package org.gk3hd.standalone;

import android.app.Activity;
import android.content.Context;
import android.opengl.GLES30;
import android.opengl.GLSurfaceView;
import android.os.Process;
import android.util.Log;
import android.view.Surface;
import com.winlator.StandaloneGameActivity;
import java.lang.reflect.Array;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Crystal device adapter. Consumes a GPU side-by-side frame, not a CPU screenshot. */
public final class PimaxPresenter implements XrPresenter {
    private final Activity activity;
    private final NativeSurfaceView view;
    private final Source source;
    private final Class<?> api;
    private final Object outer, service, device;
    private final int[] textures=new int[3], buffers=new int[3];
    private final OutputCompletion outputCompletion=new OutputCompletion(3);
    private final boolean finishEveryFrame;
    private final boolean reuseWorldOutput;
    private final FrameObserver observer;
    private final NativeSessionReport report;
    private final TrackingWorker trackingWorker;
    private final Object trackingLock=new Object();
    private TrackingSample latestTracking;
    private ControllerSample latestControllers;
    private long inputEpoch;
    private int trackingSequence;
    private volatile boolean connected, closing, inputFocused;
    private boolean initialized, waitingForGuest, failed;
    private volatile boolean started;
    private final int runtimeEyeWidth,runtimeEyeHeight,eyeWidth,eyeHeight;
    private int frame;
    private long observedDraws;
    private int distinctSources;
    private Integer lastSourceId;
    private long startNanos;
    private long sessionEpoch;
    private float ipd;
    private StereoViews opticalViews;
    private PimaxControllers controllers;
    private final FramePoses<Object> poses=new FramePoses<>();
    private final GraphicsRetirement retirement=new GraphicsRetirement();
    // Disjoint session IDs prevent cached X-window pixels matching a new session.
    private final int firstFrameId=new java.security.SecureRandom().nextInt();

    private static final class TrackingSample {
        final Object pose;final float[] head;final int flags,id;final long sampled;
        TrackingSample(Object pose,float[] head,int flags,int id,long sampled) {
            this.pose=pose;this.head=head;this.flags=flags;this.id=id;this.sampled=sampled;
        }
    }
    private static final class ControllerSample {
        final XrInput input;final long sampled,epoch;
        ControllerSample(XrInput input,long sampled,long epoch) {this.input=input;this.sampled=sampled;this.epoch=epoch;}
    }

