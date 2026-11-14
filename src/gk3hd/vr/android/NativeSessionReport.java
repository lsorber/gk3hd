package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.UUID;
import java.util.function.LongSupplier;

/** Render-thread counters for calls accepted by a native runtime, not display delivery.
 * No pixel readbacks, per-frame file writes or synthetic tracking are needed.
 */
final class NativeSessionReport {
    static final String FILE_NAME="xr-host-status.json";
    static final String LAST_STALL_FILE="xr-last-graphics-stall.json";
    static final String LAST_GAME_OUTAGE_FILE="xr-last-game-outage.json";
    static final String LAST_STARTUP_FILE="xr-last-startup-without-image.json";
    private static final long GAP_CHECKPOINT_NS = 1_000_000_000L;
    private static final long INTERVAL_BUCKET_NS = 250_000L;
    static final long UNKNOWN_POSE_TIME = Long.MIN_VALUE;
    enum ResolutionSource {
        RUNTIME_RECOMMENDED("runtime_recommended"),
        HEADSET_DEFAULT("headset_default"),
        FIXTURE_OVERRIDE("fixture_override"),
        LAUNCH_OVERRIDE("launch_override");

        final String label;
        ResolutionSource(String label) {this.label=label;}
    }
    enum Output {
        STEREO, NO_SOURCE, NO_FRAME_ID, NO_MATCHING_POSE, NO_LAYER_SUBMITTED;

        static Output missing(boolean sourceAvailable,Integer frameId) {
            if(!sourceAvailable)return NO_SOURCE;
            return frameId==null ? NO_FRAME_ID : NO_MATCHING_POSE;
        }
    }


    private static final class Gap {
        private long start;
        private long longest;
        private boolean reported;

        boolean update(boolean active, long now) {
            if (!active) {
                if (start == 0) return false;
                longest = Math.max(longest, duration(now));
                boolean ended = reported;
                start = 0;
                reported = false;
                return ended;
            }
            if (start == 0) start = now;
            if (reported || duration(now) < GAP_CHECKPOINT_NS) return false;
            reported = true;
            return true;
        }

        private long duration(long now) { return start == 0 ? 0 : now - start; }
        double longestMs(long now) { return Math.max(longest, duration(now)) / 1e6; }
    }

    private final File output;
    private final String adapter,token,frameSession,session=UUID.randomUUID().toString();
    private final LongSupplier clock;
    private final long created;
    private long sampled,orientationValid,positionValid,orientationTracked,positionTracked,focused,renderable;
    private long submitted,stereo,game,movie,unknown,changes,gameChanges,lastSnapshot;
    private long waits,reuses;
    private long crystalGameShaderCopies,crystalGamePaddedBlits;
    private boolean haveSnapshot,completionObserved;
    private String failure;
    private String startupOutcome;
    private boolean eligible;
    private long lastStereo,lastChange,lastEligibleSnapshot,unmatchedEligible,repeatedEligible;
    private long eligibleGame,freshEligibleGame,repeatedGame,gameRepeatRun,longestGameRepeatRun,multiGameRepeatRuns;
    private long noSource,noFrameId,noMatchingPose,noLayerSubmitted;
    private Output lastEligibleMiss;
    private long lastEligibleMissAt;
    private final Gap missingStereo = new Gap();
    private final Gap heldImage = new Gap();
    private final Gap noFreshGame = new Gap();
    private boolean archiveGameOutage;
    private long gameOutageStartedAt,gameOutageEndedAt;
    private String gameOutageEndReason;
    private int lastPoseFlags;
    private boolean lastFocus,lastRenderable,sampleStatePending;
    private long sampleStateChanged,stateReportedAt;
    private int eyeWidth,eyeHeight;
    private ResolutionSource resolutionSource;
    private final long[] poseToSubmitMs=new long[257];
    private long poseToSubmitCount,poseToSubmitTotalNs;
    private final long[] freshIntervals=new long[1025];
    private long freshIntervalCount,freshIntervalTotalNs;
    private boolean haveEligibleGameImage,expectGameImage;
    private Runnable firstFocusedGame;

