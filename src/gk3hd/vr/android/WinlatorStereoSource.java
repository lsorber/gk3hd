package com.winlator.renderer;

import android.opengl.GLES20;
import android.util.Log;
import com.winlator.StandaloneGameActivity;
import com.winlator.widget.XServerView;
import com.winlator.xserver.Drawable;
import com.winlator.xserver.Window;
import com.winlator.xserver.XLock;
import com.winlator.xserver.XServer;
import com.winlator.xserver.Pointer;
import javax.microedition.khronos.opengles.GL10;
import org.gk3hd.standalone.XrPresenter;
import org.gk3hd.standalone.XrApiBridge;
import org.gk3hd.standalone.XrInput;
import org.gk3hd.standalone.StereoTransfer;
import org.gk3hd.standalone.AsyncStereoTransfer;
import org.gk3hd.standalone.BorrowedPresentFrames;
import org.gk3hd.standalone.RendererRecovery;
import com.winlator.xenvironment.RootFS;
import java.io.File;
import java.io.PrintWriter;
import android.app.Activity;
import android.graphics.Bitmap;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Select the OpenXR runtime's simultaneous stereo window, never GK3's mono mirror. */
public final class WinlatorStereoSource extends GLRenderer implements XrPresenter.Source {
    private final XServer server;
    private StereoTransfer transfer;
    private AsyncStereoTransfer asyncTransfer;
    private java.util.function.BooleanSupplier outputTarget;
    private final boolean asynchronous;
    private final boolean measureSnapshotTiming;
    private int eyeWidth,eyeHeight,transportHeight;
    private Integer renderedId;
    private Window stereo;
    private int reportedWindow;
    private final XrApiBridge bridge;
    private final boolean captureGuest;
    private final String captureTag;
    private final int diagnosticClickX,diagnosticClickY;
    private int diagnosticCount;
    private long nextDiagnostic;
    private final long diagnosticInterval;
    private final boolean testStereoSource;
    private final java.util.HashMap<Integer,String> windowTrace=new java.util.HashMap<>();
    private int stereoAttempts;
    private Drawable lastDrawable;
    private Texture lastContentTexture;
    private long lastContentGeneration;
    private Drawable borrowedContent;
    private final boolean publicationGate;
    private final boolean nativeGraphics;
    private org.gk3hd.standalone.GlTransferProfile transferProfile;
    private int profileGeneration;
    private boolean leasedMetadata;
    private boolean frameIdentities;
    private boolean linearOutput;
    private boolean preferPaddedEyeBlit;
    private final Object movieFocusLock=new Object();
    private boolean movieFocused;
    private volatile org.gk3hd.standalone.AndroidMovieHost movies;
    private boolean nativeMovieRendered;

