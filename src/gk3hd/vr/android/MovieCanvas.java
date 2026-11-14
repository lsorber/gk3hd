package org.gk3hd.standalone;

/** World-anchored cinema projection using the same calibrated eyes as the game. */
public final class MovieCanvas {
    private final float[] anchor;
    private final float width,height;
    public MovieCanvas(float[] head,int sourceWidth,int sourceHeight) {
        validate(head);
        if(sourceWidth<=0||sourceHeight<=0||sourceWidth>32768||sourceHeight>32768)
            throw new IllegalArgumentException("Invalid movie dimensions");
        float ratio=(float)sourceWidth/sourceHeight;
        width=Math.min(2.4f,1.5f*ratio);height=width/ratio;
        // Keep the cinema level with gravity even when playback starts with
        // the wearer looking down or tilting their head. Subsequent physical
        // head motion still sees this fixed world-space screen naturally.
        float x=head[3],y=head[4],z=head[5],w=head[6];
        float forwardX=-2*(x*z+w*y),forwardZ=2*(x*x+y*y)-1;
        float yaw=forwardX*forwardX+forwardZ*forwardZ>1e-8f
            ? (float)Math.atan2(-forwardX,-forwardZ) : 0;
        float[] level={head[0],head[1],head[2],0,(float)Math.sin(yaw/2),0,(float)Math.cos(yaw/2)};
        anchor=XrApiBridge.compose(level,new float[]{0,0,-2,0,0,0,1});
    }
    private static void validate(float[] head) {
        if(head==null||head.length!=7)throw new IllegalArgumentException("Invalid head pose");
        float norm=0;for(int i=0;i<7;i++){if(!Float.isFinite(head[i]))throw new IllegalArgumentException("Non-finite head pose");if(i>=3)norm+=head[i]*head[i];}
        if(Math.abs(norm-1)>.001f)throw new IllegalArgumentException("Invalid head orientation");
    }
    /** Four homogeneous clip vertices, in triangle-strip order. No guessed IPD/FOV. */
    public void vertices(float[] head,StereoViews views,int eye,float[] output) {
        validate(head);
        if(views==null||eye<0||eye>1||output==null||output.length!=16)
            throw new IllegalArgumentException("Exact eye views and four clip vertices required");
        float[] inverse=XrApiBridge.inverse(XrApiBridge.compose(head,views.eyePose(eye)));
        float[] fov=views.eyeFov(eye);
        float l=(float)Math.tan(fov[0]),r=(float)Math.tan(fov[1]);
        float u=(float)Math.tan(fov[2]),d=(float)Math.tan(fov[3]);
        for(int i=0;i<4;i++) {
            float x=(i%2==0?-.5f:.5f)*width,y=(i<2?-.5f:.5f)*height;
            float[] world=XrApiBridge.compose(anchor,new float[]{x,y,0,0,0,0,1});
            float[] local=XrApiBridge.compose(inverse,world);
            int k=i*4;
            output[k]=(2*local[0]+(r+l)*local[2])/(r-l);
            output[k+1]=(2*local[1]+(u+d)*local[2])/(u-d);
            output[k+2]=-(100.01f/99.99f)*local[2]-(2/99.99f);
            output[k+3]=-local[2];
        }
    }
}
