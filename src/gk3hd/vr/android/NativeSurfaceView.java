package org.gk3hd.standalone;

import android.content.Context;
import android.opengl.GLSurfaceView;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import java.util.ArrayDeque;
import javax.microedition.khronos.egl.EGL10;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.egl.EGLContext;
import javax.microedition.khronos.egl.EGLDisplay;
import javax.microedition.khronos.egl.EGLSurface;
import javax.microedition.khronos.opengles.GL10;

/** Owned EGL loop: vendor presentation never swaps a framework-owned surface. */
public class NativeSurfaceView extends SurfaceView implements SurfaceHolder.Callback {
    public static final int RENDERMODE_WHEN_DIRTY=0, RENDERMODE_CONTINUOUSLY=1;
    private final Object lock=new Object();
    private final ArrayDeque<Runnable> events=new ArrayDeque<>();
    private final NativeDrawProgress drawProgress=new NativeDrawProgress();
    private final Handler watchdogHandler=new Handler(Looper.getMainLooper());
    private final Runnable watchdog=this::checkNativeDraw;
    private GLSurfaceView.Renderer renderer;
    private Thread worker;
    private boolean available, resumed=true, stopping, dirty=true, changed=true, paused;
    private boolean surfaceReleased=true,closed;
    private volatile boolean externalPresentation;
    // Lifecycle callbacks publish under lock. The EGL owner also checks before swapping.
    private volatile long surfaceGeneration;
    private boolean watching; // Activity lifecycle and watchdog run on the main thread.
    private int width=1,height=1,renderMode=RENDERMODE_CONTINUOUSLY;

