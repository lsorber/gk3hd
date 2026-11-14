package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.EGL14;
import android.opengl.EGLContext;
import android.opengl.GLES30;
import android.util.Log;
import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import org.json.JSONObject;

/** Debug-only, nonblocking transfer timing. No vendor API or extra native library. */
public final class GlTransferProfile implements AutoCloseable {
    public static final int SNAPSHOT_COPY=1,EYE_COPY=2,METADATA_READBACK=3,SYNC_EYE_COPY=4;
    private static final int TIME_ELAPSED=0x88bf,COUNTER_BITS=0x8864,CURRENT_QUERY=0x8865,DISJOINT=0x8fbb;
    private static final int MAX_ROWS=512;
    private final BufferedWriter output;
    private final GlDriver driver=new GlDriver();
    private final GpuScopeTimers timers;
    private final long created=System.nanoTime(),delay;
    private int rows;
    private boolean closed,failed;
    private static final class GlDriver implements GpuScopeTimers.Driver {
        final Thread owner=Thread.currentThread();
        final EGLContext context=EGL14.eglGetCurrentContext();
        final int[] value=new int[1];
        boolean abandoned;
        public boolean current() {
            return !abandoned&&Thread.currentThread()==owner&&!context.equals(EGL14.EGL_NO_CONTEXT)&&context.equals(EGL14.eglGetCurrentContext());
        }
        public int counterBits() {
            String extensions=GLES30.glGetString(GLES30.GL_EXTENSIONS);
            if(extensions==null||!(" "+extensions+" ").contains(" GL_EXT_disjoint_timer_query ")) return 0;
            GLES30.glGetQueryiv(TIME_ELAPSED,COUNTER_BITS,value,0);return value[0];
        }
        public boolean canBegin() {GLES30.glGetQueryiv(TIME_ELAPSED,CURRENT_QUERY,value,0);return value[0]==0;}
        public int create() {GLES30.glGenQueries(1,value,0);return value[0];}
        public void begin(int query) {GLES30.glBeginQuery(TIME_ELAPSED,query);}
        public void end() {GLES30.glEndQuery(TIME_ELAPSED);}
        public boolean disjoint() {GLES30.glGetIntegerv(DISJOINT,value,0);return value[0]!=0;}
        public boolean available(int query) {GLES30.glGetQueryObjectuiv(query,GLES30.GL_QUERY_RESULT_AVAILABLE,value,0);return value[0]!=0;}
        public long result(int query) {
            GLES30.glGetQueryObjectuiv(query,GLES30.GL_QUERY_RESULT,value,0);
            return value[0]&0xffffffffL;
        }
        public void delete(int query) {value[0]=query;GLES30.glDeleteQueries(1,value,0);}
    }
    public static GlTransferProfile create(Activity activity,int generation) {
        if(!activity.getIntent().getBooleanExtra("gk3hd_profile_gl_transfers",false)||generation<1||generation>4) return null;
        String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
        int delay=activity.getIntent().getIntExtra("gk3hd_gl_profile_delay_ms",5000);
        if(token==null||!token.matches("[a-f0-9]{32}")||delay<0||delay>30000) {
            Log.w("GK3HDXR","GL transfer profiling disabled: invalid diagnostic identity/budget");return null;
        }
        java.nio.file.Path path=new java.io.File(activity.getFilesDir(),"gl-transfer-"+token+"-"+generation+".jsonl").toPath();
        try {
            BufferedWriter writer=new BufferedWriter(new OutputStreamWriter(Files.newOutputStream(path,
                StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),StandardCharsets.UTF_8));
            try {return new GlTransferProfile(writer,delay);}
            catch(java.io.IOException error) {try {writer.close();} catch(java.io.IOException ignored) {}throw error;}
        } catch(java.io.IOException error) {
            Log.w("GK3HDXR","GL transfer profiling disabled; existing evidence is preserved",error);return null;
        }
    }
    private GlTransferProfile(BufferedWriter output,int delay) throws java.io.IOException {
        this.output=output;this.delay=delay*1_000_000L;
        timers=new GpuScopeTimers(driver,System::nanoTime,this::sample,8,8,MAX_ROWS,20_000_000_000L);
        output.write("{\"kind\":\"config\",\"supported\":"+timers.supported()+",\"created_ns\":"+created+
            ",\"sample_every\":8,\"max_rows\":512,\"max_latency_ns\":"+GpuScopeTimers.MAX_LATENCY_NANOS+
            ",\"renderer\":"+JSONObject.quote(GLES30.glGetString(GLES30.GL_RENDERER))+"}\n");output.flush();
    }
    public int begin(int stage,long identity) {
        if(closed||failed||rows>=MAX_ROWS||System.nanoTime()-created<delay) return 0;
        return timers.begin(stage,identity);
    }
    public void end(int ticket) {if(ticket!=0&&!closed) timers.end(ticket);}
    /** Call outside producer locks; unavailable queries never trigger a read. */
    public void poll() {if(!closed) {if(failed) close();else timers.poll();}}
    private static String stage(int stage) {
        switch(stage) {
            case SNAPSHOT_COPY:return "snapshot_copy";
            case EYE_COPY:return "eye_copy";
            case METADATA_READBACK:return "metadata_readback";
            case SYNC_EYE_COPY:return "sync_eye_copy";
            default:return "unknown";
        }
    }
    private void sample(int stage,long identity,long begin,long recorded,long collected,long gpuNanos,String rejected) {
        if(failed||rows>=MAX_ROWS) return;
        try {
            output.write("{\"kind\":\"sample\",\"stage\":\""+stage(stage)+"\",\"identity\":"+identity+
                ",\"begin_ns\":"+begin+",\"recorded_ns\":"+recorded+",\"collected_ns\":"+collected+
                ",\"gpu_ns\":"+gpuNanos+",\"rejected\":"+(rejected==null ? "null" : JSONObject.quote(rejected))+"}\n");
            ++rows;
            // Keep the completed tail available to the host before a device
            // restart. Result collection still never waits for a GPU query.
            output.flush();
        } catch(java.io.IOException error) {failed=true;Log.w("GK3HDXR","GL timing report stopped",error);}
    }
    /** Explicitly invalidates a destroyed context even if its handle is reused. */
    public void abandonContext() {driver.abandoned=true;close();}
    @Override public void close() {
        if(closed) return;
        timers.close();closed=true;
        try {output.close();} catch(java.io.IOException error) {Log.w("GK3HDXR","GL timing report close failed",error);}
    }
}
