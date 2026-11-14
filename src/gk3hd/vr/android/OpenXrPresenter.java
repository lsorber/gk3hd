package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.GLES30;
import android.util.Log;
import com.winlator.StandaloneGameActivity;
import java.util.concurrent.TimeUnit;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Opt-in native Android OpenXR display and physical controller path. */
public final class OpenXrPresenter implements XrPresenter {
    private final Activity activity;
    private final NativeSurfaceView view;
    private final Source source;
    private final FrameObserver observer;
    private final boolean repeatWorld;
    private final java.util.function.BooleanSupplier outputTarget=this::acquireOutput;
    private long submittedSnapshot,submittedSerial,acquireBegin,acquireEnd;
    private boolean outputAcquired;
    private final NativeSessionReport report;
    private final int[] size=new int[2];
    private final float[] poses=new float[29];
    private final long[] state=new long[NativeOpenXr.FRAME_STATE_SIZE];
    private final float[] hands=new float[36];
    private final int[] handState=new int[6];
    private final FramePoses<NativeOpenXr.Frame> frames=new FramePoses<>();
    private final GraphicsRetirement retirement=new GraphicsRetirement();
    private final int firstId=new java.security.SecureRandom().nextInt();
    private long host;
    private int frame;
    private volatile boolean paused,closing;
    private boolean attached,firstTracked,firstRendered;
    public OpenXrPresenter(Activity activity,NativeSurfaceView view,Source source) throws Exception {
        this.activity=activity;this.view=view;this.source=source;
        boolean debugGraphics=(activity.getApplicationInfo().flags&android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0&&
            !activity.getIntent().getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false);
        repeatWorld=debugGraphics&&
            activity.getIntent().getBooleanExtra("gk3hd_test_repeat_world",false);
        report=new NativeSessionReport(activity.getFilesDir(),"openxr",
            activity.getIntent().getStringExtra("gk3hd_observation_token"),
            activity.getIntent().getStringExtra("gk3hd_frame_session"));
        if(activity instanceof StandaloneGameActivity)
            report.onFirstFocusedGame(((StandaloneGameActivity)activity).rendererRecoveryCompletion());
        checkpoint("created",false,null);
        try {
            EyeResolution request=EyeResolution.requested(activity.getIntent(),debugGraphics);
            host=NativeOpenXr.create(activity,request.width,request.height);
            NativeOpenXr.dimensions(host,size);source.configure(size[0],size[1]);source.linearOutput(true);
            report.configured(size[0],size[1],request.source);checkpoint("configured",false,null);
            observer=FrameObserver.open(activity);
        }
        catch(Exception|LinkageError failure) {
            if(host!=0)try {NativeOpenXr.close(host);host=0;}
                catch(Exception|LinkageError cleanup){failure.addSuppressed(cleanup);}
            try {source.close();}
            catch(Exception|LinkageError cleanup){failure.addSuppressed(cleanup);}
            checkpoint("initialization_failed",host==0,failure);throw failure;
        }
        Log.i("GK3HDOpenXR","Native presenter selected explicitly; runtime/headset qualification remains open");
    }
    @Override public void onSurfaceCreated(GL10 gl,EGLConfig config) {
        try {
            frames.clear();submittedSnapshot=0;
            source.onSurfaceCreated(gl,config);
            NativeOpenXr.attach(host);attached=true;view.setExternalPresentation(true);
        } catch(Exception failure) {fail(failure,false);}
    }
    @Override public void onSurfaceChanged(GL10 gl,int width,int height) {source.onSurfaceChanged(gl,size[0]*2,size[1]);}
    @Override public void onDrawFrame(GL10 gl) {
        if(closing||paused)return;
        boolean open=false;
        try {
            if(!attached) {NativeOpenXr.attach(host);attached=true;view.setExternalPresentation(true);}
            long[] times=observer==null?null:new long[9];
            if(times!=null)times[0]=System.nanoTime();
            if(!NativeOpenXr.next(host,poses,state)) {
                submittedSnapshot=0;
                source.moviePresentation(false);
                if(report.withoutSample())checkpoint("state_changed",false,null);
                if(observer!=null)observer.input(XrInput.EMPTY,false,0);
                if(state[0]==NativeOpenXr.SESSION_LOST)throw new NativeOpenXr.SessionLost();
                if(state[0]==NativeOpenXr.INSTANCE_LOST)throw new NativeOpenXr.InstanceLost();
                if(state[0]==NativeOpenXr.SESSION_EXIT) {
                    closing=true;
                    checkpoint("runtime_exit",false,null);
                    Log.i("GK3HDOpenXR","Runtime requested XR exit");
                    activity.runOnUiThread(activity::finish);
                    return;
                }
                source.serviceFrame(gl);
                android.os.SystemClock.sleep(5);
                return;
            }
            open=true;
            long sampled=System.nanoTime();
            if(times!=null)times[1]=sampled;
            NativeOpenXr.Frame sample=new NativeOpenXr.Frame(poses,state);
            source.moviePresentation(sample.focused&&sample.shouldRender&&(sample.flags&3)==3);
            source.trackingEpoch(sample.epoch);source.focused(sample.focused);
            if(report.sampled(sample.flags,sample.focused,sample.shouldRender))checkpoint("state_changed",false,null);
            if(!firstTracked&&(sample.flags&3)==3) {
                firstTracked=true;Log.i("GK3HDOpenXR","First located native stereo frame; focused="+sample.focused);
                checkpoint("located",false,null);
            }
            frames.beginEpoch(sample.epoch);
            frames.focused(sample.focused);
            int id=firstId+frame++;
            if(observer!=null)observer.sampled(id,sampled,sample.shouldRender?sample.flags:0);
            float hz=1_000_000_000f/sample.period;
            NativeOpenXr.controllers(host,hands,handState);
            XrInput inputs=OpenXrControllerSample.decode(hands,handState);
            boolean inputCurrent=sample.shouldRender&&(sample.flags&3)==3&&frames.inputsCurrent(sample.time);
            if(!inputCurrent)inputs=XrInput.EMPTY;
            if(observer!=null)inputs=observer.input(inputs,inputCurrent&&sample.focused,sample.flags);
            if(sample.views==null) {
                source.tracking(sample.head,sample.flags,sample.ipd,sample.fovX,sample.fovY,hz,id,inputs);
            } else {
                source.tracking(sample.head,sample.flags,sample.ipd,sample.fovX,sample.fovY,hz,id,inputs,sample.views);
            }
            // Native history expires against predicted display time. Use that
            // same timeline for matching, rather than callback-arrival time.
            frames.remember(id,sample,sample.shouldRender?sample.flags:0,sample.time,sampled);
            if(times!=null)times[2]=System.nanoTime();
            source.serviceFrame(gl);
            if(times!=null)times[3]=System.nanoTime();
            FramePoses.Sample<NativeOpenXr.Frame> rendered=null;
            long snapshot=0;
            boolean sourceAvailable=false;
            Integer sourceFrameId=null;
            acquireBegin=acquireEnd=0;outputAcquired=false;
            if(sample.shouldRender&&(sample.flags&3)==3) {
                // A loading or withdrawn source ends this frame without a layer.
                sourceAvailable=source.hasStereoFrame();
                if(!sourceAvailable) frames.matchImage(null,0,sample.time);
            }
            if(sourceAvailable) {
                int[] previous=new int[1];GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,previous,0);
                // Native focus can be lost and regained between Java frames.
                long retained=repeatWorld&&sample.reusableSerial==submittedSerial?submittedSnapshot:0;
                try {
                    if(repeatWorld) {
                        if(times!=null)times[4]=System.nanoTime();
                        if(source.drawFrame(gl,retained,outputTarget))sourceFrameId=source.renderedFrameId();
                    } else {
                        acquireOutput();
                        if(times!=null)times[4]=System.nanoTime();
                        source.drawFrame(gl,0);
                        sourceFrameId=source.renderedFrameId();
                    }
                    snapshot=sourceFrameId==null?0:source.renderedSnapshot();
                    rendered=frames.matchImageSample(sourceFrameId,snapshot,sample.time);
                    if(rendered!=null&&!outputAcquired&&
                       (retained==0||snapshot!=retained||!source.renderedOutputUnchanged()))
                        throw new IllegalStateException("Unowned unchanged native output");
                    if(observer!=null&&sample.focused&&outputAcquired&&rendered!=null)
                        observer.boundStereo(size[0],size[1],sourceFrameId,snapshot);
                    if(rendered!=null&&!firstRendered) {
                        firstRendered=true;Log.i("GK3HDOpenXR","First matched source stereo image id="+
                            sourceFrameId+" nativeSerial="+rendered.pose.serial);
                    }
                } finally {GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,previous[0]);}
            }
            if(times!=null) {
                if(times[4]==0)times[4]=System.nanoTime();
                times[5]=System.nanoTime();times[6]=times[5];times[7]=times[5];
            }
            boolean stereoSubmitted=rendered!=null&&!outputAcquired ? NativeOpenXr.repeat(host,rendered.pose.serial) :
                NativeOpenXr.end(host,rendered==null?0:rendered.pose.serial);
            open=false;
            submittedSnapshot=stereoSubmitted&&sample.focused?snapshot:0;
            submittedSerial=submittedSnapshot==0?0:rendered.pose.serial;
            NativeSessionReport.Output output=stereoSubmitted ? NativeSessionReport.Output.STEREO :
                rendered!=null ? NativeSessionReport.Output.NO_LAYER_SUBMITTED :
                NativeSessionReport.Output.missing(sourceAvailable,sourceFrameId);
            boolean milestone=report.submitted(output,stereoSubmitted?snapshot:0,
                rendered==null?NativeSessionReport.UNKNOWN_POSE_TIME:rendered.observed);
            if(times!=null) {
                times[8]=System.nanoTime();
                observer.nativeFrame(frame-1,sample.serial,sample.epoch,sample.time,sample.period,
                    sample.flags,sample.shouldRender,sample.focused,acquireBegin,acquireEnd,id);
                observer.frame(source,frame-1,stereoSubmitted?sourceFrameId:null,
                    stereoSubmitted?snapshot:0,times,false);
            }
            if(milestone)checkpoint("submitting",false,null);
        } catch(Exception failure) {fail(failure,open);}
    }
    private boolean acquireOutput() {
        if(outputAcquired)return true;
        if(observer!=null)acquireBegin=System.nanoTime();
        int target=NativeOpenXr.acquire(host);
        if(observer!=null)acquireEnd=System.nanoTime();
        if(target==0)throw new RendererRecovery.StereoTimeout("OpenXR swapchain image");
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,target);
        outputAcquired=true;return true;
    }
    private void requestRecovery() {
        if(activity instanceof StandaloneGameActivity)
            ((StandaloneGameActivity)activity).requestRendererRecovery();
    }
    private void fail(Exception failure,boolean frameOpen) {
        closing=true;
        requestRecovery();
        if(frameOpen)try {NativeOpenXr.end(host,0);}
            catch(Exception cleanup){failure.addSuppressed(cleanup);}
        if(host!=0)try {NativeOpenXr.close(host);host=0;attached=false;}
            catch(Exception cleanup){failure.addSuppressed(cleanup);}
        view.setExternalPresentation(false);
        checkpoint("failed",host==0,failure);
        Log.e("GK3HDOpenXR","Native presenter failed",failure);activity.runOnUiThread(activity::finish);
    }
    @Override public void graphicsStalled(NativeDrawProgress.Stall stall,long observed) throws java.io.IOException {
        report.graphicsStalled(stall,observed);
    }
    @Override public void graphicsAbandoned() {requestRecovery();}
    private void checkpoint(String phase,boolean ended,Throwable failure) {
        try {report.write(phase,ended,failure);}
        catch(Exception error){Log.e("GK3HDOpenXR","Session report failed",error);}
    }
    @Override public void pause() {
        source.focused(false);
        paused=true;frames.clear();
        view.queueEvent(()-> {
            submittedSnapshot=0;
            try {if(attached){NativeOpenXr.detach(host);attached=false;}}
            catch(Exception failure){fail(failure,false);}
            finally {
                view.setExternalPresentation(false);
                checkpoint("paused",!attached,null);
                try {if(observer!=null)observer.checkpoint();}
                catch(Exception failure){Log.e("GK3HDOpenXR","Presentation timing checkpoint failed",failure);}
            }
        });
    }
    @Override public void resume() {frames.clear();paused=false;}
    @Override public void prepareGuest() {
        try {source.configure(size[0],size[1]);}catch(Exception failure){throw new IllegalStateException("Native guest metadata failed",failure);}
    }
    @Override public void renderFailed(Throwable failure) {
        try {
            requestRecovery();
            checkpoint("failed",false,failure);
        } finally {destroy();}
    }
    @Override public void destroy() {
        closing=true;
        Runnable close=()-> {try {source.close();}
            catch(Exception failure){Log.e("GK3HDOpenXR","Stereo source cleanup failed",failure);}
            try {if(host!=0){NativeOpenXr.close(host);host=0;attached=false;}}
            catch(Exception failure){Log.e("GK3HDOpenXR","Native host cleanup failed",failure);}finally{
                checkpoint("closed",host==0,null);
                try {if(observer!=null)observer.close();}
                catch(Exception failure){Log.e("GK3HDOpenXR","Final presentation timing export failed",failure);}
            }};
        Runnable once=()->retirement.run(close);
        if(!view.queueRetirement(once))return;
        try {if(!retirement.await(3,TimeUnit.SECONDS))Log.e("GK3HDOpenXR","Native host cleanup not confirmed before graphics shutdown");}
        catch(InterruptedException failure){Thread.currentThread().interrupt();}
    }
}
