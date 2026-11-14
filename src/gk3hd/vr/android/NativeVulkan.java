package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.EGL14;
import android.opengl.GLES30;
import android.util.Log;
import com.winlator.core.EnvVars;
import com.winlator.core.GPUHelper;
import com.winlator.renderer.GPUImage;
import com.winlator.renderer.Texture;
import com.winlator.xconnector.UnixSocketConfig;
import com.winlator.xenvironment.XEnvironment;
import com.winlator.xenvironment.components.VortekRendererComponent;
import com.winlator.xserver.Drawable;
import com.winlator.xserver.Window;
import com.winlator.xserver.XServer;
import com.winlator.xserver.XLock;
import java.io.File;
import java.util.IdentityHashMap;

/** Android system Vulkan plus an ordered hardware-buffer/GLES publication.
 * Device-independent: the Pimax presenter and future OpenXR host share this.
 * Conservative synchronization is deliberate, not a high-performance claim. */
public final class NativeVulkan {
    private static final IdentityHashMap<XServer,NativeVulkan> sessions=new IdentityHashMap<>();
    private static final class Snapshot {
        final Window window;final Drawable drawable;final Texture texture;final long bytes;
        Snapshot(Window window,Drawable drawable,long bytes) {
            this.window=window;this.drawable=drawable;this.bytes=bytes;texture=new Texture(drawable);
        }
    }
    private final IdentityHashMap<Drawable,Snapshot> snapshots=new IdentityHashMap<>();
    private final java.util.ArrayList<Long> contexts=new java.util.ArrayList<>();
    private final ThreadLocal<Long> copyContext=new ThreadLocal<>(),publicationStart=new ThreadLocal<>();
    private final boolean stereoOnly,measure,profileRequests;
    private long snapshotBytes,measuredFrames,queueNanos,copyNanos;
    static boolean stereoOnlyWaits(android.content.Intent options) {
        // The managed XR source never samples the mono desktop. Keep full
        // ordering for explicit desktop captures and a debug-only A/B control.
        boolean selected=!options.getBooleanExtra("gk3hd_capture_guest",false);
        if(com.winlator.BuildConfig.DEBUG&&options.hasExtra("gk3hd_test_native_stereo_only"))
            selected=options.getBooleanExtra("gk3hd_test_native_stereo_only",false);
        return selected;
    }
    private NativeVulkan(Activity activity) {
        stereoOnly=stereoOnlyWaits(activity.getIntent());
        measure=com.winlator.BuildConfig.DEBUG;
        profileRequests=measure&&activity.getIntent().getBooleanExtra("gk3hd_test_native_requests",false);
    }
    public static void prepare(Activity activity,XEnvironment environment,XServer server,EnvVars vars) throws Exception {
        synchronized(sessions) {if(sessions.containsKey(server)) throw new IllegalStateException("Native Vulkan already prepared for this game");}
        if(environment.getComponent(VortekRendererComponent.class)!=null)
            throw new IllegalStateException("Managed native Vulkan must not be combined with another Vortek component");
        File root=environment.getRootFS().getRootDir();
        File manifest=NativeVulkanClient.prepare(activity,root);
        VortekRendererComponent.Options options=new VortekRendererComponent.Options();
        options.libvulkanPath=null; // Android's loader, not a replaced system driver.
        environment.addComponent(new VortekRendererComponent(server,
            UnixSocketConfig.create(root.getPath(),UnixSocketConfig.VORTEK_SERVER_PATH),options));
        vars.put("VK_ICD_FILENAMES",manifest.getCanonicalPath());
        vars.put("GK3HD_XR_DESCRIPTOR_BATCH","1");
        // Qualified for this ordered Android-driver transport. Turnip's default
        // retains shader composition; protected-source raw-copy experiments are
        // tracked separately, not enabled by this backend's configuration.
        vars.put("GK3HD_WXR_PROJECTION_COPY","1");
        synchronized(sessions) {sessions.put(server,new NativeVulkan(activity));}
        Log.i("GK3HDXR","Managed native Android Vulkan enabled; verified APK client; installed Turnip unchanged");
    }
    private static NativeVulkan session(XServer server) {synchronized(sessions) {return sessions.get(server);}}
    public static boolean active(XServer server) {return session(server)!=null;}
    public static boolean profileRequests(XServer server) {NativeVulkan owner=session(server);return owner!=null&&owner.profileRequests;}
    private static boolean stereo(Window window) {
        for(int depth=0;window!=null&&depth<16;depth++,window=window.getParent())
            if(window.getName().equals("GK3HD XR stereo")) return true;
        return false;
    }
    public static boolean requires(XServer server,int windowId) {
        NativeVulkan owner=session(server);if(owner==null) return false;
        boolean ordered=!owner.stereoOnly||stereo(server.windowManager.getWindow(windowId));
        if(owner.measure) owner.publicationStart.set(ordered?System.nanoTime():null);
        return ordered;
    }
    public static Texture texture(XServer server,Drawable drawable) {
        NativeVulkan owner=session(server);if(owner==null) return null;
        synchronized(owner.snapshots) {Snapshot value=owner.snapshots.get(drawable);return value==null ? null : value.texture;}
    }
    // Window identity and content are checked under the server's window lock.
    // Retire on this publisher's shared GL context, never the X event thread.
    private void retireStale(XServer server) {
        java.util.Iterator<Snapshot> iterator=snapshots.values().iterator();
        while(iterator.hasNext()) {
            Snapshot old=iterator.next();
            if(server.windowManager.getWindow(old.window.id)==old.window&&old.window.getContent()==old.drawable) continue;
            synchronized(old.drawable.renderLock) {old.texture.destroy();}
            snapshotBytes-=old.bytes;iterator.remove();
        }
    }
    /** Native RPC thread: its queue is idle before copying; it cannot enqueue
     * another Vulkan write until this GL copy completes. Reader fences still
     * protect the independent proxy from the device presenter's GL accesses. */
    public static boolean publish(XServer server,int windowId) {
        NativeVulkan owner=session(server);if(owner==null) return false;
        if(com.winlator.BuildConfig.DEBUG&&server.activity.getIntent().getBooleanExtra("gk3hd_test_transport_only",false)&&
           server.activity.getIntent().getBooleanExtra("gk3hd_test_fail_publication",false))
            throw new IllegalStateException("Injected native Vulkan publication failure");
        try(XLock windowLock=server.lock(XServer.Lockable.WINDOW_MANAGER,XServer.Lockable.DRAWABLE_MANAGER)) {
        Window window=server.windowManager.getWindow(windowId);
        if(window==null||!stereo(window)) return false;
        long start=System.nanoTime();Drawable drawable=window.getContent();
        synchronized(drawable.renderLock) {
            if(!(drawable.getTexture() instanceof GPUImage)) throw new IllegalStateException("Native Vulkan output is not hardware-buffer backed");
            if(owner.copyContext.get()==null) {
                synchronized(owner.contexts) {
                    if(owner.contexts.size()>=16) throw new IllegalStateException("Native Vulkan copy-context bound exceeded");
                    long context=GPUHelper.createOffscreenEGLContext(true);
                    if(context==0) throw new IllegalStateException("Cannot create native Vulkan publication context");
                    owner.contexts.add(context);owner.copyContext.set(context);
                }
            }
            Texture source=drawable.getTexture(),snapshot;source.updateFromDrawable();
            synchronized(owner.snapshots) {
                owner.retireStale(server);
                Snapshot cached=owner.snapshots.get(drawable);
                if(cached==null) {
                    long bytes=(long)drawable.width*drawable.height*4;
                    if(owner.snapshots.size()>=8||bytes<=0||owner.snapshotBytes+bytes>128L*1024*1024)
                        throw new IllegalStateException("Native Vulkan snapshots exceed their GPU storage bound");
                    cached=new Snapshot(window,drawable,bytes);owner.snapshots.put(drawable,cached);owner.snapshotBytes+=bytes;
                }
                snapshot=cached.texture;
            }
            int[] previous=new int[1],fbo=new int[1];
            GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,previous,0);
            GLES30.glGenFramebuffers(1,fbo,0);GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
            try {
                GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,source.getTextureId(),0);
                if(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                    throw new IllegalStateException("Native Vulkan copy source is incomplete");
                snapshot.copyFromReadBuffer(drawable.width,drawable.height);GLES30.glFinish();
                if(GLES30.glGetError()!=GLES30.GL_NO_ERROR) throw new IllegalStateException("Native Vulkan publication GPU error");
            } finally {GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,previous[0]);GLES30.glDeleteFramebuffers(1,fbo,0);}
            drawable.forceUpdate();
            Long begin=owner.measure?owner.publicationStart.get():null;
            if(begin!=null) synchronized(owner.snapshots) {
                owner.queueNanos+=start-begin;owner.copyNanos+=System.nanoTime()-start;
                if(++owner.measuredFrames==64) {
                    Log.i("GK3HDXR","Native publication samples=64 queue_mean_ms="+owner.queueNanos/64000000.0+" copy_mean_ms="+owner.copyNanos/64000000.0);
                    owner.measuredFrames=owner.queueNanos=owner.copyNanos=0;
                }
            }
            return true;
        }
        }
    }
    /** On the native publisher thread, before its JNI detach/exit. */
    public static void releaseThread(XServer server) {
        NativeVulkan owner=session(server);if(owner==null) return;
        Long context=owner.copyContext.get();if(context==null) return;
        GPUHelper.destroyOffscreenEGLContext(context);
        synchronized(owner.contexts) {owner.contexts.remove(context);}
        owner.copyContext.remove();owner.publicationStart.remove();
        Log.i("GK3HDXR","Native Vulkan publisher context retired");
    }
    /** Called after guest/RPC shutdown and reader pause. Graphics require the root GL context. */
    public static void close(XServer server) {
        NativeVulkan owner;synchronized(sessions) {owner=sessions.remove(server);}if(owner==null) return;
        synchronized(owner.snapshots) {
            synchronized(owner.contexts) {if(owner.snapshots.isEmpty()&&owner.contexts.isEmpty())return;}
            for(Snapshot snapshot:owner.snapshots.values()) snapshot.texture.destroy();
            owner.snapshots.clear();owner.snapshotBytes=0;
        }
        android.opengl.EGLDisplay display=EGL14.eglGetCurrentDisplay();
        android.opengl.EGLContext context=EGL14.eglGetCurrentContext();
        android.opengl.EGLSurface draw=EGL14.eglGetCurrentSurface(EGL14.EGL_DRAW),read=EGL14.eglGetCurrentSurface(EGL14.EGL_READ);
        try {synchronized(owner.contexts) {for(long copy:owner.contexts) GPUHelper.destroyOffscreenEGLContext(copy);owner.contexts.clear();}}
        finally {
            if(!EGL14.eglMakeCurrent(display,draw,read,context)) throw new IllegalStateException("Cannot restore root GL context after native Vulkan cleanup");
        }
        Log.i("GK3HDXR","Native Vulkan session graphics released");
    }
}