    NativeSessionReport(File directory,String adapter,String token,String frameSession) {
        this(directory,adapter,token,frameSession,System::nanoTime);
    }
    NativeSessionReport(File directory,String adapter,String token,String frameSession,LongSupplier clock) {
        output=new File(directory,FILE_NAME);this.adapter=adapter;this.token=token;
        this.frameSession=frameSession!=null&&frameSession.matches("[a-f0-9]{32}")?frameSession:null;
        this.clock=clock;created=clock.getAsLong();
    }

    void onFirstFocusedGame(Runnable callback) {firstFocusedGame=callback;}

    /** Record the selected render target, not physical panel pixels
     * or proof that a source image or compositor submission reached that size.
     */
    void configured(int width,int height) {
        configured(width,height,ResolutionSource.RUNTIME_RECOMMENDED);
    }

    void configured(int width,int height,ResolutionSource source) {
        if(width<=0||height<=0||width>Integer.MAX_VALUE/2)
            throw new IllegalArgumentException("Invalid configured stereo dimensions");
        eyeWidth=width;eyeHeight=height;resolutionSource=source;
    }

    /** Request a bounded checkpoint even if tracking/focus prevents submission. */
    boolean sampled(int flags,boolean hasFocus,boolean shouldRender) {
        if(sampled==0||lastPoseFlags!=flags||lastFocus!=hasFocus||lastRenderable!=shouldRender) {
            lastPoseFlags=flags;lastFocus=hasFocus;lastRenderable=shouldRender;
            sampleStateChanged=clock.getAsLong();sampleStatePending=true;
        }
        // There may be no subsequent submission while the runtime withholds
        // rendering. Stop counting an eligible image outage at this sample,
        // rather than charging tracking/focus loss to a stalled producer.
        boolean outageEnded=false;
        if((flags&3)==3&&hasFocus&&shouldRender)eligible=true;
        else outageEnded=withoutSample("runtime_ineligible");
        sampled++;
        if((flags&1)!=0)orientationValid++;
        if((flags&2)!=0)positionValid++;
        if((flags&5)==5)orientationTracked++;
        if((flags&10)==10)positionTracked++;
        if(hasFocus)focused++;
        if(shouldRender)renderable++;
        if(outageEnded||!sampleStatePending)return outageEnded;
        long now=clock.getAsLong();
        return now-sampleStateChanged>=100_000_000L&&
            (stateReportedAt==0||now-stateReportedAt>=1_000_000_000L);
    }

    /** A runtime that withholds a frame ends eligibility without a new sample. */
    boolean withoutSample() {return withoutSample("no_runtime_frame");}

    private boolean withoutSample(String reason) {
        if(!eligible)return false;
        eligible=false;
        long now=clock.getAsLong();
        missingStereo.update(false,now);
        heldImage.update(false,now);
        lastEligibleSnapshot=0;
        gameRepeatRun=0;
        haveEligibleGameImage=false;
        return endGameOutage(now,reason);
    }

    private boolean endGameOutage(long now,String reason) {
        if(!noFreshGame.update(false,now))return false;
        gameOutageEndedAt=now;
        gameOutageEndReason=reason;
        archiveGameOutage=true;
        return true;
    }

    /** Call only after the runtime submission returns successfully. A matching
     * pose permits stereo submission; the immutable snapshot identifies pixels.
     * Negative snapshots belong to native movies, not new game-renderer images.
     * Checkpoint first submissions, sustained missing or stale game images,
     * and recovery. No per-frame file writes or screenshot readbacks.
     */
    boolean submitted(Output output,long snapshot) {
        return submitted(output,snapshot,UNKNOWN_POSE_TIME);
    }

