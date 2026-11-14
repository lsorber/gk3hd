package org.gk3hd.standalone;

import java.nio.ByteBuffer;

/** Exact runtime eye poses relative to the transmitted head, in OpenXR axes/metres. */
public final class StereoViews {
    public static final int WIRE_BYTES=88;
    private final float[][] poses=new float[2][],fovs=new float[2][];
    public StereoViews(float[] leftPose,float[] leftFov,float[] rightPose,float[] rightFov) {
        float[][] p={leftPose,rightPose},f={leftFov,rightFov};
        for(int eye=0;eye<2;eye++) {
            if(p[eye]==null||f[eye]==null||p[eye].length!=7||f[eye].length!=4)
                throw new IllegalArgumentException("Expected two eye poses and FOVs");
            for(float value:p[eye]) if(!Float.isFinite(value)) throw new IllegalArgumentException("Non-finite eye pose");
            float norm=0;for(int i=3;i<7;i++)norm+=p[eye][i]*p[eye][i];
            if(Math.abs(norm-1)>.001f) throw new IllegalArgumentException("Invalid eye orientation");
            for(float value:f[eye]) if(!Float.isFinite(value)||Math.abs(value)>=Math.PI/2)
                throw new IllegalArgumentException("Unsupported eye FOV angle");
            if(f[eye][0]>=f[eye][1]||f[eye][3]>=f[eye][2])
                throw new IllegalArgumentException("Inverted eye FOV");
            poses[eye]=p[eye].clone();fovs[eye]=f[eye].clone();
        }
    }
    float[] eyePose(int eye) {return poses[eye].clone();}
    float[] eyeFov(int eye) {return fovs[eye].clone();}
    void write(ByteBuffer target) {
        for(int eye=0;eye<2;eye++) {
            for(float value:poses[eye])target.putFloat(value);
            for(float value:fovs[eye])target.putFloat(value);
        }
    }
}
