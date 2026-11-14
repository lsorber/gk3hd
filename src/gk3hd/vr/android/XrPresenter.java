package org.gk3hd.standalone;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.opengl.GLSurfaceView;
import javax.microedition.khronos.opengles.GL10;

/** Host lifecycle and GPU source contract, independent of a headset vendor. */
public interface XrPresenter extends GLSurfaceView.Renderer {
    /** A one-launch override leaves the headset's optical calibration unchanged. */
    final class EyeResolution {
        final int width,height;
        final NativeSessionReport.ResolutionSource source;

        private EyeResolution(int width,int height,NativeSessionReport.ResolutionSource source) {
            this.width=width;this.height=height;this.source=source;
        }

        static EyeResolution requested(Intent intent,boolean debug) {
            if(!intent.getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false)) {
                String value=intent.getStringExtra("gk3hd_eye_resolution");
                if(value!=null)return parse(value,NativeSessionReport.ResolutionSource.LAUNCH_OVERRIDE);
                if(debug) {
                    int width=intent.getIntExtra("gk3hd_test_eye",0);
                    int height=intent.getIntExtra("gk3hd_test_eye_height",width);
                    if(width!=0||height!=0)
                        return new EyeResolution(width,height,NativeSessionReport.ResolutionSource.FIXTURE_OVERRIDE);
                }
                String profile=intent.getStringExtra(XrRuntimeSelection.HEADSET_EYE_RESOLUTION);
                if(profile!=null)return parse(profile,NativeSessionReport.ResolutionSource.HEADSET_DEFAULT);
            }
            return new EyeResolution(0,0,NativeSessionReport.ResolutionSource.RUNTIME_RECOMMENDED);
        }

        private static EyeResolution parse(String value,NativeSessionReport.ResolutionSource source) {
            if(!value.matches("[1-9][0-9]{0,3}x[1-9][0-9]{0,3}"))
                throw new IllegalArgumentException("Invalid per-eye resolution");
            String[] dimensions=value.split("x");
            int width=Integer.parseInt(dimensions[0]),height=Integer.parseInt(dimensions[1]);
            if(width>4096||height>4096)
                throw new IllegalArgumentException("Per-eye resolution exceeds 4096 pixels per axis");
            return new EyeResolution(width,height,source);
        }
    }

    final class InitializationFailure extends IllegalStateException {
        private static final long serialVersionUID=1L;

        public InitializationFailure(Throwable cause) {
            super("Headset compositor initialization failed",cause);
        }
    }

    /** Optional bounded development observer. Input callbacks may use a reader thread. */
    interface FrameObserver {
        static FrameObserver open(Activity activity) throws ReflectiveOperationException {
            if((activity.getApplicationInfo().flags&ApplicationInfo.FLAG_DEBUGGABLE)==0)return null;
            Intent intent=activity.getIntent();
            boolean exploration=!intent.getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false)&&
                intent.getBooleanExtra("gk3hd_test_native_exploration",false);
            if(!exploration&&!intent.getBooleanExtra("gk3hd_test_presenter_timing",false))return null;
            String observer=exploration ? "NativeExplorationFlow" : "NativeFrameTiming";
            return (FrameObserver)Class.forName("org.gk3hd.standalone."+observer)
                .getConstructor(Activity.class).newInstance(activity);
        }
        default XrInput input(XrInput physical,boolean eligible,int flags) throws Exception {return physical;}
        void sampled(int id,long now,int flags);
        default void published(int id,long now) {}
        /** The presenter still owns a bound stereo draw target here. */
        default void boundStereo(int width,int height,int id,long snapshot) throws Exception {}
        void frame(Source source,int tick,Integer id,long snapshot,long[] times,boolean waited) throws Exception;
        default void crystalSubmission(int tick,long draw,long focusEpoch,int trackingFlags,boolean focused,
                int outputSlot,boolean reusedPreviousOutput) {}
        default void nativeFrame(int tick,long serial,long epoch,long displayTime,long period,
                int flags,boolean render,boolean focused,long acquireBegin,long acquireEnd,int inputPose) {}
        void checkpoint() throws Exception;
        void close() throws Exception;
    }
    interface Source extends GLSurfaceView.Renderer {
        /** Guest startup readiness, independent of pose or image validity. */
        default boolean readyForSession() {return true;}
        boolean hasStereoFrame();
        default Integer renderedFrameId() {return null;}
        /** Nonzero identity of an immutable GPU snapshot, not merely its pose ID. */
        default long renderedSnapshot() {return 0;}
        /** True only if the last draw issued no writes to the unchanged output target. */
        default boolean renderedOutputUnchanged() {return false;}
        /** True only if the most recent draw copied both eyes via the padded blit. */
        default boolean renderedWithPaddedEyeBlit() {return false;}
        /** Exact-image diagnostics only. No CPU pixel capture is required. */
        default long[] snapshotFrameEvents(Integer id) {return null;}
        /** Caller retains an unchanged, same-size output target with this snapshot. */
        default void drawFrame(GL10 gl,long retainedSnapshot) {onDrawFrame(gl);}
        /** Select immutable pixels before acquiring a writable output when supported. */
        default boolean drawFrame(GL10 gl,long retainedSnapshot,java.util.function.BooleanSupplier target) {
            if(!target.getAsBoolean())return false;
            drawFrame(gl,0);return true;
        }
        default void serviceFrame(GL10 gl) throws Exception {}
        default void focused(boolean value) {}
        default void trackingEpoch(long epoch) {}
        default void moviePresentation(boolean eligible) {}
        default void configure(int eyeWidth,int eyeHeight) throws Exception {}
        /** Configure before creating source GL resources. True means an sRGB
         * compositor attachment, false preserves the encoded RGBA8 output.
         */
        default void linearOutput(boolean value) {
            if(value)throw new UnsupportedOperationException("Source does not support linear compositor output");
        }
        /** The presenter owns exact-size, single-sample RGBA8 output targets. */
        default void preferPaddedEyeBlit() {}
        /** Combined path for a graphics-owned tracking/render loop. */
        default void tracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs) throws Exception {}
        default void tracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,StereoViews views) throws Exception {
            throw new UnsupportedOperationException("Source does not carry exact runtime eye views");
        }
        /** Input-only publication: no graphics or movie state may be touched. */
        default void publishTracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,StereoViews views) throws Exception {
            throw new UnsupportedOperationException("Source does not support independent tracking publication");
        }
        /** Apply the exact chosen pose to graphics-owned movie state. */
        default void stageTracking(float[] head,int flags,int frame,StereoViews views) {}
        default void close() {}
    }
    void pause();
    void resume();
    /** Some vendor runtimes keep their compositor while a visible overlay pauses
     * the Activity, and retire only at onStop. Standard adapters keep onPause.
     */
    default boolean rendersWhileVisible() {return false;}
    default void inputFocused(boolean focused) {}
    void prepareGuest();
    void destroy();
    /** Called by the main thread, even if the graphics owner cannot return. */
    default void graphicsStalled(NativeDrawProgress.Stall stall,long observed) throws java.io.IOException {}
    /** A previously stalled native call also prevented the view from pausing. */
    default void graphicsAbandoned() {}
    /** Called on the graphics owner before the failing EGL context is released. */
    default void renderFailed(Throwable failure) {destroy();}
}