    boolean submitted(Output output,long snapshot,long poseObserved) {
        boolean milestone=submitted++==0;
        long now=clock.getAsLong();
        boolean matched=output==Output.STEREO;
        boolean changed=matched&&snapshot!=0&&(!haveSnapshot||snapshot!=lastSnapshot);
        boolean missing=eligible&&!matched;
        long eligibleSnapshot=eligible&&matched ? snapshot : 0;
        boolean repeated=eligibleSnapshot!=0&&eligibleSnapshot==lastEligibleSnapshot;
        lastEligibleSnapshot=eligibleSnapshot;
        if(missing) {
            unmatchedEligible++;
            lastEligibleMiss=output;lastEligibleMissAt=now;
            switch(output) {
                case NO_SOURCE: noSource++;break;
                case NO_FRAME_ID: noFrameId++;break;
                case NO_MATCHING_POSE: noMatchingPose++;break;
                case NO_LAYER_SUBMITTED: noLayerSubmitted++;break;
                default: throw new AssertionError(output);
            }
        }
        if(repeated)repeatedEligible++;
        if(eligibleSnapshot>0)eligibleGame++;
        if(repeated&&eligibleSnapshot>0) {
            repeatedGame++;
            gameRepeatRun++;
            longestGameRepeatRun=Math.max(longestGameRepeatRun,gameRepeatRun);
            if(gameRepeatRun==2)multiGameRepeatRuns++;
        } else gameRepeatRun=0;
        milestone|=missingStereo.update(missing,now);
        milestone|=heldImage.update(repeated,now);
        // Focus loss breaks timing continuity. Gameplay can still be the expected
        // source when focus returns, even if its first fresh image never arrives.
        if(eligible&&expectGameImage&&(!matched||(snapshot>0&&!changed))) {
            if(noFreshGame.update(true,now)) {
                gameOutageStartedAt=noFreshGame.start;
                gameOutageEndedAt=0;
                gameOutageEndReason=null;
                archiveGameOutage=true;
                milestone=true;
            }
        } else {
            milestone|=endGameOutage(now,snapshot>0 ? "fresh_game_image" : "source_changed");
        }
        if(!matched)return milestone;
        lastStereo=now;
        milestone|=stereo++==0;
        if(snapshot>0)milestone|=game++==0;
        else if(snapshot<0)milestone|=movie++==0;
        else unknown++;
        if(snapshot<=0) {
            haveEligibleGameImage=false;
            expectGameImage=false;
        } else if(eligible) expectGameImage=true;
        if(changed) {
            changes++;if(snapshot>0)gameChanges++;
            if(eligible&&snapshot>0) {
                freshEligibleGame++;
                if(firstFocusedGame!=null) {
                    Runnable completed=firstFocusedGame;
                    firstFocusedGame=null;
                    completed.run();
                }
                long interval=now-lastChange;
                if(haveEligibleGameImage&&interval>0) {
                    int bucket=(int)Math.min(interval/INTERVAL_BUCKET_NS,freshIntervals.length-1);
                    freshIntervals[bucket]++;
                    freshIntervalCount++;
                    freshIntervalTotalNs+=interval;
                }
                haveEligibleGameImage=true;
            }
            if(eligible&&snapshot>0&&poseObserved!=UNKNOWN_POSE_TIME) {
                long age=now-poseObserved;
                if(age>=0) {
                    int bucket=(int)Math.min(age/1_000_000L,poseToSubmitMs.length-1);
                    poseToSubmitMs[bucket]++;
                    poseToSubmitCount++;
                    poseToSubmitTotalNs+=age;
                }
            }
            haveSnapshot=true;lastSnapshot=snapshot;
            lastChange=now;
        }
        return milestone;
    }

    void completion(boolean waited) {completionObserved=true;if(waited)waits++;else reuses++;}

    /** Crystal calls this after submitting a newly written gameplay target. */
    void gameEyeCopy(boolean paddedBlit) {
        if(!eligible)return;
        if(paddedBlit)crystalGamePaddedBlits++;
        else crystalGameShaderCopies++;
    }

    /** Millisecond bucket upper bound. An overflow percentile is unbounded. */
    private String poseToSubmitP95UpperMs() {
        if(poseToSubmitCount==0)return "null";
        long rank=poseToSubmitCount-poseToSubmitCount/20;
        for(int i=0;i<poseToSubmitMs.length-1;i++) {
            rank-=poseToSubmitMs[i];
            if(rank<=0)return Integer.toString(i+1);
        }
        return "null";
    }

    /** Interval bounds between fresh game images accepted by the runtime.
     * Keep gaps with repeated/missing images while tracking and focus are valid.
     */
    private String freshIntervalUpperMs(long rank) {
        if(rank==0)return "null";
        for(int i=0;i<freshIntervals.length-1;i++) {
            rank-=freshIntervals[i];
            if(rank<=0)return Double.toString((i+1)*INTERVAL_BUCKET_NS/1e6);
        }
        return "null";
    }

