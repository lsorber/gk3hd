package org.gk3hd.standalone;

import android.app.Activity;
import android.graphics.Bitmap;
import android.opengl.GLES30;
import android.util.Log;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Non-presenting game integration fixture, not a headset backend or fallback.
 * Simulated head input is confined to this debug-only activity. Actual game
 * stereo pixels stay in a private offscreen framebuffer and bounded captures.
 * It never calls a Pimax API or submits those images to a VR compositor.
 */
public final class OffHeadGamePresenter implements XrPresenter {
    private StartupFrameStrip startupStrip;
    private final FixtureEyeExtent sourceExtent;
    private final int eyeWidth,eyeHeight;
    private final int consumerHz;
    private final int drawHz;
    private final int inputHz,pumpHz;
    private final TrackingWorker independentTracking;
    private boolean readerActive;
    private volatile InputSeed readerSeed;
    private volatile InputPose readerPose;
    private int readerSamples;
    private final boolean restoreCycles;
    private final TravelVisibilitySamples travelVisibility;
    private int sceneCycle;
    private long sceneCycleStarted;
    private final java.util.ArrayList<long[]> restoredImages=new java.util.ArrayList<>();
    private static final class InputSeed {
        final long time;final double seconds;final boolean moving;final XrInput input;
        InputSeed(long time,double seconds,boolean moving,XrInput input) {
            this.time=time;this.seconds=seconds;this.moving=moving;this.input=input;
        }
    }
    private static final class InputPose {
        final int id;final float[] head;
        InputPose(int id,float[] head) {this.id=id;this.head=head;}
    }
    private final boolean retainOutput;
    private final boolean copiedFrameTrace;
    private final boolean worldMotion;
    private long retainedSnapshot;
    private final Activity activity;
    private final Source source;
    private final String scenario;
    private final String pimaxApplicationMode;
    private final boolean correctnessOnly;
    private final NativeGameFlow gameFlow;
    private final FrameProgressWatchdog watchdog;
    private final boolean worldWatchdog;
    private final java.util.HashSet<Integer> ids=new java.util.HashSet<>();
    private final FramePoses<Long> poses=new FramePoses<>();
    private final int firstFrameId=new java.security.SecureRandom().nextInt();
    private final java.util.ArrayList<Double> poseAges=new java.util.ArrayList<>();
    private OutputFenceTrace outputTrace;
    private MetadataCompletionTrace metadataTrace;
    private final java.util.ArrayList<long[]> frameEvents=new java.util.ArrayList<>();
    private final long[][] posePublications;
    private int posePublicationCount;
    private boolean finishPending,traceWritten;
    private long finishDeadline;
    private long tracedOutputs;
    private long paddedEyeCopies;
    private boolean publicationDriven;
    private long lastPublication,publicationWakes,sensorSamples;
    private long unmatchedSourceSamples;
    private int unmatchedPoseLogs;
    private boolean quitThreadDump;
    private File guestLog;
    private boolean startupSourceObserved;
    private int fbo,texture,captures,blackSamples;
    private volatile int frame;
    private long[] lastCaptureVisible;
    private int lastCaptureReviewEye;
    private int startupMovieCaptures;
    private long nextStartupMovieCapture;
    private long started,lastReport,firstWorld,lastWorld,nextTick,nextCapture;
    private long nextDraw,nextInput;
    private long measuredDraws,drawNanos,drawCpuNanos;
    private long backStarted;
    private long inspectStarted;
    private long navigationStarted;
    private long turnStarted;
    private long steadyFirst,steadyLast,steadyFrames;
    private long steadyReceiptLast;
    // This explicitly selected device benchmark is not a normal/unit-test load.
    // Complete segments expose a slow start hidden by a whole-window average.
    private static final long BENCHMARK_NANOS=30_000_000_000L;
    private final boolean quickProfile;
    private final long[] tenSecondFrames=new long[3];
    private long[] steadySnapshotStart;
    private long[] steadySnapshotEnd;
    private long[] producedFirst,producedLast;
    private long warmFirst,warmLast;
    private final ExplorationSoak explorationSoak;
    private final boolean stationarySoak;
    private boolean benchmarkWorldConfirmed,benchmarkFinished;
    private final java.util.ArrayList<Double> arrivals=new java.util.ArrayList<>();
    private boolean paused;
    private volatile boolean closing;
    private boolean firstCaptureSparse;
    public OffHeadGamePresenter(Activity activity,Source source) {
        this.activity=activity;this.source=source;
        try {
            android.os.Bundle metadata=activity.getPackageManager().getApplicationInfo(
                activity.getPackageName(),android.content.pm.PackageManager.GET_META_DATA).metaData;
            pimaxApplicationMode=metadata==null ? null : metadata.getString("com.pimax.vr.application.mode");
        } catch(android.content.pm.PackageManager.NameNotFoundException error) {
            throw new IllegalStateException("Cannot inspect the fixture application's VR declaration",error);
        }
        copiedFrameTrace=activity.getIntent().getBooleanExtra("gk3hd_native_vulkan",false);
        worldWatchdog=activity.getIntent().getBooleanExtra("gk3hd_test_world_watchdog",false);
        watchdog=worldWatchdog ? new FrameProgressWatchdog(500_000_000L) :
            activity.getIntent().getBooleanExtra("gk3hd_test_frame_watchdog",false) ? new FrameProgressWatchdog() : null;
        if(worldWatchdog)watchdog.pause();
        sourceExtent=new FixtureEyeExtent(activity.getIntent().getIntExtra("gk3hd_test_eye",2060),
            activity.getIntent().getIntExtra("gk3hd_test_eye_height",activity.getIntent().getIntExtra("gk3hd_test_eye",2060)));
        FixtureEyeExtent outputExtent=new FixtureEyeExtent(
            activity.getIntent().getIntExtra("gk3hd_test_output_eye",sourceExtent.width),
            activity.getIntent().getIntExtra("gk3hd_test_output_eye_height",sourceExtent.height));
        eyeWidth=outputExtent.width;eyeHeight=outputExtent.height;
        consumerHz=activity.getIntent().getIntExtra("gk3hd_test_consumer_hz",90);
        drawHz=activity.getIntent().getIntExtra("gk3hd_test_draw_hz",consumerHz);
        if(drawHz!=30&&drawHz!=90&&drawHz!=120) throw new IllegalArgumentException("Unsupported test draw cadence");
        inputHz=activity.getIntent().getIntExtra("gk3hd_test_input_hz",consumerHz);
        pumpHz=activity.getIntent().getIntExtra("gk3hd_test_pump_hz",consumerHz);
        if((inputHz!=90&&inputHz!=120&&inputHz!=180&&inputHz!=360)||
                (pumpHz!=90&&pumpHz!=120&&pumpHz!=360)||inputHz>pumpHz)
            throw new IllegalArgumentException("Unsupported test input/poll cadence");
        retainOutput=activity.getIntent().getBooleanExtra("gk3hd_test_retain_output",false);
        scenario=activity.getIntent().getStringExtra("gk3hd_scenario");
        correctnessOnly=activity.getIntent().getBooleanExtra("gk3hd_test_correctness_only",false);
        if(worldWatchdog&&!"benchmark".equals(scenario)) throw new IllegalArgumentException("World watchdog requires the bounded benchmark");
        worldMotion=activity.getIntent().getBooleanExtra("gk3hd_test_world_motion",false);
        int soakSeconds=activity.getIntent().getIntExtra("gk3hd_test_exploration_soak_seconds",0);
        if(soakSeconds!=0&&(!"benchmark".equals(scenario)||!worldMotion))
            throw new IllegalArgumentException("Exploration soak requires the moving world fixture");
        explorationSoak=new ExplorationSoak(soakSeconds);
        stationarySoak=activity.getIntent().getBooleanExtra("gk3hd_test_stationary_soak",false);
        if(stationarySoak&&soakSeconds==0)
            throw new IllegalArgumentException("Stationary preparation requires an exploration soak duration");
        quickProfile=activity.getIntent().getBooleanExtra("gk3hd_test_quick_profile",false);
        if(quickProfile&&(!"benchmark".equals(scenario)||!worldMotion))
            throw new IllegalArgumentException("Quick profiling requires a moving benchmark");
        if((eyeWidth!=sourceExtent.width||eyeHeight!=sourceExtent.height)&&
                (!quickProfile||(long)eyeWidth*sourceExtent.height!=(long)eyeHeight*sourceExtent.width||
                activity.getIntent().getBooleanExtra("gk3hd_test_selected_image_pixels",false)))
            throw new IllegalArgumentException("Split eye extents require a moving profile with matching aspect ratios");
        if((inputHz!=consumerHz||pumpHz!=consumerHz)&&!quickProfile)
            throw new IllegalArgumentException("Independent input/poll cadence requires the quick benchmark");
        boolean tracePosePublications=activity.getIntent().getBooleanExtra("gk3hd_test_pose_publications",false);
        if(tracePosePublications&&(!quickProfile||!activity.getIntent().getBooleanExtra("gk3hd_test_frame_events",true)))
            throw new IllegalArgumentException("Pose publication tracing requires the quick frame-event benchmark");
        posePublications=tracePosePublications ? new long[4096][4] : null;
        restoreCycles=activity.getIntent().getBooleanExtra("gk3hd_test_restore_cycles",false);
        if(restoreCycles&&!quickProfile)throw new IllegalArgumentException("Restore cycles require the moving quick benchmark");
        boolean independent=activity.getIntent().getBooleanExtra("gk3hd_test_independent_tracking",false);
        if(independent&&(!quickProfile||!tracePosePublications||inputHz!=360||pumpHz!=360))
            throw new IllegalArgumentException("Concurrent reader requires the traced 360-Hz quick benchmark");
        independentTracking=independent ? new TrackingWorker(inputHz) : null;
        if(worldMotion&&!"benchmark".equals(scenario)) throw new IllegalArgumentException("Motion requires a bounded world benchmark");
        gameFlow="save".equals(scenario)||"benchmark".equals(scenario) ? new NativeGameFlow(activity) : null;
        if(gameFlow!=null&&gameFlow.longTravel()&&!restoreCycles)
            throw new IllegalArgumentException("Long travel requires the bounded multi-Restore journey");
        try {travelVisibility=gameFlow!=null&&gameFlow.longTravel()?new TravelVisibilitySamples(activity,eyeWidth*2,eyeHeight):null;}
        catch(Exception error){throw new IllegalStateException("Cannot prepare travel visibility evidence",error);}
        if(gameFlow!=null&&worldMotion&&"benchmark".equals(scenario))gameFlow.alignMeasurementMotion();
        if(activity.getIntent().getBooleanExtra("gk3hd_test_startup_strip",false)&&
                (gameFlow==null||!gameFlow.startupCaptureSequence()))
            throw new IllegalArgumentException("Startup strip requires the isolated opening-room journey");
        if(activity.getIntent().getBooleanExtra("gk3hd_test_padded_eye_blit",false)) {
            if(!quickProfile||copiedFrameTrace||
                    !activity.getIntent().getBooleanExtra("gk3hd_test_frame_events",true))
                throw new IllegalArgumentException("Eye-copy comparison requires the traced moving benchmark");
            source.preferPaddedEyeBlit();
        }
        prepareGuest();
        Log.i("GK3HDXR","OFF-HEAD TEST: simulated viewer, real game/GPU; no headset compositor");
    }
    @Override public void prepareGuest() {
        try {source.configure(sourceExtent.width,sourceExtent.height);} catch(Exception error) {throw new IllegalStateException(error);}
    }
    @Override public void onSurfaceCreated(GL10 gl,EGLConfig config) {
        if("benchmark".equals(scenario)) {
            // The benchmark renders into its owned offscreen target. Swapping
            // a blank framework window adds a second, unrelated presentation
            // cadence that the real vendor backend does not have.
            ((com.winlator.XServerDisplayActivity)activity).getXServerView().setExternalPresentation(true);
        }
        source.onSurfaceCreated(gl,config);
        if(activity.getIntent().getBooleanExtra("gk3hd_test_metadata_completions",false)) {
            if(!"benchmark".equals(scenario)||copiedFrameTrace)
                throw new IllegalArgumentException("Metadata completion tracing requires the leased benchmark");
            metadataTrace=new MetadataCompletionTrace();
            ((com.winlator.renderer.WinlatorStereoSource)source).observeSnapshotCompletions(metadataTrace::complete);
        }
        File gameDirectory=new File(com.winlator.xenvironment.RootFS.find(activity).getRootDir(),"home/xuser-1/.wine/drive_c/gk3hd-vr");
        guestLog=new File(gameDirectory,"standalone-launch.log");
        publicationDriven="benchmark".equals(scenario)&&(activity.getIntent().getBooleanExtra("gk3hd_test_publication_wake",false)||
            new File(gameDirectory,"gk3hd-publication-wake.txt").isFile());
        PresentCopyRetirementTests.run();
        BorrowedPresentFramesTests.run();
        BorrowedPresentGpuTests.run();
        LeasedMetadataTests.run();
        FrameIdentityGpuTests.run();
        if(activity.getIntent().getBooleanExtra("gk3hd_test_startup_strip",false))
            StartupFrameStripTests.run(activity);
        if(activity.getIntent().getBooleanExtra("gk3hd_test_frame_events","benchmark".equals(scenario))) {
            if(!"benchmark".equals(scenario))throw new IllegalArgumentException("Frame events require the bounded moving benchmark");
            outputTrace=new OutputFenceTrace(new OutputFenceTrace.Fences(){
                public long create(){long fence=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);if(fence!=0)GLES30.glFlush();return fence;}
                public int status(long fence){int status=GLES30.glClientWaitSync(fence,0,0);
                    if(status==GLES30.GL_TIMEOUT_EXPIRED)return 0;
                    return status==GLES30.GL_ALREADY_SIGNALED||status==GLES30.GL_CONDITION_SATISFIED ? 1 : -1;}
                public void delete(long fence){GLES30.glDeleteSync(fence);}
            },System::nanoTime,8);
        }
        int[] names=new int[1];GLES30.glGenTextures(1,names,0);texture=names[0];
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
        GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,eyeWidth*2,eyeHeight,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MIN_FILTER,GLES30.GL_NEAREST);
        GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MAG_FILTER,GLES30.GL_NEAREST);
        GLES30.glGenFramebuffers(1,names,0);fbo=names[0];GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo);
        GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture,0);
        if(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("Off-head game framebuffer incomplete");
        started=lastReport=System.nanoTime();
    }
    @Override public void onSurfaceChanged(GL10 gl,int width,int height) {source.onSurfaceChanged(gl,eyeWidth*2,eyeHeight);}
    @Override public void onDrawFrame(GL10 gl) {
        if(paused||closing) return;
        try {
            // Unlike the real backend there is no blocking compositor Submit.
            // Bound the simulated sensor by the selected diagnostic cadence
            // instead of flooding UDP/CPU. This does not set headset refresh.
            if(watchdog!=null) watchdog.mark("publication / sensor wait");
            boolean publicationWake=false;
            if(publicationDriven) {
                long observed=((com.winlator.renderer.WinlatorStereoSource)source).awaitPublication(lastPublication,nextTick);
                publicationWake=observed!=lastPublication;lastPublication=observed;
                if(publicationWake)publicationWakes++;
            } else {
                long remaining=nextTick-System.nanoTime();
                if(remaining>0)java.util.concurrent.locks.LockSupport.parkNanos(remaining);
            }
            long now=System.nanoTime();
            if(watchdog!=null) watchdog.mark("output observer poll");
            if(outputTrace!=null)outputTrace.poll();
            if(finishPending) {
                // Retire metadata through its ordinary nonblocking source poll.
                // A selected image may have reached CPU receipt before this fence.
                if(metadataTrace!=null)((com.winlator.renderer.WinlatorStereoSource)source).pollSnapshotCompletions();
                if(outputTrace.pending()!=0||metadataTrace!=null&&metadataTrace.pending()!=0) {
                    if(now>finishDeadline)throw new IllegalStateException("Completion drain timed out: output="+
                        outputTrace.pending()+" metadata="+(metadataTrace==null ? 0 : metadataTrace.pending())+
                        " pending_outputs="+outputTrace.describePending());
                    return;
                }
                writeFrameTrace();finishPending=false;report();
                GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo);GLES30.glViewport(0,0,eyeWidth*2,eyeHeight);
                captureBenchmark();gameFlow.finishBenchmark(System.nanoTime());return;
            }
            double elapsed=(now-started)/1e9;
            boolean inputTick=!publicationDriven||now>=nextTick;
            if(inputTick) {
            long period=1_000_000_000L/pumpHz;
            if(!publicationDriven||nextTick==0)nextTick=now+period;
            else {do {nextTick+=period;}while(nextTick<=now);}
            }
            // Hold polling cadence fixed across the input-frequency screen.
            // Each publication keeps its actual sample time and identity;
            // the advertised display cadence remains consumerHz.
            if(inputTick&&(inputHz==pumpHz||now>=nextInput)) {
            long inputPeriod=1_000_000_000L/inputHz;
            if(!publicationDriven||nextInput==0)nextInput=now+inputPeriod;
            else {do {nextInput+=inputPeriod;}while(nextInput<=now);}
            sensorSamples++;
            // Aim at native canvas (720,733): opaque panel width 2.4 m, aspect 1280/800,
            // centered 1.6 m forward. Exercise the real game's VR action route,
            // not a desktop click intercepted by the stereo transport window.
            boolean trigger=elapsed>=6 && elapsed<12 && elapsed%2<.5;
            int buttons=trigger ? XrInput.TRIGGER : 0;
            if("inventory".equals(scenario)&&elapsed>=25&&elapsed<26) buttons|=XrInput.PRIMARY;
            float handX=.15f,handY=-.624375f;
            float turn=0,walk=0;
            if("navigation".equals(scenario)&&captures>=1) {
                if(navigationStarted==0) navigationStarted=now;
                long age=now-navigationStarted;
                // A capture intentionally stalls this test presenter. Let the
                // recovered neutral sample re-arm controls before deflecting.
                if(age>=500_000_000L&&age<1_250_000_000L) walk=1;
                if(captures>=2) {
                    if(turnStarted==0) turnStarted=now;
                    long turnAge=now-turnStarted;
                    if(turnAge>=500_000_000L&&turnAge<1_250_000_000L) turn=1;
                }
            }
            if("inventory".equals(scenario)&&elapsed>=27&&elapsed<36) {
                // Native first inventory item near canvas (220,133). A modal
                // inventory uses the same 2.4 m opaque panel as the title.
                handX=-.7875f;handY=.5f;
                if(elapsed>=28&&elapsed<28.4) {buttons|=XrInput.TRIGGER;trigger=true;}
            }
            if("inventory".equals(scenario)&&captures==1) {
                if(inspectStarted==0) inspectStarted=now;
                // First native verb is Look, at the left of the selected
                // item's menu. Keep a released aim before its trigger edge.
                handX=-.88125f;handY=.5f;
                long inspectAge=now-inspectStarted;
                if(!firstCaptureSparse&&inspectAge>=500_000_000L&&inspectAge<1_000_000_000L) {
                    buttons|=XrInput.TRIGGER;trigger=true;
                }
            }
            if("inventory".equals(scenario)&&captures>=2) {
                // Screenshot encoding must not skip an entire short pulse.
                // Start Back only after the inspection capture has returned, and
                // release before the next pulse so native input can re-arm.
                if(backStarted==0) backStarted=now;
                long backAge=now-backStarted;
                if((backAge>=500_000_000L&&backAge<1_000_000_000L)||
                   (backAge>=2_000_000_000L&&backAge<2_500_000_000L))
                    buttons|=XrInput.SECONDARY;
            }
            XrInput.Hand right=new XrInput.Hand(new float[]{handX,handY,0,0,0,0,1},15,
                buttons,turn,0,trigger ? 1 : 0,0);
            XrInput.Hand left="navigation".equals(scenario) ?
                new XrInput.Hand(new float[]{-.15f,-.2f,0,0,0,0,1},15,0,0,walk,0,0) : XrInput.UNLOCATED;
            int frameId=0;
            if(watchdog!=null) watchdog.mark("fixture input / native state observation");
            XrInput inputs=gameFlow==null ? new XrInput(left,right) : gameFlow.input(now);
            if(watchdog!=null) watchdog.mark("tracking");
            source.focused(true); // Explicit simulated focus, never headset presence.
            // Diagnostic viewer only, never submitted to a headset compositor.
            // Sweep +/- 15 degrees while native stick input steps forward/back.
            double yaw=worldMotion ? Math.sin(gameFlow.motionSeconds(now)*.8)*Math.PI/12 : 0;
            float[] diagnosticHead={0,0,0,0,(float)Math.sin(yaw/2),0,(float)Math.cos(yaw/2)};
            if(gameFlow!=null)diagnosticHead[2]=-gameFlow.probeHeadForward(now);
            if(independentTracking!=null&&!benchmarkFinished) {
                readerSeed=new InputSeed(now,gameFlow.motionSeconds(now),gameFlow.motionActive(),inputs);
                if(!readerActive) {independentTracking.activate(this::sampleIndependent);readerActive=true;}
                independentTracking.checkFailure();
                InputPose selected=readerPose;
                if(selected!=null)source.stageTracking(selected.head,15,selected.id,diagnosticOptics());
            } else {
            frameId=firstFrameId+(++frame);poses.remember(frameId,now,15,now);
            boolean recordPose=posePublications!=null&&!benchmarkFinished;
            long publicationStart=recordPose ? System.nanoTime() : 0;
            if(activity.getIntent().getBooleanExtra("gk3hd_test_native_movie_optics",false)) {
                float[] fov={-1.5596154f/2,1.5596154f/2,1.5712752f/2,-1.5712752f/2};
                StereoViews optics=new StereoViews(new float[]{-.06352f/2,0,0,0,0,0,1},fov,
                    new float[]{.06352f/2,0,0,0,0,0,1},fov);
                source.tracking(diagnosticHead,15,.06352f,1.5596154f,1.5712752f,consumerHz,frameId,inputs,optics);
            }else source.tracking(diagnosticHead,15,.06352f,1.5596154f,1.5712752f,consumerHz,frameId,inputs);
            if(recordPose) {
                long publicationEnd=System.nanoTime();
                long[] row=posePublications[posePublicationCount++%posePublications.length];
                row[0]=Integer.toUnsignedLong(frameId);row[1]=now;
                row[2]=publicationStart;row[3]=publicationEnd;
            }
            }
            }
            if(watchdog!=null) watchdog.mark("source service");
            source.serviceFrame(gl);
            // Cost isolation: keep sensor/controller delivery unchanged while
            // reducing only the offscreen consumer's GPU copy/draw cadence.
            if(!publicationWake&&now<nextDraw) return;
            nextDraw=now+1_000_000_000L/drawHz;
            GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo);
            GLES30.glViewport(0,0,eyeWidth*2,eyeHeight);GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            GLES30.glClearColor(0,0,0,1);
            if(!retainOutput) GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            if(watchdog!=null) watchdog.mark("source lookup");
            if(source.hasStereoFrame()) {
                if(watchdog!=null) watchdog.mark("source draw");
                long drawStart=System.nanoTime(),cpuStart=android.os.Debug.threadCpuTimeNanos();
                source.drawFrame(gl,retainOutput ? retainedSnapshot : 0);
                if("benchmark".equals(scenario) ? steadyFirst!=0&&measuredWorldReady() : elapsed>=20) {
                    measuredDraws++;drawNanos+=System.nanoTime()-drawStart;
                    drawCpuNanos+=android.os.Debug.threadCpuTimeNanos()-cpuStart;
                }
                Integer id=source.renderedFrameId();
                long received=System.nanoTime();
                Long sampled=poses.match(id,received);
                if(sampled!=null&&source.renderedSnapshot()>0&&gameFlow!=null&&gameFlow.wantsRestoreListCapture(received)) {
                    int before=captures;capture(true);
                    if(captures>before)gameFlow.didRestoreListCapture(captures,id,source.renderedSnapshot(),sampled,received);
                }
                if(sampled!=null&&source.renderedSnapshot()>0&&travelVisibility!=null&&gameFlow.worldReady()&&gameFlow.motionActive())
                    travelVisibility.sample(sceneCycle,gameFlow.travelState(received),fbo,id,source.renderedSnapshot(),sampled,received);
                if(sampled!=null&&source.renderedSnapshot()>0&&advanceRestoreCycle(id,sampled,received))return;
                // Native Android movie frames have their own negative snapshot
                // namespace. This diagnostic boundary is the translated game.
                if(sampled!=null&&source.renderedSnapshot()>0&&!startupSourceObserved&&
                        activity.getIntent().getBooleanExtra("gk3hd_test_startup_observer_gate",false)) {
                    String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
                    if(token==null||!token.matches("[0-9a-f]{32}"))throw new IllegalStateException("Missing startup observer identity");
                    File ready=new File(guestLog.getParentFile(),"gk3hd-observe-ready-"+token+".txt");
                    if(ready.exists())throw new IllegalStateException("Startup observation identity is occupied");
                    org.json.JSONObject record=new org.json.JSONObject().put("token",token).put("source","game-renderer").put("pose_id",id)
                        .put("snapshot",source.renderedSnapshot()).put("sampled_ns",sampled).put("received_ns",received);
                    FixtureReport.write(new File(activity.getFilesDir(),"startup-source-match-"+token+".json"),record.toString());
                    FixtureReport.write(ready,token);startupSourceObserved=true;
                    Log.i("GK3HDXR","First matched source image published startup observation token="+token);
                }
                boolean stripRequested=activity.getIntent().getBooleanExtra("gk3hd_test_startup_strip",false);
                if(stripRequested&&sampled!=null&&gameFlow!=null&&gameFlow.startupStripReady(sampled)) {
                    if(startupStrip==null)startupStrip=new StartupFrameStrip(activity.getFilesDir(),activity.getIntent().getStringExtra("gk3hd_observation_token"));
                    if(!startupStrip.complete()) {
                        startupStrip.capture(fbo,eyeWidth,id,source.renderedSnapshot(),sampled,received);
                        if(startupStrip.complete())gameFlow.didStartupStrip();
                    }
                }
                if(!stripRequested&&sampled!=null&&gameFlow!=null&&gameFlow.wantsStartupCapture(sampled)) {
                    int before=captures;capture();
                    if(captures>before)gameFlow.didStartupCapture(captures,id,source.renderedSnapshot(),sampled,System.nanoTime());
                }
                if(sampled!=null&&gameFlow!=null&&gameFlow.wantsJeanCapture(sampled)) {
                    int before=captures;capture();
                    if(captures>before)gameFlow.didJeanCapture(captures,id,source.renderedSnapshot(),sampled,System.nanoTime(),eyeWidth,lastCaptureReviewEye,lastCaptureVisible);
                }
                if(sampled!=null&&gameFlow!=null&&gameFlow.wantsInventoryCapture()) {
                    int before=captures;capture();
                    if(captures>before)gameFlow.didInventoryCapture(captures,id,source.renderedSnapshot(),sampled,System.nanoTime());
                }
                if(sampled!=null&&gameFlow!=null&&gameFlow.startupMovie()&&
                        startupMovieCaptures<(gameFlow.storyMovieActive() ? 23 : gameFlow.titleIntroActive() ? 6 : 3)&&
                        now>=nextStartupMovieCapture&&activity.getIntent().getBooleanExtra("gk3hd_test_capture_startup_movies",false)) {
                    int before=captures;capture();nextStartupMovieCapture=System.nanoTime()+1_000_000_000L;
                    if(captures>before) {
                        startupMovieCaptures++;
                        org.json.JSONObject record=new org.json.JSONObject();
                        record.put("scope","simulated viewer; actual game/movie GPU output, no headset submission");
                        record.put("token",activity.getIntent().getStringExtra("gk3hd_observation_token"));
                        record.put("draw_ns",drawStart);record.put("sampled_ns",sampled);
                        record.put("independent_tracking",independentTracking!=null&&readerActive);
                        record.put("capture_finished_ns",System.nanoTime());
                        record.put("story_movie",gameFlow.storyMovieActive());
                        record.put("image",captures);record.put("pose_id",id);record.put("snapshot",source.renderedSnapshot());
                        FixtureReport.write(new File(activity.getFilesDir(),"startup-movie-capture-"+startupMovieCaptures+".json"),record.toString());
                    }
                }
                if(id!=null&&sampled==null&&elapsed>=20&&unmatchedPoseLogs<8) {
                    unmatchedPoseLogs++;
                    Log.w("GK3HDXR","Unmatched source pose image="+Integer.toUnsignedString(id)+
                        " latest_sent="+Integer.toUnsignedString(firstFrameId+frame)+
                        " sequence_distance="+Integer.toUnsignedString(firstFrameId+frame-id)+
                        " snapshot="+source.renderedSnapshot()+" elapsed="+elapsed);
                }
                if(id!=null&&sampled==null&&steadyFirst==0&&captures==0&&elapsed>=20&&
                    activity.getIntent().getBooleanExtra("gk3hd_test_unmatched_capture",false))capture();
                if(outputTrace!=null&&!benchmarkFinished&&steadyFirst!=0&&sampled!=null&&gameFlow.worldReady()&&
                   !source.renderedOutputUnchanged()) {
                    if(frameEvents.size()>=4096)throw new IllegalStateException("Frame timing observer bound exceeded");
                    com.winlator.renderer.WinlatorStereoSource stereo=(com.winlator.renderer.WinlatorStereoSource)source;
                    long[] events=copiedFrameTrace ? stereo.snapshotCopiedFrameEvents(id) : stereo.snapshotFrameEvents(id);
                    long copyBegin;
                    long[] row=new long[copiedFrameTrace ? 8 : 21];
                    row[0]=source.renderedSnapshot();row[1]=id&0xffffffffL;row[2]=sampled;row[3]=received;
                    if(copiedFrameTrace) {
                        if(events==null||events[0]!=row[0]||events[1]<sampled||events[3]<events[1]||
                           events[2]<events[3]||events[4]<events[2]||received<events[4])
                            throw new IllegalStateException("Incomplete owned-copy timing identity");
                        System.arraycopy(events,1,row,4,4);copyBegin=events[4];
                    } else {
                        if(events==null||events[8]==0||events[1]<sampled||events[7]<events[5])
                            throw new IllegalStateException("Incomplete exact-frame timing identity");
                        System.arraycopy(events,0,row,4,events.length);copyBegin=events[7];
                    }
                    boolean metadataFresh=metadataTrace==null||metadataTrace.issue(row);
                    boolean outputFresh=outputTrace.issue(fbo,row[0],id,sampled,copyBegin,received);
                    if(metadataTrace!=null&&metadataFresh!=outputFresh)
                        throw new IllegalStateException("Source and output observers disagree about a fresh image");
                    if(outputFresh) {
                        frameEvents.add(row);
                        if(source.renderedWithPaddedEyeBlit())paddedEyeCopies++;
                    }
                }
                if(sampled==null) {
                    retainedSnapshot=0;GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
                } else retainedSnapshot=source.renderedSnapshot();
                if(id!=null&&sampled==null) {
                    if(elapsed>=20) unmatchedSourceSamples++;
                }
                if(sampled!=null && now-started>12_000_000_000L &&
                   (!"benchmark".equals(scenario)||measuredWorldReady()) && ids.add(id)) {
                    if("benchmark".equals(scenario)) {
                        benchmarkWorldConfirmed=true;
                        // Cold shader compilation can start well after Activity
                        // startup. Warm up on fresh native-world images instead
                        // of treating a fixed wall-clock delay as steady play.
                        if(steadyFirst==0) {
                            if(explorationSoak.frames()==0&&!explorationSoak.complete()) {
                                if(!stationarySoak)gameFlow.beginPreparedMotion(now);
                                if(worldWatchdog)watchdog.resume();
                            }
                            explorationSoak.observe(now);
                            if(warmLast==0||now-warmLast>250_000_000L) warmFirst=now;
                            warmLast=now;
                            if(explorationSoak.complete()&&now-warmFirst>=(quickProfile ? 0 : 3_000_000_000L)+gameFlow.extraWarmupNanos()) {
                                steadyFirst=now;
                                if(!gameFlow.motionActive())gameFlow.beginPreparedMotion(now);
                                steadySnapshotStart=((com.winlator.renderer.WinlatorStereoSource)source).snapshotOutputCounts();
                                if(worldWatchdog)watchdog.resume();
                                if(activity.getIntent().getBooleanExtra("gk3hd_test_scheduler_ready",false)) {
                                    String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
                                    FixtureReport.write(new File(activity.getFilesDir(),"scheduler-ready-"+token+".json"),
                                        new org.json.JSONObject().put("token",token).put("start_ns",now).toString());
                                }
                                Log.i("GK3HDXR",(quickProfile ? "Ready native profile started token=" : "Warmed native benchmark started token=")+
                                    activity.getIntent().getStringExtra("gk3hd_observation_token")+" start_ns="+now);
                            }
                        }
                    }
                    if(("benchmark".equals(scenario) ? steadyFirst!=0 : elapsed>=20)&&poseAges.size()<4096) {
                        poseAges.add((received-sampled)/1e6);

                    }
                    if(firstWorld==0) firstWorld=now;lastWorld=now;
                    if("benchmark".equals(scenario)&&steadyFirst!=0) {
                        long[] produced=gameFlow.producedFrames();
                        if(produced!=null) {if(producedFirst==null) producedFirst=produced;producedLast=produced;}
                        // Delivery intervals use actual receipt times. Callback
                        // start times hide variation in source acquisition/copy.
                        if(steadyReceiptLast!=0&&arrivals.size()<4096)arrivals.add((received-steadyReceiptLast)/1e6);
                        steadyReceiptLast=received;
                        steadyLast=now;steadyFrames++;
                        long segment=(now-steadyFirst)/10_000_000_000L;
                        if(segment<tenSecondFrames.length)tenSecondFrames[(int)segment]++;
                    }
                    if("benchmark".equals(scenario)&&!benchmarkFinished&&steadyLast-steadyFirst>=(travelVisibility!=null ? 6_200_000_000L : quickProfile ? 5_000_000_000L : BENCHMARK_NANOS)) {
                        if(travelVisibility!=null)travelVisibility.endScene(sceneCycle,gameFlow.travelState(received),received);
                        steadySnapshotEnd=((com.winlator.renderer.WinlatorStereoSource)source).snapshotOutputCounts();
                        stopIndependent();benchmarkFinished=true;
                        if(worldWatchdog)watchdog.pause();
                        // Read the exact last drawn selection before completion
                        // draining may select a different pending source image.
                        // Diagnostic readbacks follow the measured interval.
                        if(activity.getIntent().getBooleanExtra("gk3hd_test_selected_image_pixels",false))
                            SelectedImagePixels.capture(activity,source,fbo,eyeWidth,eyeHeight);
                        if(outputTrace!=null) {finishPending=true;finishDeadline=System.nanoTime()+250_000_000L;return;}
                        report();
                        // Inspect exactly the measured scene, but keep all
                        // readback/PNG work outside the timing window.
                        captureBenchmark();
                        gameFlow.finishBenchmark(System.nanoTime());
                    }
                    long captureStart="inventory".equals(scenario) ? 30_000_000_000L : 18_000_000_000L;
                    if("navigation".equals(scenario)) captureStart=23_000_000_000L;
                    boolean ordinaryCapture=gameFlow!=null &&
                        activity.getIntent().getBooleanExtra("gk3hd_test_capture_game",false) && gameFlow.wantsCapture(captures);
                    boolean restoredCapture=gameFlow!=null && captures==0 &&
                        activity.getIntent().getBooleanExtra("gk3hd_test_capture_restored_output",false) &&
                        gameFlow.wantsRestoredCapture(sampled);
                    if(ordinaryCapture || restoredCapture) {
                        int before=captures;capture();if(captures>before) gameFlow.didCapture(captures,System.nanoTime());
                    } else if(gameFlow==null&&!activity.getIntent().getBooleanExtra("gk3hd_test_transport_only",false)&&captures<2 && now-started>captureStart && now>nextCapture) {
                        nextCapture=now+5_000_000_000L;capture();
                    }
                }
            } else {
                retainedSnapshot=0;GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            }
            // Keep the synchronous report out of the short timing window.
            boolean measuringQuickProfile=quickProfile&&steadyFirst!=0&&!benchmarkFinished;
            if(!measuringQuickProfile&&now-lastReport>5_000_000_000L) {
                if(watchdog!=null) watchdog.mark("periodic fixture report");
                lastReport=now;Log.i("GK3HDXR","Off-head actual distinct game frames="+ids.size()+" elapsed="+(now-started)/1e9+
                    " glError="+GLES30.glGetError());report();
                if(benchmarkFinished&&gameFlow.quitRequested()&&!quitThreadDump&&guestLog.isFile()&&guestLog.length()<262144&&
                    new String(java.nio.file.Files.readAllBytes(guestLog.toPath()),java.nio.charset.StandardCharsets.UTF_8).contains("Owned child exit=0")) {
                    quitThreadDump=true;FrameProgressWatchdog.dumpThreads("Native child exited; Android graphics retirement still pending");
                }
            }
            // Only a blank test window is shown. No simulated-view game image
            // leaves the private offscreen framebuffer except diagnostic PNGs.
            GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,0);GLES30.glClearColor(0,0,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            if(watchdog!=null) watchdog.mark("frame returned / EGL swap");
        } catch(Exception error) {
            if(outputTrace!=null){outputTrace.close();outputTrace=null;}
            paused=true;Log.e("GK3HDXR","Off-head game fixture failed",error);
            if(gameFlow!=null) {
                try {gameFlow.failed(error);}
                catch(Exception reporting){Log.e("GK3HDXR","Cannot retain native fixture failure state",reporting);}
            }
            MovieStartupDiagnostics.capture(source);
            activity.runOnUiThread(activity::finish);
        }
    }
    private void captureBenchmark() throws Exception {
        // Readback/PNG encoding deliberately follows the timing window. A
        // timing-only control can omit this work without changing the scene,
        // measured rendering, output identities or normal native Quit route.
        if(activity.getIntent().getBooleanExtra("gk3hd_test_capture_benchmark",true)) capture();
    }
    private void capture() throws Exception {capture(false);}
    private void capture(boolean preserveSparse) throws Exception {
        if(watchdog!=null)watchdog.mark("stereo screenshot readback / PNG encoding");
        // Timed startup reviews must not pause the game for a full-resolution
        // CPU pixel conversion and PNG. Only the review export is reduced;
        // game rendering and the source image remain at the selected eye size.
        int reviewWidth=gameFlow!=null&&gameFlow.startupCaptureSequence() ? Math.min(eyeWidth,640) : eyeWidth;
        int reviewHeight=(int)((long)eyeHeight*reviewWidth/eyeWidth);
        ByteBuffer bytes=capturePixels(reviewWidth,reviewHeight);
        boolean compact=gameFlow!=null&&gameFlow.allowsBlackCapture();
        int[] pixels=compact ? new int[reviewWidth*2*reviewHeight] : null;
        long nonblack=0,different=0;long[] visible={0,0};
        for(int y=0;y<reviewHeight;y++) for(int x=0;x<reviewWidth*2;x++) {
            int p=bytes.getInt((y*reviewWidth*2+x)*4);
            if(pixels!=null)pixels[(reviewHeight-y-1)*reviewWidth*2+x]=(p&0xff00ff00)|((p&0xff)<<16)|((p>>>16)&255);
            if((p&0xffffff)!=0) {nonblack++;visible[x/reviewWidth]++;}
            if(x<reviewWidth && (p&0xffffff)!=(bytes.getInt((y*reviewWidth*2+x+reviewWidth)*4)&0xffffff)) different++;
        }
        // Item inspection deliberately puts a small object on black. Requiring
        // room-sized foreground here rejects a valid native interface and
        // prevents the subsequent Back test from ever running.
        long minimum="inventory".equals(scenario) ? reviewWidth*reviewHeight/1000 : reviewWidth*reviewHeight/10;
        if(gameFlow!=null&&gameFlow.sparseInterfaceCapture())minimum=reviewWidth*reviewHeight/1000;
        if(gameFlow!=null&&gameFlow.startupMovie()&&
                            activity.getIntent().getBooleanExtra("gk3hd_test_capture_startup_movies",false))minimum=reviewWidth*reviewHeight/1000;
        if((visible[0]<minimum || visible[1]<minimum || different<100)&&
                !preserveSparse&&!(gameFlow!=null&&gameFlow.allowsBlackCapture())) {
            blackSamples++;Log.w("GK3HDXR","Off-head black/loading sample="+blackSamples+" left="+visible[0]+" right="+visible[1]+" different="+different);
            report();return; // Black transition frames are legal; do not stop loading early.
        }
        if(captures==0) firstCaptureSparse=visible[0]<reviewWidth*reviewHeight/10&&visible[1]<reviewWidth*reviewHeight/10;
        Bitmap bitmap=null;
        // Keep actual rendering/readback and full-image visibility counts at
        // the selected eye size. The NPC diagnostic only needs a compact
        // review export; PNG encoding must not dominate each control stage.
        if(compact) {
            Bitmap full=Bitmap.createBitmap(pixels,reviewWidth*2,reviewHeight,Bitmap.Config.ARGB_8888);
            bitmap=Bitmap.createScaledBitmap(full,eyeWidth,eyeHeight/2,false);full.recycle();
        }
        lastCaptureVisible=visible.clone();lastCaptureReviewEye=bitmap==null ? reviewWidth : bitmap.getWidth()/2;
        try(java.io.FileOutputStream out=new java.io.FileOutputStream(new File(activity.getFilesDir(),"offhead-game-stereo-"+(++captures)+".png"))) {
            if(bitmap==null)RgbaPng.write(out,bytes,reviewWidth*2,reviewHeight);
            else bitmap.compress(Bitmap.CompressFormat.PNG,100,out);
        } finally {if(bitmap!=null)bitmap.recycle();}
        Log.i("GK3HDXR","Off-head game stereo capture="+captures+" nonblack="+nonblack+" eyeDifferences="+different+
            " sourceEye="+sourceExtent.width+"x"+sourceExtent.height+" reviewEye="+lastCaptureReviewEye);report();
    }
    private ByteBuffer capturePixels(int reviewWidth,int reviewHeight) {
        ByteBuffer bytes=ByteBuffer.allocateDirect(reviewWidth*2*reviewHeight*4).order(ByteOrder.LITTLE_ENDIAN);
        if(reviewWidth==eyeWidth&&reviewHeight==eyeHeight) {
            GLES30.glReadPixels(0,0,eyeWidth*2,eyeHeight,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,bytes);
            return bytes;
        }
        int[] read={0},draw={0},binding={0},reviewFbo={0},reviewTexture={0};
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,read,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,draw,0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,binding,0);
        boolean scissor=GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST);
        try {
            GLES30.glGenTextures(1,reviewTexture,0);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,reviewTexture[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,reviewWidth*2,reviewHeight,0,
                GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glGenFramebuffers(1,reviewFbo,0);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,reviewFbo[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,reviewTexture[0],0);
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Startup review framebuffer is incomplete");
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo);
            GLES30.glBlitFramebuffer(0,0,eyeWidth*2,eyeHeight,0,0,reviewWidth*2,reviewHeight,
                GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,reviewFbo[0]);
            GLES30.glReadPixels(0,0,reviewWidth*2,reviewHeight,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,bytes);
            int error=GLES30.glGetError();
            if(error!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Startup review readback failed: "+error);
            return bytes;
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,read[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,draw[0]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,binding[0]);
            if(scissor)GLES30.glEnable(GLES30.GL_SCISSOR_TEST);
            if(reviewFbo[0]!=0)GLES30.glDeleteFramebuffers(1,reviewFbo,0);
            if(reviewTexture[0]!=0)GLES30.glDeleteTextures(1,reviewTexture,0);
        }
    }
    private void report() throws Exception {
        long[] outputCounts=((com.winlator.renderer.WinlatorStereoSource)source).snapshotOutputCounts();
        long[] steadyCounts=steadySnapshotEnd==null ? outputCounts : steadySnapshotEnd;
        double fps=lastWorld>firstWorld ? (ids.size()-1)*1e9/(lastWorld-firstWorld) : 0;
        double steadyFps=steadyLast>steadyFirst ? (steadyFrames-1)*1e9/(steadyLast-steadyFirst) : 0;
        Double[] sorted=arrivals.toArray(new Double[0]);java.util.Arrays.sort(sorted);
        double p95=sorted.length==0 ? 0 : sorted[(int)Math.ceil(sorted.length*.95)-1];
        Double[] ages=poseAges.toArray(new Double[0]);java.util.Arrays.sort(ages);
        double poseP95=ages.length==0 ? 0 : ages[(int)Math.ceil(ages.length*.95)-1];
        double poseMax=ages.length==0 ? 0 : ages[ages.length-1];
        java.io.StringWriter text=new java.io.StringWriter();
        try(java.io.PrintWriter out=new java.io.PrintWriter(text)) {
            out.println("{\"scope\":\"real game stereo with simulated viewer; no headset presentation or tracking qualification\",\"token\":"+
                org.json.JSONObject.quote(activity.getIntent().getStringExtra("gk3hd_observation_token"))+
                ",\"fixture_token\":"+org.json.JSONObject.quote(activity.getIntent().getStringExtra("gk3hd_fixture_token"))+
                ",\"pimax_application_mode\":"+(pimaxApplicationMode==null ? "null" : org.json.JSONObject.quote(pimaxApplicationMode))+
                ",\"graphics_runtime\":"+org.json.JSONObject.quote(activity.getIntent().getStringExtra("gk3hd_graphics_runtime"))+
                ",\"graphics_profile_source\":"+org.json.JSONObject.quote(
                    activity.getIntent().hasExtra("gk3hd_test_graphics_runtime") ? "declared-fixture" : "runtime-discovery")+
                ",\"rgb565_layout\":"+org.json.JSONObject.quote(activity.getIntent().getStringExtra("gk3hd_rgb565_layout"))+
                ",\"scenario\":\""+scenario+"\",\"long_travel_reliability\":"+(travelVisibility!=null)+",\"correctness_only\":"+correctnessOnly+",\"distinct_game_frames\":"+
                ids.size()+",\"game_fps\":"+fps+",\"eye_size\":"+(sourceExtent.width==sourceExtent.height ? Integer.toString(sourceExtent.width) : "null")+
                ",\"eye_width\":"+sourceExtent.width+",\"eye_height\":"+sourceExtent.height+
                ",\"output_eye_width\":"+eyeWidth+",\"output_eye_height\":"+eyeHeight+",\"consumer_hz\":"+consumerHz+
                ",\"world_motion\":"+worldMotion+",\"quick_profile\":"+quickProfile+
                ",\"draw_hz\":"+drawHz+
                ",\"input_hz\":"+inputHz+",\"pump_hz\":"+pumpHz+
                ",\"publication_driven\":"+publicationDriven+",\"publication_wakes\":"+publicationWakes+",\"sensor_samples\":"+sensorSamples+
                ",\"native_world_confirmed\":"+benchmarkWorldConfirmed+
                ",\"retained_output\":"+retainOutput+
                ",\"snapshot_output_copies\":"+outputCounts[0]+",\"snapshot_output_reuses\":"+outputCounts[1]+
                ",\"snapshot_input_copies\":"+outputCounts[2]+",\"snapshot_completions\":"+outputCounts[3]+
                ",\"steady_snapshot_input_copies\":"+(steadySnapshotStart==null ? 0 : steadyCounts[2]-steadySnapshotStart[2])+
                ",\"steady_snapshot_output_copies\":"+(steadySnapshotStart==null ? 0 : steadyCounts[0]-steadySnapshotStart[0])+
                ",\"source_draws\":"+measuredDraws+",\"source_wall_ms\":"+(measuredDraws==0 ? 0 : drawNanos/1e6/measuredDraws)+
                ",\"source_cpu_ms\":"+(measuredDraws==0 ? 0 : drawCpuNanos/1e6/measuredDraws)+
                ",\"latest_frame_age_ms\":"+(lastWorld==0 ? -1 : (System.nanoTime()-lastWorld)/1e6)+
                ",\"steady_game_fps\":"+steadyFps+",\"new_frame_arrival_p95_ms\":"+p95+
                ",\"new_frame_arrival_p50_ms\":"+percentile(arrivals,.5)+
                ",\"new_frame_arrival_p99_ms\":"+percentile(arrivals,.99)+
                ",\"new_frame_arrival_max_ms\":"+(sorted.length==0 ? 0 : sorted[sorted.length-1])+
                ",\"new_frame_arrival_over_50ms\":"+over(arrivals,50)+
                ",\"new_frame_arrival_over_100ms\":"+over(arrivals,100)+
                ",\"new_frame_arrival_intervals\":"+arrivals.size()+
                ",\"new_frame_arrival_mean_ms\":"+mean(arrivals)+
                ",\"steady_game_frames\":"+steadyFrames+",\"steady_window_seconds\":"+(steadyLast>steadyFirst ? (steadyLast-steadyFirst)/1e9 : 0)+
                ",\"steady_start_ns\":"+steadyFirst+",\"steady_end_ns\":"+steadyLast+
                ",\"exploration_soak_seconds\":"+explorationSoak.elapsedNanos()/1e9+
                ",\"exploration_soak_stationary\":"+stationarySoak+
                ",\"exploration_soak_images\":"+explorationSoak.frames()+
                ",\"exploration_soak_max_gap_ms\":"+explorationSoak.maximumGapNanos()/1e6+
                ",\"complete_ten_second_bins\":"+(steadyFirst!=0 ? Math.min(3,(steadyLast-steadyFirst)/10_000_000_000L) : 0)+
                ",\"steady_ten_second_frames\":"+java.util.Arrays.toString(tenSecondFrames)+
                ",\"native_produced_fps\":"+(producedFirst!=null&&producedLast!=null&&producedLast[0]>producedFirst[0]&&producedLast[1]>=producedFirst[1] ?
                    1000.0*(producedLast[1]-producedFirst[1])/(producedLast[0]-producedFirst[0]) : -1)+
                ",\"matched_pose_samples\":"+ages.length+",\"pose_age_p95_ms\":"+poseP95+",\"pose_age_max_ms\":"+poseMax+
                ",\"pose_age_p50_ms\":"+percentile(poseAges,.5)+",\"pose_age_mean_ms\":"+mean(poseAges)+
                ",\"frame_trace_written\":"+traceWritten+",\"frame_trace_outputs\":"+tracedOutputs+
                ",\"unmatched_source_samples\":"+unmatchedSourceSamples+
                ",\"metadata_verified_images\":"+((com.winlator.renderer.WinlatorStereoSource)source).snapshotIdentityCounts()[0]+
                ",\"metadata_predicted_images\":"+((com.winlator.renderer.WinlatorStereoSource)source).snapshotIdentityCounts()[1]+
                ",\"metadata_missing_packets\":"+((com.winlator.renderer.WinlatorStereoSource)source).snapshotIdentityCounts()[2]+
                ",\"first_capture_sparse\":"+firstCaptureSparse+
                ",\"stereo_captures\":"+captures+",\"black_samples\":"+blackSamples+"}");
        }
        FixtureReport.write(new File(activity.getFilesDir(),"offhead-game-result.json"),text.toString());
    }
    private static double percentile(java.util.ArrayList<Double> values,double fraction) {
        if(values.isEmpty()) return 0;
        Double[] sorted=values.toArray(new Double[0]);java.util.Arrays.sort(sorted);
        return sorted[(int)Math.ceil(sorted.length*fraction)-1];
    }
    private static double mean(java.util.ArrayList<Double> values) {
        double total=0;for(double value:values)total+=value;return values.isEmpty() ? 0 : total/values.size();
    }
    private static int over(java.util.ArrayList<Double> values,double threshold) {
        int count=0;for(double value:values)if(value>threshold)count++;return count;
    }
    private boolean measuredWorldReady() {return gameFlow.worldReady()&&(!restoreCycles||sceneCycle==3);}
    private boolean advanceRestoreCycle(int id,long sampled,long received)throws Exception {
        if(!restoreCycles||sceneCycle==3)return false;
        if(!gameFlow.worldReady()) {sceneCycleStarted=0;return false;}
        if(sceneCycleStarted==0) {
            sceneCycleStarted=received;
            if(travelVisibility!=null) {gameFlow.beginPreparedMotion(received);if(worldWatchdog)watchdog.resume();}
        }
        if(received-sceneCycleStarted<(travelVisibility!=null?6_200_000_000L:1_000_000_000L))return false;
        if(travelVisibility!=null) {travelVisibility.endScene(sceneCycle,gameFlow.travelState(received),received);if(worldWatchdog)watchdog.pause();}
        restoredImages.add(new long[]{sceneCycle,source.renderedSnapshot(),id&0xffffffffL,sampled,received});
        String destination=new String[]{"LBY","R25","RC1"}[sceneCycle++];
        Log.i("GK3HDXR","Source Restore request stage="+sceneCycle+" destination="+destination+" ns="+received);
        gameFlow.restoreScene(destination,received);sceneCycleStarted=0;return true;
    }
    private static StereoViews diagnosticOptics() {
        float[] fov={-1.5596154f/2,1.5596154f/2,1.5712752f/2,-1.5712752f/2};
        return new StereoViews(new float[]{-.06352f/2,0,0,0,0,0,1},fov,
            new float[]{.06352f/2,0,0,0,0,0,1},fov);
    }
    private void sampleIndependent()throws Exception {
        long sampled=System.nanoTime();InputSeed seed=readerSeed;
        if(seed==null||sampled<seed.time||sampled-seed.time>250_000_000L)return;
        // This is an explicitly simulated sensor: calculate a new pose at the
        // actual callback time rather than re-date the graphics thread's pose.
        double seconds=seed.seconds+(sampled-seed.time)/1e9;
        double yaw=seed.moving ? Math.sin(seconds*.8)*Math.PI/12 : 0;
        float[] head={0,0,0,0,(float)Math.sin(yaw/2),0,(float)Math.cos(yaw/2)};
        int id=firstFrameId+(++frame);poses.remember(id,sampled,15,sampled);
        long begin=System.nanoTime();
        source.publishTracking(head,15,.06352f,1.5596154f,1.5712752f,consumerHz,id,seed.input,diagnosticOptics());
        long end=System.nanoTime();
        long[] row=posePublications[posePublicationCount++%posePublications.length];
        row[0]=Integer.toUnsignedLong(id);row[1]=sampled;row[2]=begin;row[3]=end;
        readerSamples++;readerPose=new InputPose(id,head);
    }
    private void stopIndependent() {
        if(independentTracking!=null) {independentTracking.deactivate();independentTracking.checkFailure();}
        readerActive=false;readerSeed=null;readerPose=null;
    }
    private void writeFrameTrace() throws Exception {
        if(readerActive)throw new IllegalStateException("Retire reader before exporting timing evidence");
        if(outputTrace==null||traceWritten||outputTrace.pending()!=0)throw new IllegalStateException("Incomplete or duplicate frame trace");
        long[][] outputs=outputTrace.rows();
        if(outputs.length!=outputTrace.issued()||outputs.length!=frameEvents.size())throw new IllegalStateException("Missing output observer rows");
        org.json.JSONArray frames=new org.json.JSONArray(),completed=new org.json.JSONArray();
        for(long[] row:frameEvents)frames.put(new org.json.JSONArray(row));
        for(long[] row:outputs)completed.put(new org.json.JSONArray(row));
        String[] columns={"snapshot","pose","sampled_ns","received_ns","lease","offered_ns","take_begin_ns","take_end_ns",
            "capture_ns","identified_ns","metadata_ready_ns","copy_begin_ns","composition","epoch0","epoch1","epoch2","epoch3","early","window","pixmap","present_serial"};
        if(copiedFrameTrace)columns=new String[]{"snapshot","pose","sampled_ns","received_ns","capture_ns","identified_ns","metadata_ready_ns","copy_begin_ns"};
        org.json.JSONObject trace=new org.json.JSONObject();trace.put("schema",copiedFrameTrace ? 3 : 2);
        trace.put("transport",copiedFrameTrace ? "owned-copy" : "xpresent-lease");
        trace.put("scope",copiedFrameTrace ?
            "Owned immutable copies with pixel pose tags and local snapshot tokens; no XPresent lease or 64-bit composition provenance. GPU completion brackets are not physical motion-to-photon" :
            "Exact offscreen output copies; GPU completion brackets are not physical motion-to-photon");
        trace.put("token",activity.getIntent().getStringExtra("gk3hd_observation_token"));
        trace.put("independent_tracking",independentTracking!=null).put("reader_samples",readerSamples);
        trace.put("restore_cycles",restoreCycles).put("restore_requests",sceneCycle);
        trace.put("padded_eye_copies",paddedEyeCopies).put("other_eye_copies",frameEvents.size()-paddedEyeCopies);
        org.json.JSONArray restored=new org.json.JSONArray();for(long[] row:restoredImages)restored.put(new org.json.JSONArray(row));
        trace.put("restore_columns",new org.json.JSONArray(new String[]{"stage","snapshot","pose","sampled_ns","received_ns"}));
        trace.put("restore_observations",restored);
        trace.put("frame_columns",new org.json.JSONArray(columns));trace.put("frames",frames);
        trace.put("output_columns",new org.json.JSONArray(OutputFenceTrace.COLUMNS));trace.put("outputs",completed);
        if(posePublications!=null) {
            org.json.JSONArray publications=new org.json.JSONArray();
            for(int i=Math.max(0,posePublicationCount-posePublications.length);i<posePublicationCount;i++)
                publications.put(new org.json.JSONArray(posePublications[i%posePublications.length]));
            trace.put("pose_publication_columns",new org.json.JSONArray(
                new String[]{"pose","sampled_ns","send_begin_ns","send_end_ns"}));
            trace.put("pose_publications",publications);
        }
        if(metadataTrace!=null) {
            if(metadataTrace.pending()!=0||metadataTrace.issued()!=outputs.length||metadataTrace.completed()!=outputs.length)
                throw new IllegalStateException("Missing selected metadata completions");
            org.json.JSONArray metadata=new org.json.JSONArray();
            for(long[] row:metadataTrace.rows())metadata.put(new org.json.JSONArray(row));
            trace.put("metadata_columns",new org.json.JSONArray(MetadataCompletionTrace.COLUMNS));
            trace.put("metadata_completions",metadata);
            trace.put("repeated_selected_copies",metadataTrace.repeated());
        }
        FixtureReport.write(new File(activity.getFilesDir(),"offhead-frame-events.json"),trace.toString());
        tracedOutputs=outputs.length;traceWritten=true;outputTrace.close();outputTrace=null;
    }
    @Override public void pause() {paused=true;stopIndependent();source.focused(false);if(watchdog!=null) watchdog.pause();}
    @Override public void resume() {
        paused=false;
        if(watchdog!=null&&(!worldWatchdog||explorationSoak.frames()!=0&&!benchmarkFinished))watchdog.resume();
    }
    @Override public void destroy() {
        closing=true;
        if(independentTracking!=null)independentTracking.close();
        if(watchdog!=null)watchdog.close();
        java.util.concurrent.CountDownLatch retired=new java.util.concurrent.CountDownLatch(1);
        org.gk3hd.standalone.NativeSurfaceView view=((com.winlator.XServerDisplayActivity)activity).getXServerView();
        Runnable close=()-> {try {try {if(startupStrip!=null)startupStrip.close();}finally {source.close();}}
            catch(Exception failure){Log.e("GK3HDXR","Off-head source retirement failed",failure);}
            finally {retired.countDown();}};
        if(!view.queueRetirement(close))return;
        try {
            if(!retired.await(3,java.util.concurrent.TimeUnit.SECONDS))
                Log.e("GK3HDXR","Off-head source retirement not confirmed before graphics shutdown");
        } catch(InterruptedException failure){Thread.currentThread().interrupt();}
    }
}
