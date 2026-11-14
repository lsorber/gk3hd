package org.gk3hd.standalone;

/** Firmware-specific units and basis, kept outside the generic XR bridge. */
public final class PimaxTracking {
    private PimaxTracking() {}
    public static float fullIpd(float halfMeters) {
        float result=halfMeters*2;
        if(!Float.isFinite(result)||result<.04f||result>.1f) throw new IllegalArgumentException("Invalid calibrated IPD");
        return result;
    }
    public static int locationFlags(int poseStatus) {
        // The firmware Unity input provider maps bit 0 to rotation, bit 1 to position.
        // OpenXR: orientation valid/tracked = 1|4, position valid/tracked = 2|8.
        return ((poseStatus&1)!=0 ? 5 : 0) | ((poseStatus&2)!=0 ? 10 : 0);
    }
    /** Native frustum: left/right/top/bottom/near, position XYZ, rotation XYZW. */
    public static StereoViews stereoViews(float[] left,float[] right) {
        return new StereoViews(eyePose(left),eyeFov(left),eyePose(right),eyeFov(right));
    }
    private static void requireFrustum(float[] frustum) {
        if(frustum==null||frustum.length!=12)
            throw new IllegalArgumentException("Expected calibrated Pimax eye frustum");
        for(float value:frustum) if(!Float.isFinite(value))
            throw new IllegalArgumentException("Non-finite calibrated Pimax eye frustum");
        if(frustum[4]<=0||frustum[0]>=frustum[1]||frustum[3]>=frustum[2])
            throw new IllegalArgumentException("Invalid calibrated Pimax eye frustum");
    }
    private static float[] eyePose(float[] frustum) {
        requireFrustum(frustum);
        // The firmware Unity display provider preserves native X/Y and flips
        // Z, Qx and Qy for Unity. Converting Unity back to OpenXR cancels those
        // flips. These local eye transforms are not predicted world head poses.
        return new float[]{frustum[5],frustum[6],frustum[7],
            frustum[8],frustum[9],frustum[10],frustum[11]};
    }
    private static float[] eyeFov(float[] frustum) {
        requireFrustum(frustum);
        float near=frustum[4];
        return new float[]{(float)Math.atan(frustum[0]/near),(float)Math.atan(frustum[1]/near),
            (float)Math.atan(frustum[2]/near),(float)Math.atan(frustum[3]/near)};
    }
    public static float[] headPose(float[] nativePose) {
        if(nativePose.length!=7) throw new IllegalArgumentException("Expected position and quaternion");
        for(float value:nativePose) if(!Float.isFinite(value)) throw new IllegalArgumentException("Non-finite native pose");
        // Match pxrInputProvider::UpdateDeviceState's native -> Unity conversion,
        // then convert Unity's left-handed coordinates to OpenXR's right-handed basis.
        // Native position is negated and native orientation is conjugated.
        return new float[]{-nativePose[0],-nativePose[1],-nativePose[2],
            -nativePose[3],-nativePose[4],-nativePose[5],nativePose[6]};
    }
}
