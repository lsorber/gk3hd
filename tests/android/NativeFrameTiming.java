package org.gk3hd.standalone;

import android.app.Activity;
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded real-compositor observation, exported after XR has ended. */
public class NativeFrameTiming implements XrPresenter.FrameObserver {
    private final Activity activity;
    private final boolean openXr;
    private final String token;
    private final int frameLimit;
    private final ArrayList<long[]> rows=new ArrayList<>();
    private final FramePoses<Long> samples=new FramePoses<>();
    private final ArrayList<long[]> nativeRows=new ArrayList<>();
    private final ArrayList<long[]> crystalRows=new ArrayList<>();
    private final ArrayList<long[]> inputRows=new ArrayList<>();
    private final java.util.HashMap<Integer,long[]> inputIds=new java.util.HashMap<>();
    private int inputOmitted;
    private final java.util.HashMap<Integer,String[]> inputContexts=new java.util.HashMap<>();
    private int omitted,nativeOmitted,checkpoints;
    private boolean closed;
    public NativeFrameTiming(Activity activity) {this(activity,4096);}
    protected NativeFrameTiming(Activity activity,int frameLimit) {
        this.frameLimit=frameLimit;
        this.activity=activity;openXr="openxr".equals(activity.getIntent().getStringExtra("gk3hd_xr_presenter"));
        token=activity.getIntent().getStringExtra("gk3hd_observation_token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh presenter observation token required");
    }
    @Override public synchronized void sampled(int id,long now,int flags) {
        if(closed)return;
        samples.remember(id,now,flags,now);
        if(inputRows.size()==8192) {inputOmitted++;return;}
        int tid=android.os.Process.myTid();
        if(!inputContexts.containsKey(tid)) {
            String root="/proc/self/task/"+tid+"/";
            String[] context={Thread.currentThread().getName(),"", ""};
            String[] paths={"stat","cgroup"};
            for(int i=0;i<paths.length;i++) {
                try {
                    byte[] data=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(root+paths[i]));
                    if(data.length>8192)throw new java.io.IOException("Oversized tracking context");
                    context[i+1]=new String(data,java.nio.charset.StandardCharsets.UTF_8);
                } catch(Exception error) {context[i+1]="unavailable: "+error;}
            }
            inputContexts.put(tid,context);
        }
        long[] row={id&0xffffffffL,now,flags,System.nanoTime(),0,tid};
        if(inputIds.put(id,row)!=null)throw new IllegalStateException("Repeated native sample identity");
        inputRows.add(row);
    }
    @Override public synchronized void published(int id,long now) {
        if(closed)return;
        long[] row=inputIds.get(id);
        if(row==null)return;
        if(row[4]!=0||now<row[1])throw new IllegalStateException("Invalid native input publication identity/time");
        row[4]=now;
    }
    @Override public synchronized void frame(XrPresenter.Source source,int tick,Integer id,long snapshot,long[] times,boolean waited) {
        if(closed)return;
        if(rows.size()==frameLimit){omitted++;return;}
        if(times.length!=9)throw new IllegalArgumentException("Unexpected presenter timeline");
        for(int i=1;i<times.length;i++)if(times[i]<times[i-1])throw new IllegalStateException("Presenter clock moved backwards");
        long[] row=new long[31];row[0]=tick;row[1]=id==null ? -1 : id&0xffffffffL;row[2]=snapshot;
        Long sampled=samples.matchImage(id,snapshot,times[8]);row[3]=sampled==null ? 0 : sampled;
        System.arraycopy(times,0,row,4,9);row[13]=waited ? 1 : 0;
        long[] events=id==null?null:source.snapshotFrameEvents(id);
        if(events!=null) {
            if(events.length!=17)throw new IllegalStateException("Unexpected exact-image timeline");
            System.arraycopy(events,0,row,14,17);
        }
        rows.add(row);
    }
    @Override public synchronized void crystalSubmission(int tick,long draw,long focusEpoch,int trackingFlags,
            boolean focused,int outputSlot,boolean reusedPreviousOutput) {
        if(closed||omitted!=0)return;
        if(openXr||rows.size()!=crystalRows.size()+1||rows.get(rows.size()-1)[0]!=tick||
                draw<=0||focusEpoch<0||outputSlot<0||outputSlot>=3)
            throw new IllegalArgumentException("Crystal submission must identify the current timing row");
        crystalRows.add(new long[]{tick,draw,focusEpoch,trackingFlags,focused?1:0,outputSlot,reusedPreviousOutput?1:0});
    }
    @Override public synchronized void nativeFrame(int tick,long serial,long epoch,long time,long period,
            int flags,boolean render,boolean focused,long acquireBegin,long acquireEnd,int inputPose) {
        if(closed)return;
        if(nativeRows.size()==frameLimit){nativeOmitted++;return;}
        if(serial<=0||epoch<=0||time<=0||period<=0||acquireBegin<0||acquireEnd<acquireBegin)
            throw new IllegalArgumentException("Invalid native frame observation");
        nativeRows.add(new long[]{tick,serial,epoch,time,period,flags,render?1:0,focused?1:0,acquireBegin,acquireEnd,inputPose&0xffffffffL});
    }
    @Override public synchronized void checkpoint() throws Exception {
        if(closed)return;
        export(false);
    }
    @Override public synchronized void close() throws Exception {
        if(closed)return;
        export(true);closed=true;
    }
    private void export(boolean complete) throws Exception {
        String[] columns={"tick","pose","snapshot","sampled_ns","sample_begin_ns","pose_ready_ns","tracking_end_ns",
            "service_end_ns","draw_begin_ns","draw_end_ns","finish_begin_ns","finish_end_ns","submit_end_ns","waited",
            "lease","offered_ns","take_begin_ns","take_end_ns","capture_ns","identified_ns","metadata_ready_ns",
            "copy_begin_ns","composition","epoch0","epoch1","epoch2","epoch3","early","window","pixmap","present_serial"};
        JSONObject data=new JSONObject();data.put("schema",3);
        data.put("scope","Host submission/source timeline. Native XR time is a separate clock domain; not physical scanout or motion-to-photon.");
        data.put("backend",openXr?"openxr":"pimax");
        data.put("completion",openXr?"OpenXR runtime ownership wait and release/submit, no explicit glFinish":"vendor explicit GPU completion wait");
        data.put("closed",complete).put("checkpoint",++checkpoints);
        data.put("token",token);
        data.put("columns",new JSONArray(columns));data.put("omitted",omitted);
        JSONArray frames=new JSONArray();for(long[] row:rows)frames.put(new JSONArray(row));data.put("frames",frames);
        data.put("native_columns",new JSONArray(new String[]{"tick","serial","space_epoch","xr_display_time","xr_period",
            "flags","should_render","focused","acquire_begin_ns","acquire_end_ns","input_pose"}));
        JSONArray nativeFrames=new JSONArray();for(long[] row:nativeRows)nativeFrames.put(new JSONArray(row));
        data.put("native_frames",nativeFrames).put("native_omitted",nativeOmitted);
        if(!openXr) {
            data.put("crystal_columns",new JSONArray(new String[]{"tick","draw","focus_epoch","tracking_flags",
                "focused","output_slot","reused_previous_output"}));
            JSONArray crystalFrames=new JSONArray();for(long[] row:crystalRows)crystalFrames.put(new JSONArray(row));
            data.put("crystal_submissions",crystalFrames);
        }
        data.put("input_columns",new JSONArray(new String[]{"pose","sampled_ns","flags","observed_ns","published_ns","caller_tid"}));
        JSONArray inputs=new JSONArray();for(long[] row:inputRows)inputs.put(new JSONArray(row));
        data.put("inputs",inputs).put("input_omitted",inputOmitted);
        JSONObject contexts=new JSONObject();
        for(java.util.Map.Entry<Integer,String[]> entry:inputContexts.entrySet())contexts.put(entry.getKey().toString(),new JSONArray(entry.getValue()));
        data.put("input_contexts",contexts);
        File destination=new File(activity.getFilesDir(),"native-presenter-timing.json");
        if(destination.exists()) {
            if(destination.length()>4*1024*1024)throw new java.io.IOException("Preserve oversized earlier presenter trace");
            JSONObject previous=new JSONObject(new String(java.nio.file.Files.readAllBytes(destination.toPath()),java.nio.charset.StandardCharsets.UTF_8));
            if(!token.equals(previous.optString("token")))throw new java.io.IOException("Preserve presenter trace owned by another observation");
        }
        File temporary=new File(activity.getFilesDir(),"presenter-timing-"+token+".tmp");
        if(!temporary.createNewFile())throw new java.io.IOException("Preserve unfinished presenter export");
        try(PrintWriter out=new PrintWriter(temporary)) {
            out.println(data.toString());if(out.checkError())throw new java.io.IOException("Presenter trace export failed");
        }
        java.nio.file.Files.move(temporary.toPath(),destination.toPath(),
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        android.util.Log.i("GK3HDXR","Real presenter trace exported rows="+rows.size()+" omitted="+omitted);
    }
}
