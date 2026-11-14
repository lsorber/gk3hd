package org.gk3hd.standalone;

import static org.gk3hd.standalone.NativeSessionReport.Output.NO_LAYER_SUBMITTED;
import static org.gk3hd.standalone.NativeSessionReport.Output.NO_SOURCE;
import static org.gk3hd.standalone.NativeSessionReport.Output.STEREO;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Report behavior without a headset, Android framework or synthetic rendering. */
public final class NativeSessionReportTests {
    private static int checks;
    private static void check(boolean value,String message) {checks++;if(!value)throw new AssertionError(message);}
    private static String read(File directory) throws Exception {
        return readFile(new File(directory,"xr-host-status.json"));
    }
    private static String readFile(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
    }
    private static void field(String json,String name,String value) {
        check(json.contains("\""+name+"\":"+value+"," )||json.contains("\""+name+"\":"+value+"}"),name+" differs: "+json);
    }
    private static void retainGraphicsStall(File directory) throws Exception {
        File file=new File(directory,"xr-last-graphics-stall.json");
        String game="fedcba0987654321fedcba0987654321";
        NativeSessionReport stalled=new NativeSessionReport(directory,"pimax",null,game);
        NativeDrawProgress progress=new NativeDrawProgress();
        progress.active(true);
        progress.begin(NativeDrawProgress.Phase.DRAW,1_000_000_000L);
        long observed=11_100_000_000L;
        stalled.write("created",false,null);
        String original=read(directory);
        field(original,"frame_session","\""+game+"\"");
        stalled.graphicsStalled(progress.inspect(observed),observed);
        String first=new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
        int start=original.indexOf("\"session_id\":");
        check(first.contains(original.substring(start,original.indexOf(',',start))),"Retain the stalled session ID");
        field(first,"observation_token","null");field(first,"adapter","\"pimax\"");
        field(first,"frame_session","\""+game+"\"");
        field(first,"phase","\"draw\"");field(first,"elapsed_ns","10100000000");
        field(first,"observed_monotonic_ns","11100000000");
        check(original.equals(read(directory)),"Watchdog must not change the render owner's report");
        stalled.write("paused",true,null);
        NativeSessionReport later=new NativeSessionReport(directory,"openxr","diagnostic","invalid session");
        later.write("created",false,null);
        field(read(directory),"frame_session","null");
        check(first.equals(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8)),
            "A restart must preserve the last stall");
        progress.begin(NativeDrawProgress.Phase.RESIZE,12_000_000_000L);
        later.graphicsStalled(progress.inspect(23_000_000_000L),23_000_000_000L);
        String second=new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
        field(second,"phase","\"resize\"");field(second,"adapter","\"openxr\"");
        field(second,"observation_token","\"diagnostic\"");field(second,"frame_session","null");
        check(!new File(directory,"xr-last-graphics-stall.json.tmp").exists(),"Stall report must replace its pending file");
    }
    private static void freshIntervals(File directory) throws Exception {
        long[] now={1_000_000_000L};
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null,()->now[0]);
        report.sampled(15,true,true);report.submitted(STEREO,1);
        now[0]+=5_000_000L;report.submitted(STEREO,1);
        now[0]+=5_000_000L;report.submitted(NO_SOURCE,0);
        now[0]+=3_100_000L;report.submitted(STEREO,2);
        now[0]+=20_000_000L;report.submitted(STEREO,3);
        report.write("submitting",false,null);
        String json=read(directory);
        field(json,"fresh_game_submit_intervals","2");
        field(json,"fresh_eligible_game_submissions","3");
        field(json,"fresh_game_submit_interval_mean_ms","16.55");
        field(json,"fresh_game_submit_interval_p50_upper_ms","13.25");
        field(json,"fresh_game_submit_interval_p95_upper_ms","20.25");

        report.sampled(0,true,true);now[0]+=1_000_000_000L;
        report.sampled(15,true,true);report.submitted(STEREO,4);
        report.write("paused",false,null);now[0]+=1_000_000_000L;
        report.sampled(15,true,true);report.submitted(STEREO,5);
        now[0]+=3_000_000L;report.submitted(STEREO,-1);
        now[0]+=1_000_000_000L;report.submitted(STEREO,6);
        now[0]+=3_000_000L;report.submitted(STEREO,0);
        now[0]+=1_000_000_000L;report.submitted(STEREO,7);
        report.write("submitting",false,null);
        field(read(directory),"fresh_game_submit_intervals","2");
        now[0]+=300_000_000L;report.submitted(STEREO,8);
        report.write("closed",true,null);
        field(read(directory),"fresh_game_submit_intervals","3");
        field(read(directory),"fresh_game_submit_interval_p50_upper_ms","20.25");
        field(read(directory),"fresh_game_submit_interval_p95_upper_ms","null");
    }

    private static void crystalEyeCopies(File directory) throws Exception {
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null);
        report.sampled(15,true,true);
        report.gameEyeCopy(false);
        report.gameEyeCopy(true);
        report.gameEyeCopy(true);
        report.sampled(15,false,true);
        report.gameEyeCopy(false);
        report.sampled(15,true,false);
        report.gameEyeCopy(true);
        report.write("closed",true,null);
        String json=read(directory);
        field(json,"crystal_game_shader_copies","1");
        field(json,"crystal_game_padded_blits","2");
    }

    private static void gameRepeatRuns(File directory) throws Exception {
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null);
        report.sampled(15,true,true);
        for(long snapshot:new long[]{1,1,2,2,2,3,3,3,3,-1,-1,-1})report.submitted(STEREO,snapshot);
        report.write("submitting",false,null);
        String clustered=read(directory);
        field(clustered,"eligible_game_submissions","9");
        field(clustered,"fresh_eligible_game_submissions","3");
        field(clustered,"repeated_eligible_submissions","8");
        field(clustered,"repeated_eligible_game_submissions","6");
        field(clustered,"longest_eligible_game_repeat_run","3");
        field(clustered,"eligible_game_repeat_runs_of_two_or_more","2");

        report.submitted(STEREO,4);report.submitted(STEREO,4);
        report.write("paused",false,null);
        report.sampled(15,true,true);
        report.submitted(STEREO,4);report.submitted(STEREO,4);
        report.sampled(1,false,false);
        report.submitted(STEREO,4);
        report.sampled(15,true,true);
        report.submitted(STEREO,4);report.submitted(STEREO,4);
        report.submitted(NO_SOURCE,0);
        report.submitted(STEREO,4);report.submitted(STEREO,4);
        report.write("closed",true,null);
        String separated=read(directory);
        field(separated,"eligible_game_submissions","17");
        field(separated,"fresh_eligible_game_submissions","4");
        field(separated,"repeated_eligible_game_submissions","10");
        field(separated,"longest_eligible_game_repeat_run","3");
        field(separated,"eligible_game_repeat_runs_of_two_or_more","2");
    }

    private static void alternatingStaleAndMissing(File directory) throws Exception {
        long[] now={1_000_000_000L};
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null,()->now[0]);
        report.sampled(15,true,true);
        report.submitted(STEREO,1);
        now[0]+=10_000_000L;
        check(!report.submitted(NO_SOURCE,0),"A brief game image outage is not a milestone");
        now[0]+=400_000_000L;
        check(!report.submitted(STEREO,1),"A stale image cannot end the game image outage");
        now[0]+=400_000_000L;
        check(!report.submitted(NO_LAYER_SUBMITTED,1),"The same outage is still below its threshold");
        now[0]+=400_000_000L;
        check(report.submitted(STEREO,1),"Alternating stale and empty submissions need a checkpoint");
        check(!report.submitted(STEREO,1),"A stalled game should checkpoint only once");
        report.write("submitting",false,null);
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","1010000000");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1200.0");
        now[0]+=10_000_000L;
        check(report.submitted(STEREO,2),"A fresh game image ends the outage");
        report.write("submitting",false,null);
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","0");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1210.0");

        now[0]+=10_000_000L;report.submitted(STEREO,2);
        now[0]+=800_000_000L;report.submitted(STEREO,-1);
        now[0]+=800_000_000L;report.submitted(NO_SOURCE,0);
        now[0]+=800_000_000L;report.submitted(STEREO,3);
        now[0]+=10_000_000L;report.submitted(STEREO,3);
        now[0]+=800_000_000L;report.sampled(15,false,true);
        now[0]+=3_000_000_000L;report.sampled(15,true,true);report.submitted(STEREO,4);
        now[0]+=10_000_000L;report.submitted(NO_SOURCE,0);
        now[0]+=800_000_000L;report.write("paused",false,null);
        now[0]+=3_000_000_000L;report.write("closed",true,null);
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","0");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1210.0");

        report.sampled(15,true,true);report.submitted(STEREO,5);
        now[0]+=10_000_000L;report.submitted(NO_SOURCE,0);
        now[0]+=800_000_000L;report.withoutSample();
        now[0]+=3_000_000_000L;report.withoutSample();
        report.write("closed",true,null);
        field(read(directory),"sampled_frames","4");
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","0");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1210.0");
    }

    private static void gameOutageAfterFocusReturns(File directory,boolean paused) throws Exception {
        long[] now={1_000_000_000L};
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null,()->now[0]);
        report.sampled(15,true,true);
        report.submitted(STEREO,1);
        now[0]+=10_000_000L;
        report.submitted(NO_SOURCE,0);
        now[0]+=20_000_000L;
        report.sampled(15,false,true);
        if(paused)report.write("paused",true,null);
        now[0]+=4_000_000_000L;
        report.sampled(15,true,true);
        check(!report.submitted(NO_SOURCE,0),"The focus gap must not trigger an outage checkpoint");
        now[0]+=400_000_000L;
        check(!report.submitted(STEREO,1),"The stale image is still within the new grace period");
        now[0]+=400_000_000L;
        check(!report.submitted(NO_LAYER_SUBMITTED,1),"No individual missed-output run exceeds the threshold");
        now[0]+=400_000_000L;
        check(report.submitted(STEREO,1),"Regained focus without fresh gameplay needs a checkpoint");
        report.write("submitting",false,null);
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","5030000000");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1200.0");
        now[0]+=10_000_000L;
        check(report.submitted(STEREO,2),"A fresh game image closes the outage after focus returns");
        now[0]+=10_000_000L;
        report.submitted(STEREO,3);
        report.write("submitting",false,null);
        field(read(directory),"eligible_no_fresh_game_start_monotonic_ns","0");
        field(read(directory),"longest_eligible_no_fresh_game_ms","1210.0");
        field(read(directory),"fresh_game_submit_intervals","1");
        field(read(directory),"fresh_game_submit_interval_mean_ms","10.0");
    }

    private static void retainGameOutage(File directory) throws Exception {
        File isolated=new File(directory,"game-outage");
        Files.createDirectories(isolated.toPath());
        File saved=new File(isolated,"xr-last-game-outage.json");
        long[] now={1_000_000_000L};
        String owner="0123456789abcdef0123456789abcdef";
        NativeSessionReport report=new NativeSessionReport(isolated,"pimax",null,owner,()->now[0]);
        report.sampled(15,true,true);report.submitted(STEREO,1);
        now[0]+=10_000_000L;
        report.submitted(NO_SOURCE,0);report.write("submitting",false,null);
        check(!saved.exists(),"A brief missing image must not create a retained outage");
        now[0]+=1_000_000_000L;
        check(report.submitted(NO_LAYER_SUBMITTED,0),"Sustained outage needs a checkpoint");
        report.write("submitting",false,null);
        String outage=readFile(saved);
        field(outage,"frame_session","\""+owner+"\"");
        field(outage,"eligible_no_fresh_game_start_monotonic_ns","1010000000");
        field(outage,"last_game_outage_start_monotonic_ns","1010000000");
        field(outage,"last_game_outage_end_monotonic_ns","null");
        field(outage,"last_game_outage_end_reason","null");
        field(outage,"longest_eligible_no_fresh_game_ms","1000.0");
        field(outage,"last_eligible_stereo_miss","\"no_layer_submitted\"");
        field(outage,"last_sample_focused","true");
        now[0]+=10_000_000L;
        check(report.submitted(STEREO,2),"A fresh image must checkpoint the recovered episode");
        report.write("submitting",false,null);
        String recovered=readFile(saved);
        field(recovered,"eligible_no_fresh_game_start_monotonic_ns","0");
        field(recovered,"last_game_outage_start_monotonic_ns","1010000000");
        field(recovered,"last_game_outage_end_monotonic_ns","2020000000");
        field(recovered,"last_game_outage_end_reason","\"fresh_game_image\"");
        report.write("closed",true,null);
        NativeSessionReport later=new NativeSessionReport(isolated,"pimax",null,null,()->now[0]);
        later.write("created",false,null);
        check(recovered.equals(readFile(saved)),"A relaunch must preserve the outcome of the prior outage");
        later.sampled(15,true,true);later.submitted(STEREO,1);
        now[0]+=10_000_000L;later.submitted(STEREO,1);
        now[0]+=1_000_000_000L;later.submitted(STEREO,1);
        later.write("submitting",false,null);
        field(readFile(saved),"frame_session","null");
        field(readFile(saved),"last_game_outage_end_reason","null");
        check(!new File(isolated,"xr-last-game-outage.json.tmp").exists(),"Retained report was not published atomically");
    }

    private static void retainNonRecoveryOutcomes(File directory) throws Exception {
        for(String outcome:new String[]{"runtime_ineligible","no_runtime_frame","source_changed","paused","closed","failed"}) {
            File isolated=new File(directory,outcome);
            Files.createDirectories(isolated.toPath());
            File saved=new File(isolated,NativeSessionReport.LAST_GAME_OUTAGE_FILE);
            long[] now={1_000_000_000L};
            NativeSessionReport report=new NativeSessionReport(isolated,"openxr",null,null,()->now[0]);
            report.sampled(15,true,true);report.submitted(STEREO,1);
            now[0]+=10_000_000L;report.submitted(NO_SOURCE,0);
            now[0]+=1_000_000_000L;report.submitted(NO_SOURCE,0);
            report.write("submitting",false,null);
            now[0]+=35_000_000L;
            switch(outcome) {
                case "runtime_ineligible":
                    check(report.sampled(15,false,true),"Focus loss ends a sustained episode immediately");
                    report.write("state_changed",false,null);break;
                case "no_runtime_frame":
                    check(report.withoutSample(),"A missing runtime frame ends the eligible episode");
                    check(!report.withoutSample(),"Repeated missing runtime frames do not rewrite the outcome");
                    report.write("state_changed",false,null);break;
                case "source_changed":
                    check(report.submitted(STEREO,-1),"A movie ends the episode without a fresh game image");
                    report.write("submitting",false,null);break;
                default:
                    report.write(outcome,outcome.equals("closed"),
                        outcome.equals("failed") ? new IllegalStateException("renderer failed") : null);
            }
            String ended=readFile(saved);
            field(ended,"last_game_outage_start_monotonic_ns","1010000000");
            field(ended,"last_game_outage_end_monotonic_ns","2045000000");
            field(ended,"last_game_outage_end_reason","\""+outcome+"\"");
            field(ended,"longest_eligible_no_fresh_game_ms","1035.0");
            if(outcome.equals("runtime_ineligible"))field(ended,"last_sample_focused","false");
            if(outcome.equals("failed"))field(ended,"failure","\"java.lang.IllegalStateException\"");
            report.write("closed",true,null);
            check(ended.equals(readFile(saved)),"Retirement must not overwrite a recorded outcome");
        }
    }
    private static void completeRecoveryOnFocusedGame(File directory) {
        NativeSessionReport report=new NativeSessionReport(directory,"pimax",null,null);
        int[] completions={0};
        report.onFirstFocusedGame(()->completions[0]++);
        report.sampled(15,false,true);
        report.submitted(STEREO,71);
        report.sampled(1,true,true);
        report.submitted(STEREO,72);
        report.sampled(15,true,true);
        report.submitted(STEREO,72);
        report.submitted(NO_LAYER_SUBMITTED,73);
        report.submitted(STEREO,-1);
        report.submitted(STEREO,0);
        check(completions[0]==0,"Unfocused, stale, missing or movie output cannot complete recovery");
        report.submitted(STEREO,74);
        report.submitted(STEREO,75);
        check(completions[0]==1,"The first fresh focused game output completes recovery once");
    }

    private static void retainStartupWithoutImage(File directory) throws Exception {
        File isolated=new File(directory,"startup-without-image");
        Files.createDirectories(isolated.toPath());
        File saved=new File(isolated,NativeSessionReport.LAST_STARTUP_FILE);
        NativeSessionReport failed=new NativeSessionReport(isolated,"openxr",null,null);
        failed.write("created",false,null);
        check(!saved.exists(),"An ongoing launch must not replace the previous attempt");
        failed.write("runtime_exit",false,null);
        String exit=readFile(saved);
        field(exit,"startup_outcome","\"runtime_exit\"");
        field(exit,"stereo_submissions","0");
        failed.write("closed",true,null);
        check(exit.equals(readFile(saved)),"Cleanup must preserve the initial exit reason");
        NativeSessionReport recovered=new NativeSessionReport(isolated,"openxr",null,null);
        recovered.write("created",false,null);
        recovered.sampled(15,true,true);
        recovered.submitted(STEREO,1);
        recovered.write("closed",true,null);
        check(exit.equals(readFile(saved)),"A successful retry must preserve the failed launch");
        NativeSessionReport lost=new NativeSessionReport(isolated,"openxr",null,null);
        lost.write("failed",true,new IllegalStateException("session lost"));
        field(readFile(saved),"startup_outcome","\"failed\"");
        field(readFile(saved),"failure","\"java.lang.IllegalStateException\"");
    }

    public static void main(String[] args) throws Exception {
        File directory=new File(args[0]);Files.createDirectories(directory.toPath());
        retainGraphicsStall(directory);
        freshIntervals(directory);
        crystalEyeCopies(directory);
        gameRepeatRuns(directory);
        alternatingStaleAndMissing(directory);
        gameOutageAfterFocusReturns(directory,false);
        gameOutageAfterFocusReturns(directory,true);
        retainGameOutage(directory);
        retainNonRecoveryOutcomes(directory);
        retainStartupWithoutImage(directory);
        completeRecoveryOnFocusedGame(directory);
        NativeSessionReport report=new NativeSessionReport(directory,"openxr","quote\"\\\n\t\u0000",null);
        report.write("created",false,null);
        String initial=read(directory);
        field(initial,"configured_eye_width_px","null");field(initial,"configured_eye_height_px","null");
        field(initial,"resolution_source","null");
        report.configured(1680,1760);report.write("configured",false,null);
        String configured=read(directory);
        field(configured,"configured_eye_width_px","1680");field(configured,"configured_eye_height_px","1760");
        field(configured,"resolution_source","\"runtime_recommended\"");
        NativeSessionReport fixture=new NativeSessionReport(directory,"pimax",null,null);
        fixture.configured(2688,2752,NativeSessionReport.ResolutionSource.FIXTURE_OVERRIDE);
        fixture.write("configured",false,null);
        String override=read(directory);
        field(override,"resolution_source","\"fixture_override\"");
        field(override,"configured_eye_width_px","2688");field(override,"configured_eye_height_px","2752");
        fixture.configured(2816,2880,NativeSessionReport.ResolutionSource.LAUNCH_OVERRIDE);
        fixture.write("configured",false,null);
        String launch=read(directory);
        field(launch,"resolution_source","\"launch_override\"");
        field(launch,"configured_eye_width_px","2816");field(launch,"configured_eye_height_px","2880");
        field(configured,"api_submissions","0");field(configured,"stereo_submissions","0");
        for(int[] invalid:new int[][]{{0,1760},{1680,0},{-1,1760},{Integer.MAX_VALUE,1760}}) {
            try {report.configured(invalid[0],invalid[1]);throw new AssertionError("Invalid dimensions accepted");}
            catch(IllegalArgumentException expected) {checks++;}
        }
        report.write("configured",false,null);
        field(read(directory),"configured_eye_width_px","1680");
        field(read(directory),"configured_eye_height_px","1760");
        field(initial,"api_submissions","0");field(initial,"output_completion_waits","null");
        field(initial,"last_pose_flags","null");field(initial,"last_sample_focused","null");
        field(initial,"last_eligible_stereo_miss","null");
        field(initial,"host_pose_to_submit_samples","0");
        field(initial,"host_pose_to_submit_mean_ms","null");
        field(initial,"host_pose_to_submit_p95_upper_ms","null");
        field(initial,"fresh_game_submit_intervals","0");
        field(initial,"fresh_game_submit_interval_p50_upper_ms","null");
        field(initial,"fresh_game_submit_interval_p95_upper_ms","null");
        check(initial.contains("quote\\\"\\\\\\u000a\\u0009\\u0000"),"Tokens must remain valid JSON strings");
        check(!new File(directory,"xr-host-status.json.tmp").exists(),"A complete report replaces its pending file");
        report.sampled(0,false,false);
        report.sampled(1,false,true);
        report.sampled(3,true,true);
        report.sampled(15,true,true);
        check(report.submitted(NO_SOURCE,0),"First empty API submission is observable");
        check(!report.submitted(NO_SOURCE,901),"Unmatched source pixels are not counted");
        check(report.submitted(STEREO,Long.MIN_VALUE+1),"First movie submission is observable");
        check(!report.submitted(STEREO,Long.MIN_VALUE+1),"Reusing a movie snapshot is no new milestone");
        check(report.submitted(STEREO,901),"First game submission is separate from movie output");
        check(!report.submitted(STEREO,901),"A repeated game image is not a fresh game image");
        report.submitted(STEREO,902);report.submitted(STEREO,0);
        report.write("paused",true,new IllegalStateException("private details are omitted"));
        String paused=read(directory);
        field(paused,"configured_eye_width_px","1680");field(paused,"configured_eye_height_px","1760");
        field(paused,"sampled_frames","4");field(paused,"orientation_valid_frames","3");
        field(paused,"position_valid_frames","2");field(paused,"orientation_tracked_frames","1");
        field(paused,"position_tracked_frames","1");field(paused,"focused_frames","2");
        field(paused,"renderable_frames","3");field(paused,"api_submissions","8");
        field(paused,"stereo_submissions","6");field(paused,"game_submissions","3");
        field(paused,"movie_submissions","2");field(paused,"unknown_source_submissions","1");
        field(paused,"source_image_changes","3");field(paused,"game_image_changes","2");
        field(paused,"session_end_completed","true");
        check(!paused.contains("private details"),"Do not export arbitrary exception data");
        report.write("closed",true,null);
        field(read(directory),"failure","\"java.lang.IllegalStateException\"");
        Files.copy(new File(directory,"xr-host-status.json").toPath(),new File(directory,"completed-openxr.json").toPath());

        NativeSessionReport next=new NativeSessionReport(directory,"pimax",null,null);
        next.write("created",false,null);
        String fresh=read(directory);
        field(fresh,"api_submissions","0");field(fresh,"failure","null");
        field(fresh,"observation_token","null");
        int start=initial.indexOf("\"session_id\":");
        check(!initial.substring(start,initial.indexOf(',',start)).equals(
            fresh.substring(start,fresh.indexOf(',',start))),"A later launch cannot inherit an old session identity");
        next.completion(true);next.submitted(STEREO,5);
        next.completion(false);next.submitted(STEREO,5);
        next.write("closed",true,null);
        field(read(directory),"output_completion_waits","1");field(read(directory),"output_completion_reuses","1");
        field(read(directory),"game_image_changes","1");
        long submitTime=2_000_000_000L;
        NativeSessionReport latency=new NativeSessionReport(directory,"pimax",null,null,()->submitTime);
        latency.sampled(15,false,true);
        latency.submitted(STEREO,1,submitTime-30_000_000L);
        latency.sampled(15,true,true);
        latency.submitted(STEREO,-1,submitTime-30_000_000L);
        latency.submitted(NO_LAYER_SUBMITTED,2,submitTime-30_000_000L);
        latency.submitted(STEREO,2,submitTime-10_000_000L);
        latency.submitted(STEREO,2,submitTime-60_000_000L);
        latency.submitted(STEREO,3,submitTime+1L);
        latency.submitted(STEREO,4,submitTime-20_000_000L);
        latency.write("submitting",false,null);
        field(read(directory),"host_pose_to_submit_samples","2");
        field(read(directory),"host_pose_to_submit_mean_ms","15.0");
        field(read(directory),"host_pose_to_submit_p95_upper_ms","21");
        latency.submitted(STEREO,5,submitTime-300_000_000L);
        latency.write("closed",true,null);
        field(read(directory),"host_pose_to_submit_samples","3");
        field(read(directory),"host_pose_to_submit_mean_ms","110.0");
        field(read(directory),"host_pose_to_submit_p95_upper_ms","null");
        long[] now={1_000_000_000L};
        NativeSessionReport gaps=new NativeSessionReport(directory,"openxr",null,null,()->now[0]);
        gaps.sampled(15,true,true);gaps.submitted(STEREO,11);
        now[0]+=10_000_000L;gaps.submitted(NO_SOURCE,0);
        now[0]+=1_100_000_000L;
        check(gaps.submitted(NO_SOURCE,0),"A sustained tracked/focused stereo outage needs one checkpoint");
        check(!gaps.submitted(NO_SOURCE,0),"An ongoing outage must not write on every frame");
        gaps.write("submitting",false,null);
        field(read(directory),"unmatched_eligible_submissions","3");
        field(read(directory),"longest_eligible_gap_ms","1100.0");
        field(read(directory),"last_stereo_monotonic_ns","1000000000");
        now[0]+=10_000_000L;
        check(gaps.submitted(STEREO,12),"Stereo recovery needs a checkpoint");
        gaps.write("submitting",false,null);
        field(read(directory),"eligible_gap_start_monotonic_ns","0");
        field(read(directory),"last_source_change_monotonic_ns",Long.toString(now[0]));
        gaps.sampled(0,false,false);now[0]+=2_000_000_000L;
        gaps.submitted(NO_SOURCE,0);gaps.write("paused",true,null);
        field(read(directory),"unmatched_eligible_submissions","3");
        field(read(directory),"longest_eligible_gap_ms","1110.0");
        gaps.sampled(15,true,true);now[0]+=10_000_000L;gaps.submitted(NO_SOURCE,0);
        now[0]+=2_000_000_000L;gaps.write("paused",true,null);
        now[0]+=60_000_000_000L;gaps.write("closed",true,null);
        field(read(directory),"longest_eligible_gap_ms","2000.0");
        field(read(directory),"eligible_gap_start_monotonic_ns","0");
        long[] stateTime={10_000_000_000L};
        NativeSessionReport state=new NativeSessionReport(directory,"pimax",null,null,()->stateTime[0]);
        check(!state.sampled(15,true,true),"A new sample must settle before a state-only checkpoint");
        state.write("submitting",false,null);
        stateTime[0]+=10_000_000L;
        check(!state.sampled(0,true,true),"Tracking loss must not write on its first frame");
        stateTime[0]+=200_000_000L;
        check(!state.sampled(0,true,true),"State-only reports must respect the one-second rate limit");
        stateTime[0]+=800_000_000L;
        check(state.sampled(0,true,true),"Stable tracking loss must report without another submission");
        state.write("state_changed",false,null);
        field(read(directory),"last_pose_flags","0");field(read(directory),"last_sample_focused","true");
        field(read(directory),"api_submissions","0");
        stateTime[0]+=2_000_000_000L;
        check(!state.sampled(0,true,true),"Unchanged tracking loss must not produce periodic reports");
        check(!state.sampled(15,true,true),"Recovery must settle too");
        stateTime[0]+=100_000_000L;
        check(state.sampled(15,true,true),"Tracking recovery needs a state checkpoint");
        state.write("state_changed",false,null);
        field(read(directory),"last_pose_flags","15");
        stateTime[0]+=1_000_000_000L;
        check(!state.sampled(15,false,false),"Focus/render loss starts another settling interval");
        stateTime[0]+=100_000_000L;
        check(state.sampled(15,false,false),"No-render state must report without source images");
        state.write("state_changed",false,null);
        field(read(directory),"last_sample_focused","false");field(read(directory),"last_sample_renderable","false");
        for(int i=0;i<120;i++) {
            stateTime[0]+=8_333_333L;
            check(!state.sampled(i%2==0?7:15,true,true),"Unsettled tracking chatter must not write each frame");
        }
        File blocked=new File(directory,"blocked-write");
        File obstruction=new File(blocked,"xr-host-status.json");
        Files.createDirectories(obstruction.toPath());
        File marker=new File(obstruction,"owned-test-marker");Files.write(marker.toPath(),new byte[]{1});
        NativeSessionReport retry=new NativeSessionReport(blocked,"openxr",null,null,()->stateTime[0]);
        retry.sampled(0,false,false);stateTime[0]+=100_000_000L;
        check(retry.sampled(0,false,false),"Settled state needs its initial report");
        try {retry.write("state_changed",false,null);throw new AssertionError("Expected obstructed output to fail");}
        catch(java.io.IOException expected) {
            check(retry.sampled(0,false,false),"A failed report must not acknowledge the pending state");
        }
        Files.delete(marker.toPath());Files.delete(obstruction.toPath());
        retry.write("state_changed",false,null);
        check(!retry.sampled(0,false,false),"A successful retry must acknowledge the state");
        NativeSessionReport eligibility=new NativeSessionReport(directory,"openxr",null,null,()->stateTime[0]);
        eligibility.sampled(15,true,true);eligibility.submitted(STEREO,50);
        stateTime[0]+=10_000_000L;eligibility.submitted(NO_SOURCE,0);
        stateTime[0]+=300_000_000L;eligibility.sampled(0,false,false);
        stateTime[0]+=60_000_000_000L;
        eligibility.write("state_changed",false,null);
        field(read(directory),"longest_eligible_gap_ms","300.0");
        field(read(directory),"eligible_gap_start_monotonic_ns","0");
        field(read(directory),"unmatched_eligible_submissions","1");
        eligibility.sampled(15,true,true);eligibility.submitted(STEREO,51);
        eligibility.write("submitting",false,null);
        field(read(directory),"longest_eligible_gap_ms","300.0");

        NativeSessionReport stages=new NativeSessionReport(directory,"openxr",null,null,()->stateTime[0]);
        stages.sampled(15,false,true);
        stages.submitted(NO_SOURCE,0);
        stages.sampled(15,true,true);
        stages.submitted(NativeSessionReport.Output.missing(false,null),0);
        stages.submitted(NativeSessionReport.Output.missing(true,null),0);
        stages.submitted(NativeSessionReport.Output.missing(true,91),0);
        stages.submitted(NO_LAYER_SUBMITTED,92);
        long lastMiss=stateTime[0];
        stateTime[0]+=10_000_000L;
        stages.submitted(STEREO,93);
        stages.write("submitting",false,null);
        String boundary=read(directory);
        field(boundary,"unmatched_eligible_submissions","4");
        field(boundary,"eligible_without_stereo_source","1");
        field(boundary,"eligible_without_source_frame_id","1");
        field(boundary,"eligible_without_matching_pose","1");
        field(boundary,"eligible_without_layer_after_pose_match","1");
        field(boundary,"last_eligible_stereo_miss","\"no_layer_submitted\"");
        field(boundary,"last_eligible_stereo_miss_monotonic_ns",Long.toString(lastMiss));
        field(boundary,"stereo_submissions","1");
        field(boundary,"game_image_changes","1");

        long[] heldTime={20_000_000_000L};
        NativeSessionReport held=new NativeSessionReport(directory,"openxr",null,null,()->heldTime[0]);
        held.sampled(15,true,true);
        held.submitted(STEREO,71);
        heldTime[0]+=10_000_000L;
        check(!held.submitted(STEREO,71),"A brief image repeat needs no checkpoint");
        heldTime[0]+=1_000_000_000L;
        check(held.submitted(STEREO,71),"A sustained held image needs a checkpoint");
        check(!held.submitted(STEREO,71),"A held image must not write on every frame");
        held.write("submitting",false,null);
        String frozen=read(directory);
        field(frozen,"repeated_eligible_submissions","3");
        field(frozen,"source_image_changes","1");
        field(frozen,"unmatched_eligible_submissions","0");
        field(frozen,"longest_eligible_gap_ms","0.0");
        field(frozen,"held_image_start_monotonic_ns","20010000000");
        field(frozen,"longest_held_image_ms","1000.0");
        heldTime[0]+=10_000_000L;
        check(held.submitted(STEREO,72),"A fresh image after a sustained hold needs a checkpoint");
        held.write("submitting",false,null);
        field(read(directory),"held_image_start_monotonic_ns","0");
        field(read(directory),"longest_held_image_ms","1010.0");
        field(read(directory),"source_image_changes","2");

        held.submitted(STEREO,72);
        heldTime[0]+=200_000_000L;
        held.sampled(1,false,false);
        heldTime[0]+=10_000_000_000L;
        held.sampled(15,true,true);
        check(!held.submitted(STEREO,72),"A new eligible interval does not inherit the previous hold");
        held.submitted(STEREO,0);
        heldTime[0]+=2_000_000_000L;
        check(!held.submitted(STEREO,0),"Unknown identities cannot prove an image is held");
        held.write("submitting",false,null);
        field(read(directory),"held_image_start_monotonic_ns","0");
        field(read(directory),"longest_held_image_ms","1010.0");
        field(read(directory),"repeated_eligible_submissions","4");
        System.out.println("Native session report checks: "+checks);
    }
}