    // All vendor symbols are public firmware API, discovered without shipping vendor binaries.
    public PimaxPresenter(Activity activity, NativeSurfaceView view, Source source) throws Exception {
        boolean debug=(activity.getApplicationInfo().flags&android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)!=0;
        boolean ordinaryRestart=activity.getIntent().getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false);
        boolean debugGraphics=debug&&!ordinaryRestart;
        this.activity=activity;this.view=view;this.source=source;
        report=new NativeSessionReport(activity.getFilesDir(),"pimax",
            activity.getIntent().getStringExtra("gk3hd_observation_token"),
            activity.getIntent().getStringExtra("gk3hd_frame_session"));
        if(activity instanceof StandaloneGameActivity)
            report.onFirstFocusedGame(((StandaloneGameActivity)activity).rendererRecoveryCompletion());
        checkpoint("created",false,null);
        Object openedService=null;
        FrameObserver openedObserver=null;
        TrackingWorker openedWorker=null;
        boolean vsyncRequested=false;
        try {
            EyeResolution request=EyeResolution.requested(activity.getIntent(),debugGraphics);
            if((request.width!=0||request.height!=0)&&!supportedEyeSize(request.width,request.height))
                throw new IllegalArgumentException("Unsupported requested eye dimensions: "+request.width+"x"+request.height);
            finishEveryFrame=debugGraphics&&activity.getIntent().getBooleanExtra("gk3hd_test_finish_every_frame",false);
            reuseWorldOutput=debugGraphics&&!finishEveryFrame&&
                activity.getIntent().getBooleanExtra("gk3hd_test_pimax_reuse_output",false);
            boolean fastCopy=activity.getIntent().getBooleanExtra("gk3hd_experimental_eye_copy",false)||
                (debug&&activity.getIntent().getBooleanExtra("gk3hd_test_pimax_eye_blit",false));
            if(fastCopy&&!ordinaryRestart) {
                source.preferPaddedEyeBlit();
                Log.i("GK3HDXR","Crystal fast eye copy requested");
            }
            openedObserver=FrameObserver.open(activity);
            observer=openedObserver;
            api=Class.forName("com.pimax.pxrapi.PxrApi");
            outer=api.getConstructor().newInstance();
            call("sxrInitialize",new Class<?>[]{Context.class},activity);
            initialized=true;
            device=call("sxrGetDeviceInfo",new Class<?>[]{});
            runtimeEyeWidth=((Number)get(device,"targetEyeWidthPixels")).intValue();
            runtimeEyeHeight=((Number)get(device,"targetEyeHeightPixels")).intValue();
            if(!supportedEyeSize(runtimeEyeWidth,runtimeEyeHeight))
                throw new IllegalStateException("Unsupported recommended eye dimensions: "+runtimeEyeWidth+"x"+runtimeEyeHeight);
            eyeWidth=request.width==0?runtimeEyeWidth:request.width;
            eyeHeight=request.height==0?runtimeEyeHeight:request.height;
            source.configure(eyeWidth,eyeHeight);
            report.configured(eyeWidth,eyeHeight,request.source);checkpoint("configured",false,null);
            Class<?> client=Class.forName("com.pimax.pxrapi.PvrServiceClient");
            openedService=client.getConstructor(Context.class,long.class).newInstance(activity,0L);
            service=openedService;
            client.getMethod("Connect").invoke(service);
            client.getMethod("ExecuteOnConnection",Runnable.class).invoke(service,(Runnable)this::readIpd);
            // Start the dormant reader before Begin can change the render thread's
            // native scheduling policy. It samples only after explicit activation.
            if(debugGraphics&&activity.getIntent().getBooleanExtra("gk3hd_test_independent_tracking",false))
                openedWorker=new TrackingWorker(360);
            trackingWorker=openedWorker;
            vsyncRequested=true;
            call("startVsync",new Class<?>[]{Context.class},activity);
        } catch(Exception|LinkageError failure) {
            synchronized(trackingLock) {closing=true;}
            if(openedWorker!=null) cleanup(openedWorker::close,failure);
            if(openedObserver!=null) cleanup(openedObserver::close,failure);
            if(vsyncRequested) cleanup(()->call("stopVsync",new Class<?>[]{Context.class},activity),failure);
            if(initialized) cleanup(()->call("sxrShutdown",new Class<?>[]{}),failure);
            if(openedService!=null) {
                Object client=openedService;
                cleanup(()->client.getClass().getMethod("Disconnect").invoke(client),failure);
            }
            cleanup(source::close,failure);
            checkpoint("initialization_failed",failure.getSuppressed().length==0,failure);
            throw failure;
        }
        Log.i("GK3HDXR","Crystal adapter initialized; eye="+eyeWidth+"x"+eyeHeight+
            "; recommended="+runtimeEyeWidth+"x"+runtimeEyeHeight);
    }

    private static boolean supportedEyeSize(int width,int height) {
        return width>0&&height>0&&width<=4096&&height<=4096;
    }

    private void readIpd() {
        synchronized(trackingLock) {
            if(closing)return;
            try {
                // The firmware returns the one-eye offset in meters.
                float halfMeters=((Number)service.getClass().getMethod("GetIpdNumber").invoke(service)).floatValue();
                ipd=PimaxTracking.fullIpd(halfMeters);
                Log.i("GK3HDXR","device IPD="+ipd+" m");
                connected=true;
            } catch(Exception error) {Log.e("GK3HDXR","Device IPD query failed",error);activity.runOnUiThread(activity::finish);}
        }
    }

    private interface ShutdownStep {void run() throws Exception;}
    private static void cleanup(ShutdownStep step,Throwable failure) {
        try {step.run();}
        catch(Exception|LinkageError error) {failure.addSuppressed(error);}
    }

    private Class<?> nested(String name) throws Exception {return Class.forName(api.getName()+"$"+name);}
    private Object struct(String name) throws Exception {return nested(name).getConstructor(api).newInstance(outer);}
    private Object value(String type,String name) throws Exception {return nested(type).getField(name).get(null);}
    private Object call(String name,Class<?>[] signature,Object... args) throws Exception {
        return api.getMethod(name,signature).invoke(null,args);
    }
    private static Object get(Object object,String name) throws Exception {return object.getClass().getField(name).get(object);}
    private static void set(Object object,String name,Object value) throws Exception {object.getClass().getField(name).set(object,value);}
    private static float[] frustum(Object value) throws Exception {
        Object position=get(value,"position"),rotation=get(value,"rotation");
        return new float[]{number(value,"left"),number(value,"right"),number(value,"top"),
            number(value,"bottom"),number(value,"near"),number(position,"x"),number(position,"y"),
            number(position,"z"),number(rotation,"x"),number(rotation,"y"),number(rotation,"z"),number(rotation,"w")};
    }

    private Object snapshot(Object source) throws Exception {
        Object result=struct("sxrHeadPoseState"),head=struct("sxrHeadPose"),position=struct("sxrVector3"),rotation=struct("sxrQuaternion");
        for(String name:new String[]{"poseStatus","poseTimeStampNs","poseFetchTimeNs","expectedDisplayTimeNs"})
            set(result,name,get(source,name));
        Object original=get(source,"pose");
        for(String name:new String[]{"x","y","z"}) {
            set(position,name,get(get(original,"position"),name));set(rotation,name,get(get(original,"rotation"),name));
        }
        set(rotation,"w",get(get(original,"rotation"),"w"));
        set(head,"position",position);set(head,"rotation",rotation);set(result,"pose",head);
        return result;
    }

    @Override public void onSurfaceCreated(GL10 gl,EGLConfig config) {
        synchronized(trackingLock) {
            poses.clear();latestTracking=null;latestControllers=null;inputEpoch++;
        }
        source.onSurfaceCreated(gl,config);
        GLES30.glGenTextures(3,textures,0);GLES30.glGenFramebuffers(3,buffers,0);
        outputCompletion.reset();
        for(int i=0;i<3;i++) {
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[i]);
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MIN_FILTER,GLES30.GL_LINEAR);
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MAG_FILTER,GLES30.GL_LINEAR);
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_WRAP_S,GLES30.GL_CLAMP_TO_EDGE);
            GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_WRAP_T,GLES30.GL_CLAMP_TO_EDGE);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,eyeWidth*2,eyeHeight,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,buffers[i]);
            GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[i],0);
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Crystal stereo framebuffer incomplete");
        }
        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,0);
    }

    @Override public void onSurfaceChanged(GL10 gl,int width,int height) {
        source.onSurfaceChanged(gl,eyeWidth*2,eyeHeight);
    }

    private void bindOutput(int slot) {
        GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,buffers[slot]);
        GLES30.glViewport(0,0,eyeWidth*2,eyeHeight);
        GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
        GLES30.glClearColor(0,0,0,1);
    }

    @Override public void onDrawFrame(GL10 gl) {
        if(closing) return;
        long draw=observer==null ? 0 : ++observedDraws;
        try {
            if(!connected) {
                // Image ownership must still progress while the headset service connects.
                source.serviceFrame(gl);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);return;
            }
            if(!started&&!source.readyForSession()) {
                // Cold Wine startup needs no XR session. The runtime's retrying
                // hello arrives on an independent receiver, before it waits for
                // the first real pose. Do not wait for an image or synthesize one.
                if(!waitingForGuest) {waitingForGuest=true;Log.i("GK3HDXR","Waiting for guest runtime before Crystal session");}
                source.serviceFrame(gl);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);return;
            }
            if(!started) {
                Log.i("GK3HDXR","Guest ready; beginning Crystal session");
                Object begin=nested("sxrBeginParams").getConstructor(api,Surface.class).newInstance(outer,view.getHolder().getSurface());
                set(begin,"mainThreadId",Process.myPid());
                call("sxrBeginXr",new Class<?>[]{Context.class,nested("sxrBeginParams")},activity,begin);
                started=true;view.setExternalPresentation(true);
                source.trackingEpoch(++sessionEpoch);
                // Record the vendor request, not a promise of applied clocks.
                // The off-head fixture never begins this compositor session.
                Log.i("GK3HDXR","Crystal session performance request CPU="+get(begin,"cpuPerfLevel")+
                    " GPU="+get(begin,"gpuPerfLevel"));
                // Initialize/Begin do not request head tracking on this firmware.
                // Mode zero masks even real sensor data to unavailable. Request
                // the advertised normal rotation + position modes, not valid
                // pose bits, and keep using the firmware's actual pose status.
                int rotationMode=((Number)nested("sxrTrackingMode").getMethod("getTrackingMode")
                    .invoke(value("sxrTrackingMode","kTrackingRotation"))).intValue();
                int positionMode=((Number)nested("sxrTrackingMode").getMethod("getTrackingMode")
                    .invoke(value("sxrTrackingMode","kTrackingPosition"))).intValue();
                int requested=rotationMode|positionMode;
                int supported=((Number)call("sxrGetSupportedTrackingModes",new Class<?>[]{})).intValue();
                if((supported&requested)!=requested) throw new IllegalStateException("Crystal rotation/position tracking is not supported");
                call("sxrSetTrackingMode",new Class<?>[]{int.class},requested);
                Log.i("GK3HDXR","requested tracking mode="+requested+" active="+call("sxrGetTrackingMode",new Class<?>[]{}));
                // Query after the compositor and device service are ready, as
                // the vendor display provider does. Never reuse a calibration
                // captured before native session initialization.
                Object calibration=call("sxrGetDeviceInfo",new Class<?>[]{});
                if(number(calibration,"targetEyeWidthPixels")!=runtimeEyeWidth||
                        number(calibration,"targetEyeHeightPixels")!=runtimeEyeHeight)
                    throw new IllegalStateException("Crystal eye dimensions changed during session initialization");
                float[] left=frustum(get(calibration,"leftEyeFrustum")),right=frustum(get(calibration,"rightEyeFrustum"));
                opticalViews=PimaxTracking.stereoViews(left,right);
                Log.i("GK3HDXR","calibrated eye frusta left="+java.util.Arrays.toString(left)+
                    " right="+java.util.Arrays.toString(right));
                controllers=new PimaxControllers((String)call("sxrGetVersion",new Class<?>[]{}));
                startNanos=System.nanoTime();
                if(trackingWorker!=null) {
                    synchronized(trackingLock) {latestControllers=null;latestTracking=null;}
                    // Seed an actual pose before the first compositor submission;
                    // then the independent reader becomes the sole head sampler.
                    sampleTracking();trackingWorker.activate(this::sampleTracking);
                }
            }
            long[] times=observer==null ? null : new long[9];
            if(times!=null)times[0]=System.nanoTime();
            Object pose=null;
            int trackingFlags=0;
            boolean focused;
            long focusEpoch;
            if(trackingWorker==null) {
            long generation=poses.samplingGeneration();
            long nativeSampleBegin=System.nanoTime();
            Object candidate=snapshot(call("sxrGetPredictedHeadPose",new Class<?>[]{float.class},call("sxrGetPredictedDisplayTime",new Class<?>[]{})));
            long observed=System.nanoTime();
            if(times!=null)times[1]=observed;
            if(frame%300==0) Log.i("GK3HDXR","head tracking JavaStatus="+get(candidate,"poseStatus")+
                " nativeStatus="+controllers.nativeHeadStatus()+" mode="+call("sxrGetTrackingMode",new Class<?>[]{})+
                " supported="+call("sxrGetSupportedTrackingModes",new Class<?>[]{})+
                " ageMs="+(android.os.SystemClock.elapsedRealtimeNanos()-((Number)get(candidate,"poseTimeStampNs")).longValue())/1e6);
            java.nio.ByteBuffer hands=controllers.sample();
            XrInput inputs=inputFocused?PimaxControllerSample.decode(hands,android.os.SystemClock.elapsedRealtimeNanos()):XrInput.EMPTY;
            if(frame%300==0) for(int hand=0;hand<2;hand++) {
                int base=hand*272;
                Log.i("GK3HDXR","controller="+hand+" handle="+hands.getInt(base+264)+" connection="+hands.getInt(base+136)+
                    " positionValid="+hands.get(base+140)+" poseStatus="+hands.getInt(base+236)+
                    " locationFlags="+(hand==0 ? inputs.left.flags : inputs.right.flags)+
                    " buttons="+hands.getInt(base+64)+" stick="+hands.getFloat(base+68)+","+hands.getFloat(base+72)+
                    " trigger="+hands.getFloat(base+100)+" grip="+hands.getFloat(base+108)+
                    " ageMs="+(android.os.SystemClock.elapsedRealtimeNanos()-hands.getLong(base+240))/1e6+
                    " nativeXYZ="+hands.getFloat(base+224)+","+hands.getFloat(base+228)+","+hands.getFloat(base+232));
            }
            Object head=get(candidate,"pose"),position=get(head,"position"),rotation=get(head,"rotation");
            float[] coordinates={number(position,"x"),number(position,"y"),number(position,"z"),
                number(rotation,"x"),number(rotation,"y"),number(rotation,"z"),number(rotation,"w")};
            // Forward only the firmware's actual orientation/position status bits.
            // Updating quaternion numbers alone never establish valid tracking.
            int flags=PimaxTracking.locationFlags(((Number)get(candidate,"poseStatus")).intValue());
            int frameId=firstFrameId+frame;
            synchronized(trackingLock) {
                focused=inputFocused;
                focusEpoch=inputEpoch;
                if(!closing&&poses.rememberIfCurrent(generation,frameId,candidate,flags,nativeSampleBegin,observed)) {
                    pose=candidate;trackingFlags=flags;
                    if(observer!=null)observer.sampled(frameId,nativeSampleBegin,flags);
                    boolean inputCurrent=focused&&poses.inputsCurrent(nativeSampleBegin);
                    if(!inputCurrent)inputs=XrInput.EMPTY;
                    if(observer!=null)inputs=observer.input(inputs,inputCurrent,flags);
                    source.tracking(PimaxTracking.headPose(coordinates),flags,ipd,number(device,"targetFovXRad"),number(device,"targetFovYRad"),
                        number(device,"displayRefreshRateHz"),frameId,inputs,opticalViews);
                    if(observer!=null)observer.published(frameId,System.nanoTime());
                }
            }
            } else {
                trackingWorker.checkFailure();
                long controlsEpoch;
                synchronized(trackingLock) {controlsEpoch=inputEpoch;}
                java.nio.ByteBuffer hands=controllers.sample();
                XrInput input=PimaxControllerSample.decode(hands,android.os.SystemClock.elapsedRealtimeNanos());
                synchronized(trackingLock) {
                    focused=inputFocused;
                    focusEpoch=inputEpoch;
                    if(!closing&&controlsEpoch==inputEpoch)latestControllers=new ControllerSample(input,System.nanoTime(),controlsEpoch);
                    TrackingSample sample=latestTracking;
                    if(!closing&&sample!=null) {
                        pose=sample.pose;trackingFlags=sample.flags;
                        // Movies use the same pose ID without sending another input packet.
                        source.stageTracking(sample.head,sample.flags,sample.id,opticalViews);
                    }
                }
                if(times!=null)times[1]=System.nanoTime();
            }
            if(pose==null) {
                // Let the source progress without submitting a revoked pose.
                if(report.withoutSample())checkpoint("state_changed",false,null);
                if(observer!=null)observer.input(XrInput.EMPTY,false,0);
                source.serviceFrame(gl);GLES30.glClearColor(0,0,0,1);
                GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);return;
            }
            if(report.sampled(trackingFlags,focused,true))checkpoint("state_changed",false,null);
            if(times!=null)times[2]=System.nanoTime();
            source.serviceFrame(gl);
            if(times!=null)times[3]=System.nanoTime();
            int writable=reuseWorldOutput?outputCompletion.writableTarget():frame%3;
            int slot=writable;
            boolean reusedPreviousOutput=false;
            if(!reuseWorldOutput)bindOutput(writable);
            // Never label an ordinary desktop, mono mirror or half of it as stereo.
            FramePoses.Sample<Object> renderedPose=null;
            Integer sourceFrameId=null;
            long retainedSnapshot=outputCompletion.retained(slot),snapshot=0;
            if(times!=null)times[4]=System.nanoTime();
            boolean sourceAvailable=source.hasStereoFrame();
            boolean blankUnchanged=!sourceAvailable&&!finishEveryFrame&&outputCompletion.hasCompletedBlank(slot);
            if(sourceAvailable) {
                int previous=reuseWorldOutput?outputCompletion.lastSubmitted():-1;
                boolean[] writeSelected=reuseWorldOutput?new boolean[1]:null;
                if(reuseWorldOutput) {
                    retainedSnapshot=previous<0?0:outputCompletion.retained(previous);
                    if(retainedSnapshot!=0)bindOutput(previous);
                    if(source.drawFrame(gl,retainedSnapshot,()->{
                        bindOutput(writable);
                        writeSelected[0]=true;
                        return true;
                    }))sourceFrameId=source.renderedFrameId();
                } else {
                    source.drawFrame(gl,retainedSnapshot);
                    sourceFrameId=source.renderedFrameId();
                }
                long renderedSnapshot=source.renderedSnapshot();
                renderedPose=poses.matchImageSample(sourceFrameId,renderedSnapshot,System.nanoTime());
                if(reuseWorldOutput&&!writeSelected[0]) {
                    if(renderedPose==null)bindOutput(writable);
                    else {
                        if(retainedSnapshot==0||renderedSnapshot!=retainedSnapshot||!source.renderedOutputUnchanged())
                            throw new IllegalStateException("Unowned unchanged Crystal output");
                        slot=previous;
                        reusedPreviousOutput=true;
                    }
                }
                if(renderedPose!=null)snapshot=renderedSnapshot;
            } else {
                if(reuseWorldOutput)bindOutput(writable);
                poses.matchImage(null,0,System.nanoTime());
            }
            if(renderedPose==null&&!blankUnchanged) {
                GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            }
            else if(renderedPose!=null) {
                if(!sourceFrameId.equals(lastSourceId)) {lastSourceId=sourceFrameId;distinctSources++;}
            }
            if(observer!=null&&focused&&renderedPose!=null)
                observer.boundStereo(eyeWidth,eyeHeight,sourceFrameId,snapshot);
            if(times!=null)times[5]=System.nanoTime();
            Object params=struct("sxrFrameParams");
            set(params,"frameIndex",frame);set(params,"minVsyncs",1);set(params,"headPoseState",renderedPose==null ? pose : renderedPose.pose);
            Object layers=get(params,"renderLayers");
            for(int eye=0;eye<2;eye++) {
                Object layer=struct("sxrRenderLayer");
                set(layer,"imageHandle",textures[slot]);set(layer,"imageType",value("sxrTextureType","kTypeTexture"));
                set(layer,"eyeMask",value("sxrEyeMask",eye==0?"kEyeMaskLeft":"kEyeMaskRight"));
                Object coords=get(layer,"imageCoords");
                set(coords,"LowerLeftPos",new float[]{-1,-1,0,1});set(coords,"LowerRightPos",new float[]{1,-1,0,1});
                set(coords,"UpperLeftPos",new float[]{-1,1,0,1});set(coords,"UpperRightPos",new float[]{1,1,0,1});
                float lo=eye*.5f,hi=lo+.5f;
                set(coords,"LowerUVs",new float[]{lo,0,hi,0});set(coords,"UpperUVs",new float[]{lo,1,hi,1});
                float[] identity=new float[16];android.opengl.Matrix.setIdentityM(identity,0);
                set(coords,"TransformMatrix",identity);Array.set(layers,eye,layer);
            }
            // An exact retained output has no new writes. Its previous write
            // already finished; do not wait for unrelated future source copies.
            // A black clear needs the same completion proof before the slot
            // can be reused while no source draws into it.
            boolean unchanged=renderedPose!=null&&source.renderedOutputUnchanged();
            boolean waited=finishEveryFrame||(!blankUnchanged&&outputCompletion.required(slot,snapshot,unchanged));
            if(times!=null)times[6]=System.nanoTime();
            if(waited) {
                GpuHandoff.awaitOutput();
                if(renderedPose==null)outputCompletion.completedBlank(slot);
                else outputCompletion.completed(slot,snapshot);
            }
            if(times!=null)times[7]=System.nanoTime();
            call("sxrSubmitFrame",new Class<?>[]{Context.class,nested("sxrFrameParams")},activity,params);
            if(reuseWorldOutput)outputCompletion.submitted(slot);
            report.completion(waited);
            if(snapshot>0&&!unchanged)report.gameEyeCopy(source.renderedWithPaddedEyeBlit());
            boolean milestone=report.submitted(renderedPose!=null ? NativeSessionReport.Output.STEREO :
                NativeSessionReport.Output.missing(sourceAvailable,sourceFrameId),snapshot,
                renderedPose==null?NativeSessionReport.UNKNOWN_POSE_TIME:renderedPose.observed);
            if(times!=null) {
                times[8]=System.nanoTime();
                observer.frame(source,frame,renderedPose==null ? null : sourceFrameId,snapshot,times,waited);
                observer.crystalSubmission(frame,draw,focusEpoch,trackingFlags,focused,slot,reusedPreviousOutput);
            }
            if(milestone)checkpoint("submitting",false,null);
            if(renderedPose!=null&&activity.getIntent().getBooleanExtra("gk3hd_observe_native_game",false))
                Class.forName("org.gk3hd.standalone.NativeGameObserver").getMethod("observe",Activity.class,int.class,int.class,int.class,long.class)
                    .invoke(null,activity,eyeWidth,eyeHeight,source.renderedFrameId(),startNanos);
            if(frame%300==0) Log.i("GK3HDXR","submitted="+frame+" matchedStereo="+(renderedPose!=null)+
                " distinctSourceFrames="+distinctSources+
                " poseStatus="+get(pose,"poseStatus")+" glError="+GLES30.glGetError()+
                " elapsed="+(System.nanoTime()-startNanos)/1e9);
            frame++;
        } catch(Exception error) {
            reportFailure(error,!started);
            Log.e("GK3HDXR","Crystal frame failed",error);activity.runOnUiThread(activity::finish);
        }
    }

    @Override public void graphicsStalled(NativeDrawProgress.Stall stall,long observed) throws java.io.IOException {
        report.graphicsStalled(stall,observed);
    }
    @Override public void graphicsAbandoned() {requestRecovery();}

    private void checkpoint(String phase,boolean ended,Throwable failure) {
        try {report.write(phase,ended,failure);}
        catch(Exception error){Log.e("GK3HDXR","Session report failed",error);}
    }

    private void sampleTracking()throws Exception {
        long generation=poses.samplingGeneration();
        long sampled=System.nanoTime();
        Object pose=snapshot(call("sxrGetPredictedHeadPose",new Class<?>[]{float.class},call("sxrGetPredictedDisplayTime",new Class<?>[]{})));
        long observed=System.nanoTime();
        Object head=get(pose,"pose"),position=get(head,"position"),rotation=get(head,"rotation");
        float[] coordinates={number(position,"x"),number(position,"y"),number(position,"z"),
            number(rotation,"x"),number(rotation,"y"),number(rotation,"z"),number(rotation,"w")};
        int flags=PimaxTracking.locationFlags(((Number)get(pose,"poseStatus")).intValue());
        float[] nativeHead=PimaxTracking.headPose(coordinates);
        synchronized(trackingLock) {
            if(closing||!started)return;
            int id=firstFrameId+trackingSequence;
            if(!poses.rememberIfCurrent(generation,id,pose,flags,sampled,observed))return;
            trackingSequence++;
            if(observer!=null)observer.sampled(id,sampled,flags);
            ControllerSample controls=latestControllers;long now=System.nanoTime();
            XrInput input=inputFocused&&controls!=null&&controls.epoch==inputEpoch&&
                now>=controls.sampled&&now-controls.sampled<=250_000_000L&&poses.inputsCurrent(now)?controls.input:XrInput.EMPTY;
            source.publishTracking(nativeHead,flags,ipd,number(device,"targetFovXRad"),number(device,"targetFovYRad"),
                number(device,"displayRefreshRateHz"),id,input,opticalViews);
            if(observer!=null)observer.published(id,System.nanoTime());
            latestTracking=new TrackingSample(pose,nativeHead,flags,id,sampled);
        }
    }

    // Must run before NativeSurfaceView pauses, with the render context still current.
    public void pause() {
        synchronized(trackingLock) {
            closing=true;poses.clear();latestTracking=null;latestControllers=null;inputEpoch++;
            source.focused(false);
        }
        view.queueEvent(()-> {
            if(trackingWorker!=null) {
                // A timeout deliberately prevents SDK teardown while a callback
                // still uses it; it must never become an apparent clean pause.
                trackingWorker.deactivate();
            }
            // A resumed session registers fresh handles. Retire these before
            // ending XR rather than leaking registrations on each app switch.
            if(controllers!=null) {controllers.close();controllers=null;}
            try {if(started) call("sxrEndXr",new Class<?>[]{});started=false;}
            catch(Exception|LinkageError error) {
                reportFailure(error,false);
                Log.e("GK3HDXR","Crystal end failed",error);
                activity.runOnUiThread(activity::finish);
                return;
            }
            try {if(observer!=null)observer.checkpoint();}
            catch(Exception error) {Log.e("GK3HDXR","Presentation timing export failed",error);}
            view.setExternalPresentation(false);
            Log.i("GK3HDXR","Crystal session ended; submitted="+frame);
            checkpoint("paused",!started,null);
        });
    }
    public void resume() {
        synchronized(trackingLock) {
            if(failed)return;
            poses.clear();latestTracking=null;latestControllers=null;inputEpoch++;
            closing=false;source.focused(inputFocused);
        }
    }
    @Override public boolean rendersWhileVisible() {return true;}
    @Override public void inputFocused(boolean focused) {
        synchronized(trackingLock) {
            long generation=poses.samplingGeneration();
            inputFocused=focused;inputEpoch++;latestControllers=null;
            poses.focused(focused);
            if(generation!=poses.samplingGeneration())latestTracking=null;
            source.focused(focused&&!closing);
        }
    }
    public void prepareGuest() {
        try {source.configure(eyeWidth,eyeHeight);}
        catch(Exception error) {throw new IllegalStateException("Guest XR metadata failed",error);}
    }
    private static float number(Object object,String name) throws Exception {return ((Number)get(object,name)).floatValue();}
    @Override public void renderFailed(Throwable failure) {
        try {reportFailure(failure,false);}
        finally {destroy();}
    }
    private void reportFailure(Throwable failure,boolean ended) {
        synchronized(trackingLock) {
            failed=true;closing=true;
        }
        requestRecovery();
        checkpoint("failed",ended,failure);
    }
    private void requestRecovery() {
        if(activity instanceof StandaloneGameActivity)
            ((StandaloneGameActivity)activity).requestRendererRecovery();
    }
    public void destroy() {
        closing=true;
        // A callback already in flight must finish using the bridge before
        // its socket and GPU resources are retired. SDK cleanup needs this
        // same current graphics context, including direct destruction.
        Runnable close=()-> {
            if(trackingWorker!=null)trackingWorker.close();
            try {source.close();}
            catch(Exception error) {Log.e("GK3HDXR","Stereo source cleanup failed",error);}
            try {if(observer!=null)observer.close();}
            catch(Exception error) {Log.e("GK3HDXR","Final presentation timing export failed",error);}
            try {
                if(controllers!=null) {controllers.close();controllers=null;}
                if(started) {call("sxrEndXr",new Class<?>[]{});started=false;}
                if(initialized) {call("stopVsync",new Class<?>[]{Context.class},activity);call("sxrShutdown",new Class<?>[]{});initialized=false;}
                service.getClass().getMethod("Disconnect").invoke(service);
            } catch(Exception|LinkageError error) {
                checkpoint("close_failed",false,error);
                Log.e("GK3HDXR","Crystal shutdown failed",error);
                return;
            }
            checkpoint("closed",true,null);
        };
        Runnable once=()->retirement.run(close);
        if(!view.queueRetirement(once))return;
        try {
            if(!retirement.await(3,java.util.concurrent.TimeUnit.SECONDS))
                Log.e("GK3HDXR","Crystal cleanup not confirmed before graphics shutdown");
        } catch(InterruptedException error) {Thread.currentThread().interrupt();}
    }
}
