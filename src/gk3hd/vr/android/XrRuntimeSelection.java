package org.gk3hd.standalone;

/** Runtime capabilities, never headset names, select the standalone presenter. */
public final class XrRuntimeSelection {
    public enum Backend { OPENXR, PIMAX }
    public static final String HEADSET_EYE_RESOLUTION="gk3hd_headset_eye_resolution";
    private XrRuntimeSelection() {}
    public static Backend choose(int support,boolean pimaxAvailable) {
        if(support==1)return Backend.OPENXR;
        if(support==2)throw new IllegalStateException("The OpenXR runtime lacks required Android/GLES support.");
        if(support!=0)throw new IllegalArgumentException("Unknown OpenXR discovery result");
        if(pimaxAvailable)return Backend.PIMAX;
        throw new IllegalStateException("No supported standalone VR runtime was found.");
    }
    public static boolean needsCamera(Backend backend) {return backend==Backend.PIMAX;}

    /** Benchmarked standalone sizes. The selected runtime still supplies the eye projection. */
    public static String headsetEyeResolution(Backend backend,String model) {
        if(backend==Backend.PIMAX&&"Pimax_Crystal".equals(model))return "2688x2752";
        if(backend==Backend.OPENXR&&"Quest 3".equals(model))return "3008x3264";
        return null;
    }
}