    public NativeSurfaceView(Context context) { super(context); getHolder().addCallback(this); }
    public void setRenderer(GLSurfaceView.Renderer value) { renderer=value; }
    public void setEGLContextClientVersion(int version) { if(version!=3) throw new IllegalArgumentException("GLES3 required"); }
    public void setEGLConfigChooser(int r,int g,int b,int a,int depth,int stencil) {
        if(r!=8||g!=8||b!=8||a!=8||depth!=0||stencil!=0) throw new IllegalArgumentException("RGBA8 framebuffer required");
    }
    public void setPreserveEGLContextOnPause(boolean value) { if(!value) throw new IllegalArgumentException("Context preservation required"); }
    public void setExternalPresentation(boolean active) {
        synchronized(lock) {externalPresentation=active;lock.notifyAll();}
    }
    public void setRenderMode(int mode) {
        if(mode!=0&&mode!=1) throw new IllegalArgumentException("Invalid render mode");
        synchronized(lock) {renderMode=mode;lock.notifyAll();}
    }
    public void requestRender() {synchronized(lock) {dirty=true;lock.notifyAll();}}
    public void queueEvent(Runnable event) {synchronized(lock) {events.add(event);lock.notifyAll();}}
    /** Retire on the EGL owner if it exists. Closing before the surface is
     * created has no EGL owner and must prevent one from starting later.
     * Returns true when the caller must wait for the queued event. */
    public boolean queueRetirement(Runnable event) {
        synchronized(lock) {
            closed=true;
            if(worker!=null&&worker!=Thread.currentThread()) {
                events.add(event);lock.notifyAll();return true;
            }
        }
        event.run();return false;
    }
    /** Called on the graphics thread before its current context is released. */
    protected void onRenderFailure(Throwable failure) {}
    private void watchNativeDraw(boolean active) {
        if(!(renderer instanceof XrPresenter)||active==watching)return;
        watching=active;
        drawProgress.active(active);
        if(active)watchdogHandler.postDelayed(watchdog,1000);
        else watchdogHandler.removeCallbacks(watchdog);
    }
    private void checkNativeDraw() {
        if(!watching)return;
        long observed=System.nanoTime();
        NativeDrawProgress.Stall stall=drawProgress.inspect(observed);
        if(stall!=null) {
            Log.e("GK3HDNativeGL","Native graphics call still in flight phase="+stall.phase+
                " elapsedMs="+stall.elapsedNs/1_000_000L);
            try {((XrPresenter)renderer).graphicsStalled(stall,observed);}
            catch(java.io.IOException error){Log.e("GK3HDNativeGL","Cannot retain graphics stall",error);}
        }
        watchdogHandler.postDelayed(watchdog,1000);
    }
    public void onResume() {
        Log.i("GK3HDNativeGL","View resume");
        synchronized(lock) {resumed=true;paused=false;dirty=true;lock.notifyAll();}
        watchNativeDraw(true);
    }
    public void onPause() {
        Log.i("GK3HDNativeGL","View pause external="+externalPresentation);
        // A slow pause alone is not a graphics failure. Require the same call
        // to have already stalled in the foreground and still block retirement.
        NativeDrawProgress.Stall pending=drawProgress.pending(System.nanoTime());
        boolean abandoned=false;
        synchronized(lock) {
            resumed=false;lock.notifyAll();
            long until=System.nanoTime()+3_000_000_000L;
            while(worker!=null && !paused && System.nanoTime()<until) {
                try {lock.wait(50);} catch(InterruptedException error) {Thread.currentThread().interrupt();break;}
            }
            if(worker!=null&&!paused&&System.nanoTime()>=until) {
                Log.e("GK3HDNativeGL","Render thread did not pause within 3 seconds");
                abandoned=drawProgress.stillPending(pending);
            }
        }
        watchNativeDraw(false);
        if(abandoned)((XrPresenter)renderer).graphicsAbandoned();
    }
    @Override public void surfaceCreated(SurfaceHolder holder) {
        Log.i("GK3HDNativeGL","Window surface created external="+externalPresentation);
        synchronized(lock) {
            if(closed) return;
            available=true;stopping=false;changed=true;dirty=true;
            long generation=++surfaceGeneration;
            watchNativeDraw(resumed);
            if(worker==null) {worker=new Thread(()->render(generation),"GK3HDNativeGL");worker.start();}
            lock.notifyAll();
        }
    }
    @Override public void surfaceChanged(SurfaceHolder holder,int format,int w,int h) {
        synchronized(lock) {width=w;height=h;changed=true;dirty=true;lock.notifyAll();}
    }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        Log.i("GK3HDNativeGL","Window surface destroyed external="+externalPresentation);
        synchronized(lock) {
            available=false;surfaceGeneration++;lock.notifyAll();
            long until=System.nanoTime()+3_000_000_000L;
            while(worker!=null&&!surfaceReleased&&System.nanoTime()<until) {
                try {lock.wait(50);} catch(InterruptedException error) {Thread.currentThread().interrupt();break;}
            }
            if(worker!=null&&!surfaceReleased) Log.e("GK3HDNativeGL","Render thread did not release window within 3 seconds");
        }
    }
    /** Release only after the activity stops its guest/compatibility workers. */
    public void close() {
        watchNativeDraw(false);
        Thread current;
        synchronized(lock) {closed=true;stopping=true;lock.notifyAll();current=worker;}
        if(current!=null&&current!=Thread.currentThread()) {
            try {current.join(3000);} catch(InterruptedException error) {Thread.currentThread().interrupt();}
            if(current.isAlive()) Log.e("GK3HDNativeGL","EGL worker did not close within 3 seconds");
        }
    }
    private void render(long windowGeneration) {
        EGL10 egl=(EGL10)EGLContext.getEGL();
        EGLDisplay display=egl.eglGetDisplay(EGL10.EGL_DEFAULT_DISPLAY);
        EGLContext context=EGL10.EGL_NO_CONTEXT;
        EGLSurface window=EGL10.EGL_NO_SURFACE,fallback=EGL10.EGL_NO_SURFACE;
        boolean watchDraws=renderer instanceof XrPresenter;
        if(watchDraws)drawProgress.begin(NativeDrawProgress.Phase.SETUP,System.nanoTime());
        try {
            if(!egl.eglInitialize(display,new int[2])) throw new IllegalStateException("eglInitialize");
            int[] attributes={EGL10.EGL_RED_SIZE,8,EGL10.EGL_GREEN_SIZE,8,EGL10.EGL_BLUE_SIZE,8,EGL10.EGL_ALPHA_SIZE,8,
                EGL10.EGL_DEPTH_SIZE,0,EGL10.EGL_STENCIL_SIZE,0,EGL10.EGL_RENDERABLE_TYPE,0x40,EGL10.EGL_SURFACE_TYPE,5,EGL10.EGL_NONE};
            EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
            if(!egl.eglChooseConfig(display,attributes,configs,1,count)||count[0]==0) throw new IllegalStateException("GLES3 EGL config");
            context=egl.eglCreateContext(display,configs[0],EGL10.EGL_NO_CONTEXT,new int[]{0x3098,3,EGL10.EGL_NONE});
            window=egl.eglCreateWindowSurface(display,configs[0],getHolder(),null);
            fallback=egl.eglCreatePbufferSurface(display,configs[0],new int[]{EGL10.EGL_WIDTH,1,EGL10.EGL_HEIGHT,1,EGL10.EGL_NONE});
            if(context.equals(EGL10.EGL_NO_CONTEXT)||window.equals(EGL10.EGL_NO_SURFACE)||
               fallback.equals(EGL10.EGL_NO_SURFACE)||!egl.eglMakeCurrent(display,window,window,context))
                throw new IllegalStateException("EGL context/surface");
            synchronized(lock) {surfaceReleased=false;}
            GL10 gl=(GL10)context.getGL();
            renderer.onSurfaceCreated(gl,configs[0]);
            if(watchDraws)drawProgress.finish();
            while(true) {
                Runnable event=null; boolean resize=false,detach=false,attach=false;int w=1,h=1;
                long nextWindowGeneration=windowGeneration;
                synchronized(lock) {
                    // A headset compositor may retire the ordinary Android
                    // window while the visible/resumed VR session still owns
                    // output. Its valid fallback EGL surface can keep drawing.
                    while(events.isEmpty() && !stopping && ((!available&&!externalPresentation)||!resumed||(renderMode==0&&!dirty&&!changed))) {
                        if(!surfaceReleased&&windowGeneration!=surfaceGeneration) break;
                        paused=!resumed||!available;lock.notifyAll();lock.wait();
                    }
                    // Lifecycle events run before pausing or destroying the EGL context.
                    if(!events.isEmpty()) event=events.remove();
                    else if(stopping) break;
                    // Android can create the replacement after its bounded
                    // destroy wait expires, before the EGL owner can detach.
                    else if(!surfaceReleased&&windowGeneration!=surfaceGeneration) detach=true;
                    else if(resumed) {
                        attach=available&&surfaceReleased;resize=available&&(changed||attach);
                        nextWindowGeneration=surfaceGeneration;changed=false;dirty=false;w=width;h=height;
                    }
                }
                if(event!=null) {event.run();continue;}
                if(detach) {
                    if(!egl.eglMakeCurrent(display,fallback,fallback,context)) throw new IllegalStateException("EGL pause pbuffer");
                    // The vendor may already have retired the initial window.
                    if(!window.equals(EGL10.EGL_NO_SURFACE)) {egl.eglDestroySurface(display,window);egl.eglGetError();window=EGL10.EGL_NO_SURFACE;}
                    synchronized(lock) {surfaceReleased=true;lock.notifyAll();}
                    continue;
                }
                try {
                    if(watchDraws&&resize)drawProgress.begin(NativeDrawProgress.Phase.RESIZE,System.nanoTime());
                    if(attach) {
                        window=egl.eglCreateWindowSurface(display,configs[0],getHolder(),null);
                        if(window.equals(EGL10.EGL_NO_SURFACE)||!egl.eglMakeCurrent(display,window,window,context))
                            throw new IllegalStateException("EGL resumed window");
                        windowGeneration=nextWindowGeneration;
                        synchronized(lock) {surfaceReleased=false;}
                    }
                    if(resize)renderer.onSurfaceChanged(gl,w,h);
                    if(watchDraws)drawProgress.begin(NativeDrawProgress.Phase.DRAW,System.nanoTime());
                    renderer.onDrawFrame(gl);
                    if(!externalPresentation&&windowGeneration==surfaceGeneration) {
                        if(watchDraws)drawProgress.begin(NativeDrawProgress.Phase.SWAP,System.nanoTime());
                        EGLSurface current=egl.eglGetCurrentSurface(EGL10.EGL_DRAW);
                        if(current.equals(EGL10.EGL_NO_SURFACE)||!egl.eglSwapBuffers(display,current)) throw new IllegalStateException("eglSwapBuffers: "+egl.eglGetError());
                    }
                } finally {if(watchDraws)drawProgress.finish();}
            }
        } catch(Throwable error) {
            if(watchDraws)drawProgress.finish();
            Log.e("GK3HDNativeGL","EGL loop failed",error);
            synchronized(lock) {closed=true;stopping=true;lock.notifyAll();}
            try {onRenderFailure(error);}
            catch(Throwable cleanup) {error.addSuppressed(cleanup);Log.e("GK3HDNativeGL","Failed render-loop retirement",error);}
        } finally {
            EGLSurface current=egl.eglGetCurrentSurface(EGL10.EGL_DRAW);
            egl.eglMakeCurrent(display,EGL10.EGL_NO_SURFACE,EGL10.EGL_NO_SURFACE,EGL10.EGL_NO_CONTEXT);
            if(!current.equals(EGL10.EGL_NO_SURFACE)&&!current.equals(window)&&!current.equals(fallback)) egl.eglDestroySurface(display,current);
            if(!window.equals(EGL10.EGL_NO_SURFACE)) egl.eglDestroySurface(display,window);
            if(!fallback.equals(EGL10.EGL_NO_SURFACE)) egl.eglDestroySurface(display,fallback);
            if(!context.equals(EGL10.EGL_NO_CONTEXT)) egl.eglDestroyContext(display,context);
            // EGL_DEFAULT_DISPLAY belongs to the whole compatibility host.
            // Terminating it here invalidates other threads' live GL contexts.
            Log.i("GK3HDNativeGL","Owned EGL context released; shared display retained external="+externalPresentation);
            synchronized(lock) {worker=null;paused=true;lock.notifyAll();}
        }
    }
}