    public WinlatorStereoSource(XServerView view,XServer server) {
        super(view,server);this.server=server;
        captureGuest=view.getContext() instanceof Activity &&
            ((Activity)view.getContext()).getIntent().getBooleanExtra("gk3hd_capture_guest",false);
        String tag=view.getContext() instanceof Activity ?
            ((Activity)view.getContext()).getIntent().getStringExtra("gk3hd_capture_tag") : null;
        if(tag!=null&&!tag.matches("[a-z0-9-]{1,32}")) throw new IllegalArgumentException("Invalid diagnostic tag");
        captureTag=tag==null ? "session" : tag;
        android.content.Intent intent=((Activity)view.getContext()).getIntent();
        nativeGraphics=intent.getBooleanExtra("gk3hd_native_vulkan",false);
        publicationGate=!com.winlator.BuildConfig.DEBUG||!intent.getBooleanExtra("gk3hd_test_legacy_publication",false);
        // Normal standalone play uses the measured nonblocking immutable path.
        // Synchronous transfer remains an explicit debug comparison only.
        asynchronous=!com.winlator.BuildConfig.DEBUG||intent.getBooleanExtra("gk3hd_async_transfer",true);
        measureSnapshotTiming=com.winlator.BuildConfig.DEBUG&&intent.getBooleanExtra("gk3hd_test_snapshot_timing",false);
        int interval=intent.getIntExtra("gk3hd_capture_interval_ms",10000);
        if(interval<1000||interval>30000) throw new IllegalArgumentException("Invalid diagnostic interval");
        diagnosticInterval=interval*1_000_000L;
        testStereoSource=intent.getBooleanExtra("gk3hd_test_stereo_source",false);
        diagnosticClickX=captureGuest ? intent.getIntExtra("gk3hd_click_x",-1) : -1;
        diagnosticClickY=captureGuest ? intent.getIntExtra("gk3hd_click_y",-1) : -1;
        if(diagnosticClickX>=server.screenInfo.width||diagnosticClickY>=server.screenInfo.height||
           (diagnosticClickX<0)!=(diagnosticClickY<0)) throw new IllegalArgumentException("Invalid diagnostic click");
        try {bridge=new XrApiBridge();} catch(java.io.IOException error) {throw new IllegalStateException("XR bridge socket failed",error);}
    }
    @Override public void focused(boolean value) {
        synchronized(movieFocusLock) {
            if(movieFocused==value)return;
            bridge.focused(value);
            movieFocused=value;
            org.gk3hd.standalone.AndroidMovieHost active=movies;
            if(active!=null)active.focused(value);
        }
    }
    @Override public void trackingEpoch(long epoch) {bridge.trackingEpoch(epoch);}
    private boolean movieRenderable=true;
    @Override public void moviePresentation(boolean eligible) {
        if(movieRenderable==eligible)return;
        movieRenderable=eligible;
        org.gk3hd.standalone.AndroidMovieHost active=movies;
        if(active!=null)active.presentation(eligible);
    }
    @Override public boolean readyForSession() {return bridge.runtimeConnected();}
    @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs) throws java.io.IOException {
        tracking(head,flags,ipd,fovX,fovY,hz,frame,inputs,null);
    }
    @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,org.gk3hd.standalone.StereoViews views) throws java.io.IOException {
        stageTracking(head,flags,frame,views);
        publishTracking(head,flags,ipd,fovX,fovY,hz,frame,inputs,views);
    }
    @Override public void stageTracking(float[] head,int flags,int frame,org.gk3hd.standalone.StereoViews views) {
        if(movies!=null)movies.tracking(head,flags,frame,views);
    }
    @Override public void publishTracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,org.gk3hd.standalone.StereoViews views) throws java.io.IOException {
        bridge.update(head,flags,ipd,fovX,fovY,hz,frame,inputs,views);
    }
    @Override public void close() {
        bridge.close();
        if(movies==null&&transferProfile==null&&!org.gk3hd.standalone.NativeVulkan.active(server)&&!org.gk3hd.standalone.PresentCopyRetirement.active(server)&&!org.gk3hd.standalone.BorrowedPresentFrames.active(server)) return;
        java.util.concurrent.CountDownLatch finished=new java.util.concurrent.CountDownLatch(1);
        if(!xServerView.queueRetirement(()-> {try {closeGraphics();} finally {finished.countDown();}}))return;
        try {
            if(!finished.await(3,java.util.concurrent.TimeUnit.SECONDS)) Log.e("GK3HDXR","Native Vulkan cleanup did not complete before root-loop closure");
        } catch(InterruptedException error) {Thread.currentThread().interrupt();}
    }
    private void closeGraphics() {
        if(movies!=null){try{movies.close();}catch(Exception error){Log.e("GK3HDMovies","Movie host cleanup failed",error);}movies=null;}
        if(transferProfile!=null) {transferProfile.close();transferProfile=null;}
        if(asyncTransfer!=null) {asyncTransfer.close();asyncTransfer=null;}
        org.gk3hd.standalone.BorrowedPresentFrames.close(server);
        org.gk3hd.standalone.PresentCopyRetirement.close(server);
        org.gk3hd.standalone.NativeVulkan.close(server);
    }
    private void pollBorrowedFrames() {
        try {BorrowedPresentFrames.poll(server);}
        catch(RendererRecovery.StereoTimeout timeout) {
            reportStereoTimeout();throw timeout;
        }
    }

    private void reportStereoTimeout() {
        if(xServerView.getContext() instanceof StandaloneGameActivity)
            ((StandaloneGameActivity)xServerView.getContext()).requestRendererRecovery();
    }

    // The caller holds the window and drawable manager locks while checking
    // the producer, so a remap cannot hide a withdrawal we just observed.
    private boolean discardUnavailableBorrowedInputs() {
        return BorrowedPresentFrames.discardUnavailable(server,identity->
            identity instanceof Drawable&&
            registeredStereoContent(server.windowManager.getWindow(((Drawable)identity).id))==identity);
    }

    private void retireBorrowedSnapshots() {
        // Invalidation queues the ordinary read-completion fences. The pool
        // returns the pixmaps only after poll observes those fences complete.
        asyncTransfer.invalidate();borrowedContent=null;renderedId=null;
        Log.i("GK3HDXR","Retired withdrawn stereo input snapshots behind their GPU read fences");
    }

    // Retire withdrawn producers even when the headset cannot draw a frame.
    // A flat desktop is never promoted to the stereo source.
    @Override public void serviceFrame(GL10 gl) throws Exception {
        if(asyncTransfer!=null&&org.gk3hd.standalone.BorrowedPresentFrames.active(server)) {
            boolean withdrawn;
            try(XLock lock=server.lock(XServer.Lockable.WINDOW_MANAGER,XServer.Lockable.DRAWABLE_MANAGER)) {
                withdrawn=discardUnavailableBorrowedInputs();
            }
            if(withdrawn)retireBorrowedSnapshots();
        }
        org.gk3hd.standalone.PresentCopyRetirement.poll(server);
        pollBorrowedFrames();
        if(transferProfile!=null) transferProfile.poll();
        if(!captureGuest || diagnosticCount>=2) return;
        long now=System.nanoTime();
        if(nextDiagnostic==0) nextDiagnostic=now+diagnosticInterval;
        if(now<nextDiagnostic) return;
        nextDiagnostic=now+diagnosticInterval;
        int width=1280,height=800,oldWidth=surfaceWidth,oldHeight=surfaceHeight;
        int[] previous=new int[1],fbo=new int[1],texture=new int[1];
        GLES20.glGetIntegerv(GLES20.GL_FRAMEBUFFER_BINDING,previous,0);
        GLES20.glGenTextures(1,texture,0);GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,texture[0]);
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D,0,GLES20.GL_RGBA,width,height,0,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,null);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_NEAREST);
        GLES20.glGenFramebuffers(1,fbo,0);GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER,fbo[0]);
        GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER,GLES20.GL_COLOR_ATTACHMENT0,GLES20.GL_TEXTURE_2D,texture[0],0);
        try {
            if(GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER)!=GLES20.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Diagnostic framebuffer incomplete");
            super.onSurfaceChanged(gl,width,height);super.onDrawFrame(gl);
            ByteBuffer bytes=ByteBuffer.allocateDirect(width*height*4).order(ByteOrder.LITTLE_ENDIAN);
            GLES20.glReadPixels(0,0,width,height,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,bytes);
            int[] pixels=new int[width*height];
            for(int y=0;y<height;y++) for(int x=0;x<width;x++) {
                int p=bytes.getInt((y*width+x)*4);
                pixels[(height-y-1)*width+x]=(p&0xff00ff00)|((p&0xff)<<16)|((p>>>16)&0xff);
            }
            Bitmap bitmap=Bitmap.createBitmap(pixels,width,height,Bitmap.Config.ARGB_8888);
            File output=new File(xServerView.getContext().getFilesDir(),"guest-diagnostic-"+captureTag+"-"+(++diagnosticCount)+".png");
            try(java.io.FileOutputStream out=new java.io.FileOutputStream(output)) {bitmap.compress(Bitmap.CompressFormat.PNG,100,out);}
            bitmap.recycle();Log.i("GK3HDXR","MONO diagnostic saved, not a headset source: "+output.getName());
            if(diagnosticCount==1&&diagnosticClickX>=0) {
                server.injectPointerMove(diagnosticClickX,diagnosticClickY);
                android.os.Handler handler=new android.os.Handler(android.os.Looper.getMainLooper());
                handler.postDelayed(()->server.injectPointerButtonPress(Pointer.Button.BUTTON_LEFT),50);
                handler.postDelayed(()->server.injectPointerButtonRelease(Pointer.Button.BUTTON_LEFT),100);
                Log.i("GK3HDXR","Diagnostic native X input at "+diagnosticClickX+","+diagnosticClickY);
            }
        } finally {
            super.onSurfaceChanged(gl,oldWidth,oldHeight);
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER,previous[0]);
            GLES20.glDeleteFramebuffers(1,fbo,0);GLES20.glDeleteTextures(1,texture,0);
        }
    }
    @Override public void configure(int eyeWidth,int eyeHeight) throws Exception {
        this.eyeWidth=eyeWidth;this.eyeHeight=eyeHeight;
        transportHeight=org.gk3hd.standalone.StereoTransport.height(eyeHeight);
        File directory=new File(RootFS.find(xServerView.getContext()).getRootDir(),"tmp/xr");
        if(!directory.isDirectory()&&!directory.mkdirs()) throw new java.io.IOException("XR metadata directory unavailable");
        try(PrintWriter out=new PrintWriter(new File(directory,"system"),"UTF-8")) {
            out.println(android.os.Build.MANUFACTURER);out.println(android.os.Build.MODEL);
            out.println(android.os.Build.VERSION.RELEASE);out.println(android.os.Build.VERSION.SECURITY_PATCH);
            out.println((eyeWidth*2)+"x"+eyeHeight);out.println(eyeWidth+"x"+eyeHeight);
        }
    }
    private Drawable stereoContent(Window window) {
        if(window==null||!window.attributes.isMapped()||!window.attributes.isViewable())return null;
        Drawable content=window.getContent();
        return content!=null&&!content.isOffscreenStorage()&&
            content.width==eyeWidth*2&&content.height==transportHeight ? content : null;
    }

    private static String windowTitle(Window window) {
        String name=window.getName();
        // Recent Wine versions publish only the EWMH UTF-8 title. Keep the
        // exact producer identity check rather than accepting an arbitrary
        // window merely because it happens to have the stereo dimensions.
        if(name.isEmpty()) {
            int atom=com.winlator.xserver.Atom.getId("_NET_WM_NAME");
            com.winlator.xserver.Property title=atom>0 ? window.getProperty(atom) : null;
            if(title!=null&&title.data.capacity()<=256&&title.format==com.winlator.xserver.Property.Format.BYTE_ARRAY&&
               (com.winlator.xserver.Atom.getName(title.type).equals("UTF8_STRING")||
                com.winlator.xserver.Atom.getName(title.type).equals("STRING"))) name=title.toString();
        }
        return name;
    }

    private static boolean stereoTitle(String name) {
        return name.equals("GK3HD XR stereo")||name.equals("OpenXR Simulator (Mouse Look + WASD)");
    }

    private Drawable registeredStereoContent(Window window) {
        Drawable content=stereoContent(window);
        if(content==null||server.windowManager.getWindow(window.id)!=window)return null;
        boolean producer=false;
        for(Window parent=window;parent!=null;parent=parent.getParent()) {
            if(!parent.attributes.isMapped())return null;
            producer=producer||stereoTitle(windowTitle(parent));
        }
        return producer ? content : null;
    }

    // Availability and drawing acquire the X locks separately. Recover the
    // current producer here if the earlier choice was withdrawn in between.
    private Drawable stereoContentForDraw() {
        Drawable content=registeredStereoContent(stereo);
        if(content!=null)return content;
        stereo=findStereo(server.windowManager.rootWindow);
        return registeredStereoContent(stereo);
    }

    private Window findStereo(Window window) {return findStereo(window,false);}
    private Window findStereo(Window window,boolean insideProducer) {
        if(!window.attributes.isMapped())return null;
        String name=windowTitle(window);
        if(testStereoSource&&windowTrace.size()<128) {
            Drawable content=window.getContent();
            String state=name+" viewable="+window.attributes.isViewable()+" content="+
                (content==null ? "none" : content.width+"x"+content.height+" offscreen="+content.isOffscreenStorage()+
                    " texture="+content.getTexture().getClass().getSimpleName());
            if(!state.equals(windowTrace.put(window.id,state))) Log.i("GK3HDXR","Fixture X window="+window.id+" "+state);
        }
        boolean producer=insideProducer||stereoTitle(name);
        // Wine may put the Vulkan client surface in an unnamed child. Follow
        // only descendants of the explicitly identified stereo producer.
        for(Window child:window.getChildren()) {
            Window found=findStereo(child,producer);if(found!=null) return found;
        }
        // A redirected child can have the right dimensions but no readable
        // window pixels. Reject it inside the search so siblings can still win.
        return producer&&stereoContent(window)!=null ? window : null;
    }
    @Override public boolean hasStereoFrame() {
        boolean withdrawn=false, available;
        try(XLock lock=server.lock(XServer.Lockable.WINDOW_MANAGER)) {
            stereo=findStereo(server.windowManager.rootWindow);
            if(stereo==null&&asyncTransfer!=null&&BorrowedPresentFrames.active(server)) {
                try(XLock drawableLock=server.lock(XServer.Lockable.DRAWABLE_MANAGER)) {
                    withdrawn=discardUnavailableBorrowedInputs();
                }
            }
            available=(movies!=null&&movies.active())||stereo!=null;
        }
        if(withdrawn)retireBorrowedSnapshots();
        return available;
    }
    @Override public Integer renderedFrameId() {return renderedId;}
    @Override public long renderedSnapshot() {
        if(nativeMovieRendered)return movies.renderedSnapshot();
        return renderedId==null||asyncTransfer==null ? 0 : asyncTransfer.snapshotToken();
    }
    @Override public boolean renderedOutputUnchanged() {
        return !nativeMovieRendered&&renderedId!=null&&asyncTransfer!=null&&asyncTransfer.outputUnchanged();
    }
    @Override public boolean renderedWithPaddedEyeBlit() {
        return !nativeMovieRendered&&renderedId!=null&&asyncTransfer!=null&&asyncTransfer.outputPaddedEyeBlit();
    }
    @Override public void linearOutput(boolean value) {
        if(transfer!=null||asyncTransfer!=null)throw new IllegalStateException("Configure output color before creating source GL resources");
        linearOutput=value;
    }
    @Override public void preferPaddedEyeBlit() {preferPaddedEyeBlit=true;}
    @Override public void onSurfaceCreated(GL10 gl,javax.microedition.khronos.egl.EGLConfig config) {
        super.onSurfaceCreated(gl,config);
        Activity activity=(Activity)xServerView.getContext();
        String movieSession=activity.getIntent().getStringExtra("gk3hd_frame_session");
        if(transferProfile!=null) transferProfile.abandonContext();
        transferProfile=com.winlator.BuildConfig.DEBUG ? org.gk3hd.standalone.GlTransferProfile.create(
            (Activity)xServerView.getContext(),++profileGeneration) : null;
        transfer=new StereoTransfer(transferProfile,linearOutput);renderedId=null;
        org.gk3hd.standalone.PresentCopyRetirement.enable(server);
        // Capability boundary: this is the managed direct-GL image path, not a
        // headset-model choice. Native Vulkan and synchronous transfers keep
        // their existing ownership-correct copy path.
        boolean copyControl=com.winlator.BuildConfig.DEBUG&&((Activity)xServerView.getContext()).getIntent().getBooleanExtra("gk3hd_test_copy_present",false);
        boolean retainMetadata=!com.winlator.BuildConfig.DEBUG||((Activity)xServerView.getContext()).getIntent()
            .getBooleanExtra("gk3hd_test_leased_metadata",true);
        // The render callback can precede asynchronous environment preparation.
        // Choose from the launch contract as well as already prepared state.
        if(asynchronous&&!nativeGraphics&&!org.gk3hd.standalone.NativeVulkan.active(server)&&!copyControl) {
            boolean preferNewestReady=retainMetadata&&com.winlator.BuildConfig.DEBUG&&
                ((Activity)xServerView.getContext()).getIntent().getBooleanExtra("gk3hd_test_latest_ready_stereo",false);
            org.gk3hd.standalone.BorrowedPresentFrames.enable(server,retainMetadata,measureSnapshotTiming,preferNewestReady);
            Log.i("GK3HDXR","Managed stereo input retained through metadata and final GPU copy");
        }
        // Exact same-APK copy control for measurements, ignored in release builds.
        leasedMetadata=org.gk3hd.standalone.BorrowedPresentFrames.active(server)&&retainMetadata;
        asyncTransfer=asynchronous ? new AsyncStereoTransfer(measureSnapshotTiming,transferProfile,
            leasedMetadata ? server : null,leasedMetadata,linearOutput) : null;
        if(asyncTransfer!=null&&preferPaddedEyeBlit&&leasedMetadata&&!linearOutput)
            asyncTransfer.preferPaddedEyeBlit();
        frameIdentities=false;
        File metadata=activity instanceof StandaloneGameActivity
            ? ((StandaloneGameActivity)activity).frameMetadata() : null;
        if(asyncTransfer!=null&&metadata!=null) {
            asyncTransfer.identities(new org.gk3hd.standalone.FrameIdentity(
                new org.gk3hd.standalone.MappedFrameMetadata(metadata)));
            frameIdentities=true;
            if(movieSession!=null)createMovieHost(activity,metadata.getParentFile(),movieSession);
        }
        Log.i("GK3HDXR","Retained source through final copy="+leasedMetadata);
        lastDrawable=null;lastContentTexture=null;
        if(((Activity)xServerView.getContext()).getIntent().getBooleanExtra("gk3hd_test_transport",false)) {
            try {
                Class.forName("org.gk3hd.standalone.StereoTransferTests").getMethod("run").invoke(null);
                Log.i("GK3HDXR","Stereo transport GPU fixture passed; synthetic test only, not game output");
            } catch(Exception error) {throw new IllegalStateException("Stereo transport fixture failed",error);}
        }
    }
    @Override public void onDrawFrame(GL10 gl) {
        drawFrame(gl,0);
    }
    private void createMovieHost(Activity activity,File game,String movieSession) {
        if(new File(game,"gk3hd/videos/installed").isDirectory())try {
            if(movies!=null)throw new IllegalStateException("Previous movie host was not retired");
            org.gk3hd.standalone.AndroidMovieHost candidate=new org.gk3hd.standalone.AndroidMovieHost(game,movieSession,
                new android.os.Handler(activity.getMainLooper()),xServerView::queueEvent);
            synchronized(movieFocusLock) {
                candidate.presentation(movieRenderable);
                candidate.focused(movieFocused);
                movies=candidate;
            }
        }catch(java.io.IOException error){throw new IllegalStateException("Cannot create native movie host",error);}
    }
    @Override public boolean drawFrame(GL10 gl,long retainedSnapshot,java.util.function.BooleanSupplier target) {
        if(target==null||outputTarget!=null)throw new IllegalStateException("Missing or reentrant native output");
        // Only the managed immutable world path can select before acquiring.
        if(asyncTransfer==null||!frameIdentities||!leasedMetadata||
           !org.gk3hd.standalone.BorrowedPresentFrames.active(server)||(movies!=null&&movies.active())) {
            renderedId=null;nativeMovieRendered=false;
            if(!target.getAsBoolean())return false;
            drawFrame(gl,0);return renderedId!=null;
        }
        outputTarget=target;
        try {drawFrame(gl,retainedSnapshot);return renderedId!=null;}
        finally {outputTarget=null;}
    }
    @Override public void drawFrame(GL10 gl,long retainedSnapshot) {
        renderedId=null;nativeMovieRendered=false;
        try {
            if(movies!=null&&movies.active()) {
                nativeMovieRendered=movies.draw(eyeWidth,eyeHeight,linearOutput);
                // Keep native Update/input/EOF advancing, and layer only a verified
                // transparent output belonging to this exact movie over its video.
                drawGameFrame(gl,0,movies.owner());
                renderedId=nativeMovieRendered ? movies.renderedFrame() : null;
                return;
            }
            drawGameFrame(gl,retainedSnapshot,0);
        } catch(RendererRecovery.StereoTimeout timeout) {
            reportStereoTimeout();throw timeout;
        }
    }
    private void drawGameFrame(GL10 gl,long retainedSnapshot,long movie) {
        if(org.gk3hd.standalone.BorrowedPresentFrames.active(server)) {
            drawBorrowed(retainedSnapshot,movie);verifyFixtureOutput();return;
        }
        try(XLock lock=server.lock(XServer.Lockable.WINDOW_MANAGER,XServer.Lockable.DRAWABLE_MANAGER)) {
            Drawable drawable=stereoContentForDraw();
            if(drawable==null)return;
            synchronized(drawable.renderLock) {
                Texture texture=drawable.getTexture();
                if(org.gk3hd.standalone.NativeVulkan.active(server)) {
                    texture=org.gk3hd.standalone.NativeVulkan.texture(server,drawable);
                    if(texture==null) return;
                }
                boolean replaced=drawable!=lastDrawable||texture!=lastContentTexture;
                long generation=texture.getContentGeneration();
                boolean changed=replaced||(publicationGate ? generation!=lastContentGeneration : texture.isNeedsUpdate());
                if(asyncTransfer==null) {
                    // A synchronous metadata read is not a cross-context
                    // producer fence. Protect both the read and the eye blit,
                    // including cached-ID frames that issue no readback.
                    if(texture.beginXrRead()) {
                        try {
                            texture.updateFromDrawable();
                            renderedId=transfer.draw(texture.getTextureId(),eyeWidth*2,transportHeight,eyeHeight,texture.isFlipY(),surfaceWidth,surfaceHeight,changed);
                        }
                        finally {texture.endXrRead();}
                    }
                } else {
                    if(replaced) asyncTransfer.invalidate();
                    if(asyncTransfer.prepare(eyeWidth*2,transportHeight,eyeHeight,changed)&&texture.beginXrRead()) {
                        try {texture.updateFromDrawable();asyncTransfer.capture(texture.getTextureId(),texture.isFlipY());}
                        finally {texture.endXrRead();}
                    }
                }
                lastDrawable=drawable;lastContentTexture=texture;lastContentGeneration=generation;
                if(testStereoSource&&asyncTransfer==null&&renderedId==null&&stereoAttempts++%10==0&&stereoAttempts<81) {
                    try {Class.forName("org.gk3hd.standalone.StereoSourceTests").getMethod("diagnose",int.class,int.class,int.class)
                        .invoke(null,texture.getTextureId(),eyeWidth*2,transportHeight);}
                    catch(Exception error) {throw new IllegalStateException("Stereo pixel diagnostic failed",error);}
                }
                if(reportedWindow!=stereo.id) {
                    reportedWindow=stereo.id;
                    Log.i("GK3HDXR","stereo source window="+stereo.id+" name="+stereo.getName()+" size="+drawable.width+"x"+drawable.height+
                        " texture="+texture.getClass().getSimpleName());
                }
            }
        }
        // Our snapshot is immutable and owns its storage. Do not hold the X
        // producer's lock while presenting it or polling a completed PBO.
        if(asyncTransfer!=null) renderedId=asyncTransfer.draw(surfaceWidth,surfaceHeight,retainedSnapshot,movie,outputTarget);
        verifyFixtureOutput();
    }
    private void verifyFixtureOutput() {
        if(testStereoSource&&renderedId!=null) {
            try {Class.forName("org.gk3hd.standalone.StereoSourceTests").getMethod("verify",android.content.Context.class,int.class,int.class,int.class)
                .invoke(null,xServerView.getContext(),renderedId,eyeWidth,eyeHeight);}
            catch(Exception error) {throw new IllegalStateException("Stereo source fixture failed",error);}
        }
    }
    private void drawBorrowed(long retainedSnapshot,long movie) {
        if(asyncTransfer==null)throw new IllegalStateException("Borrowed source requires immutable asynchronous snapshots");
        try(XLock lock=server.lock(XServer.Lockable.WINDOW_MANAGER,XServer.Lockable.DRAWABLE_MANAGER)) {
            Drawable content=stereoContentForDraw();
            if(content==null) {
                if(discardUnavailableBorrowedInputs())retireBorrowedSnapshots();
                return;
            }
            // Winlator can replace the drawable on resize without replacing the window.
            if(content!=borrowedContent){asyncTransfer.invalidate();borrowedContent=content;}
            boolean captureReady=asyncTransfer.prepare(eyeWidth*2,transportHeight,eyeHeight,true);
            // GPU-only labels draw the completed selection first. Verified CPU
            // labels can select the newly acquired immutable image immediately
            // and draw after acquisition, without waiting another host tick.
            if(!frameIdentities)renderedId=asyncTransfer.draw(surfaceWidth,surfaceHeight,retainedSnapshot,movie,outputTarget);
            if(captureReady) {
                org.gk3hd.standalone.BorrowedPresentFrames.Frame frame=
                    org.gk3hd.standalone.BorrowedPresentFrames.take(server,content,eyeWidth*2,transportHeight);
                if(frame!=null) {
                    if(leasedMetadata)asyncTransfer.capture(frame);
                    else {
                        asyncTransfer.capture(frame.texture,frame.flip);
                        org.gk3hd.standalone.BorrowedPresentFrames.release(server,frame);
                    }
                }
            }
        }
        if(frameIdentities)renderedId=asyncTransfer.draw(surfaceWidth,surfaceHeight,retainedSnapshot,movie,outputTarget);
        BorrowedPresentFrames.poll(server);
    }
    public long[] snapshotTiming(Integer id) {return asyncTransfer==null ? null : asyncTransfer.timing(id);}
    public void observeSnapshotCompletions(java.util.function.Consumer<long[]> observer) {
        if(!com.winlator.BuildConfig.DEBUG||asyncTransfer==null)
            throw new IllegalStateException("Completion observation requires the debug asynchronous source");
        asyncTransfer.observeCompletions(observer);
    }
    public void pollSnapshotCompletions() {
        if(!com.winlator.BuildConfig.DEBUG||asyncTransfer==null)
            throw new IllegalStateException("Completion observation requires the debug asynchronous source");
        asyncTransfer.pollCompletions();
    }
    public long[] snapshotOutputCounts() {return asyncTransfer==null ? new long[]{0,0,0,0} : asyncTransfer.outputCounts();}
    public long[] snapshotIdentityCounts() {return asyncTransfer==null ? new long[4] : asyncTransfer.identityCounts();}
    public boolean earlyFrameIdentity() {return asyncTransfer!=null&&asyncTransfer.earlyIdentity();}
    public long[] snapshotFrameEvents(Integer id) {return asyncTransfer==null ? null : asyncTransfer.frameEvents(id);}
    public long[] snapshotCopiedFrameEvents(Integer id) {return asyncTransfer==null ? null : asyncTransfer.copiedFrameEvents(id);}
    public long awaitPublication(long observed,long deadline) throws InterruptedException {
        return org.gk3hd.standalone.BorrowedPresentFrames.awaitPublication(server,observed,deadline);
    }
}
