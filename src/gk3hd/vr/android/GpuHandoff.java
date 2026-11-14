package org.gk3hd.standalone;

import android.opengl.GLES30;

/** Shared-context GPU ordering. Caller owns the drawable lock on both threads. */
public final class GpuHandoff {
    private boolean enabled;
    private long fence;
    public boolean beginRead() {
        return beginRead(false);
    }
    public boolean beginRead(boolean locallyOrdered) {
        // A GPU publication preceding this handshake is not safely ordered.
        // A CPU upload made by the caller in this reading context can start
        // immediately, but must wait for any preceding GPU backing-mode use.
        if(!enabled) {enabled=true;if(!locallyOrdered) return false;}
        if(fence==0&&!locallyOrdered) return false;
        waitForAccess();return true;
    }
    public void beforeWrite() {if(enabled) waitForAccess();}
    public void afterWrite() {if(enabled) publish();}
    public void afterRead() {publish();}
    private void waitForAccess() {
        if(fence==0) return;
        // Server wait: orders the next GPU access without waiting on this CPU.
        GLES30.glWaitSync(fence,0,GLES30.GL_TIMEOUT_IGNORED);
        GLES30.glDeleteSync(fence);fence=0;
    }
    private void publish() {
        if(fence!=0) throw new IllegalStateException("Unconsumed GPU handoff");
        fence=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);
        if(fence==0) throw new IllegalStateException("GPU handoff fence unavailable");
        GLES30.glFlush();
    }
    /** Complete current-context writes before handing a texture to an external consumer. */
    static void awaitOutput() {
        long output=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);
        if(output==0)throw new IllegalStateException("Stereo output fence unavailable");
        try {
            requireOutputReady(GLES30.glClientWaitSync(output,GLES30.GL_SYNC_FLUSH_COMMANDS_BIT,
                RendererRecovery.STEREO_TIMEOUT_NS));
        } finally {GLES30.glDeleteSync(output);}
    }
    static void requireOutputReady(int status) {
        if(status==GLES30.GL_TIMEOUT_EXPIRED)throw new RendererRecovery.StereoTimeout("Stereo output");
        if(status!=GLES30.GL_ALREADY_SIGNALED&&status!=GLES30.GL_CONDITION_SATISFIED)
            throw new IllegalStateException("Stereo output completion failed");
    }
    public void close() {if(fence!=0) GLES30.glDeleteSync(fence);fence=0;enabled=false;}
}