    /** Preserve one diagnostic across relaunch, independently of the render thread. */
    void graphicsStalled(NativeDrawProgress.Stall stall,long observed) throws IOException {
        String json="{\"schema\":1,\"adapter\":"+quote(adapter)+
            ",\"session_id\":"+quote(session)+",\"observation_token\":"+quote(token)+
            ",\"frame_session\":"+quote(frameSession)+
            ",\"phase\":"+quote(stall.phase.name().toLowerCase(java.util.Locale.ROOT))+
            ",\"observed_epoch_ms\":"+System.currentTimeMillis()+
            ",\"observed_monotonic_ns\":"+observed+
            ",\"elapsed_ns\":"+stall.elapsedNs+"}\n";
        replace(new File(output.getParentFile(),LAST_STALL_FILE),json);
    }

    /** Called at startup, submission/outage milestones and lifecycle boundaries.
     * Replace atomically so an interrupted export cannot masquerade as a report.
     * A new presenter always has a new session ID, even without a diagnostic token.
     */
    void write(String phase,boolean sessionEnded,Throwable error) throws IOException {
        if(error!=null)failure=error.getClass().getName();
        boolean startupEnded=stereo==0 && startupOutcome==null &&
                (phase.equals("initialization_failed")||phase.equals("failed")||
                 phase.equals("runtime_exit")||phase.equals("closed"));
        if(startupEnded)startupOutcome=phase;
        long now=clock.getAsLong();
        if(sessionEnded||phase.equals("paused")||phase.equals("failed")) {
            haveEligibleGameImage=false;
            lastEligibleSnapshot=0;
            gameRepeatRun=0;
            endGameOutage(now,phase);
        }
        if(phase.equals("closed")||phase.equals("failed"))expectGameImage=false;
        if(sessionEnded) {
            missingStereo.update(false,now);
            heldImage.update(false,now);
        }
        String json="{\"schema\":1,\"scope\":\"runtime_api_only\",\"adapter\":"+quote(adapter)+
            ",\"session_id\":"+quote(session)+",\"observation_token\":"+quote(token)+
            ",\"frame_session\":"+quote(frameSession)+
            ",\"phase\":"+quote(phase)+",\"failure\":"+quote(failure)+
            ",\"startup_outcome\":"+quote(startupOutcome)+
            ",\"configured_eye_width_px\":"+(eyeWidth==0?"null":Integer.toString(eyeWidth))+
            ",\"configured_eye_height_px\":"+(eyeHeight==0?"null":Integer.toString(eyeHeight))+
            ",\"resolution_source\":"+quote(resolutionSource==null?null:resolutionSource.label)+
            ",\"created_monotonic_ns\":"+created+",\"reported_monotonic_ns\":"+now+
            ",\"elapsed_seconds\":"+((now-created)/1e9)+",\"sampled_frames\":"+sampled+
            ",\"orientation_valid_frames\":"+orientationValid+",\"position_valid_frames\":"+positionValid+
            ",\"orientation_tracked_frames\":"+orientationTracked+",\"position_tracked_frames\":"+positionTracked+
            ",\"focused_frames\":"+focused+",\"renderable_frames\":"+renderable+
            ",\"last_pose_flags\":"+(sampled==0?"null":Integer.toString(lastPoseFlags))+
            ",\"last_sample_focused\":"+(sampled==0?"null":Boolean.toString(lastFocus))+
            ",\"last_sample_renderable\":"+(sampled==0?"null":Boolean.toString(lastRenderable))+
            ",\"sample_state_changed_monotonic_ns\":"+(sampled==0?"null":Long.toString(sampleStateChanged))+
            ",\"api_submissions\":"+submitted+",\"stereo_submissions\":"+stereo+
            ",\"game_submissions\":"+game+",\"movie_submissions\":"+movie+
            ",\"unknown_source_submissions\":"+unknown+",\"source_image_changes\":"+changes+
            ",\"game_image_changes\":"+gameChanges+
            ",\"host_pose_to_submit_samples\":"+poseToSubmitCount+
            ",\"host_pose_to_submit_mean_ms\":"+(poseToSubmitCount==0?"null":
                Double.toString(poseToSubmitTotalNs/1e6/poseToSubmitCount))+
            ",\"host_pose_to_submit_p95_upper_ms\":"+poseToSubmitP95UpperMs()+
            ",\"fresh_game_submit_intervals\":"+freshIntervalCount+
            ",\"fresh_game_submit_interval_mean_ms\":"+(freshIntervalCount==0?"null":
                Double.toString(freshIntervalTotalNs/1e6/freshIntervalCount))+
            ",\"fresh_game_submit_interval_p50_upper_ms\":"+
                freshIntervalUpperMs(freshIntervalCount-freshIntervalCount/2)+
            ",\"fresh_game_submit_interval_p95_upper_ms\":"+
                freshIntervalUpperMs(freshIntervalCount-freshIntervalCount/20)+
            ",\"last_stereo_monotonic_ns\":"+lastStereo+
            ",\"last_source_change_monotonic_ns\":"+lastChange+
            ",\"unmatched_eligible_submissions\":"+unmatchedEligible+
            ",\"eligible_without_stereo_source\":"+noSource+
            ",\"eligible_without_source_frame_id\":"+noFrameId+
            ",\"eligible_without_matching_pose\":"+noMatchingPose+
            ",\"eligible_without_layer_after_pose_match\":"+noLayerSubmitted+
            ",\"last_eligible_stereo_miss\":"+quote(lastEligibleMiss==null ? null :
                lastEligibleMiss.name().toLowerCase(java.util.Locale.ROOT))+
            ",\"last_eligible_stereo_miss_monotonic_ns\":"+(lastEligibleMiss==null ? "null" : Long.toString(lastEligibleMissAt))+
            ",\"eligible_gap_start_monotonic_ns\":"+missingStereo.start+
            ",\"longest_eligible_gap_ms\":"+missingStereo.longestMs(now)+
            ",\"repeated_eligible_submissions\":"+repeatedEligible+
            ",\"eligible_game_submissions\":"+eligibleGame+
            ",\"fresh_eligible_game_submissions\":"+freshEligibleGame+
            ",\"repeated_eligible_game_submissions\":"+repeatedGame+
            ",\"longest_eligible_game_repeat_run\":"+longestGameRepeatRun+
            ",\"eligible_game_repeat_runs_of_two_or_more\":"+multiGameRepeatRuns+
            ",\"held_image_start_monotonic_ns\":"+heldImage.start+
            ",\"longest_held_image_ms\":"+heldImage.longestMs(now)+
            ",\"eligible_no_fresh_game_start_monotonic_ns\":"+noFreshGame.start+
            ",\"longest_eligible_no_fresh_game_ms\":"+noFreshGame.longestMs(now)+
            ",\"last_game_outage_start_monotonic_ns\":"+(gameOutageStartedAt==0?"null":Long.toString(gameOutageStartedAt))+
            ",\"last_game_outage_end_monotonic_ns\":"+(gameOutageEndedAt==0?"null":Long.toString(gameOutageEndedAt))+
            ",\"last_game_outage_end_reason\":"+quote(gameOutageEndReason)+
            ",\"crystal_game_shader_copies\":"+crystalGameShaderCopies+
            ",\"crystal_game_padded_blits\":"+crystalGamePaddedBlits+
            ",\"output_completion_waits\":"+(completionObserved?Long.toString(waits):"null")+
            ",\"output_completion_reuses\":"+(completionObserved?Long.toString(reuses):"null")+
            ",\"session_end_completed\":"+sessionEnded+"}\n";
        replace(output,json);
        if(startupEnded)replace(new File(output.getParentFile(),LAST_STARTUP_FILE),json);
        // Keep the latest sustained episode and its outcome across relaunch.
        if(archiveGameOutage)
            replace(new File(output.getParentFile(),LAST_GAME_OUTAGE_FILE),json);
        archiveGameOutage=false;
        if(sampled!=0) {sampleStatePending=false;stateReportedAt=now;}
    }

    private static void replace(File output,String json) throws IOException {
        File pending=new File(output.getParentFile(),output.getName()+".tmp");
        Files.write(pending.toPath(),json.getBytes(StandardCharsets.UTF_8));
        Files.move(pending.toPath(),output.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }

    private static String quote(String value) {
        if(value==null)return "null";
        StringBuilder result=new StringBuilder("\"");
        for(int i=0;i<value.length();i++) {
            char c=value.charAt(i);
            if(c=='"'||c=='\\')result.append('\\').append(c);
            else if(c<32)result.append(String.format(java.util.Locale.ROOT,"\\u%04x",(int)c));
            else result.append(c);
        }
        return result.append('"').toString();
    }
}
