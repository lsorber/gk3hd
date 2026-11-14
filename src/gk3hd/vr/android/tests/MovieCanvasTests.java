package org.gk3hd.standalone;

/** Projection behaviour independent of Android, GPU or headset presence. */
public final class MovieCanvasTests {
    private static final float[] HEAD={0,0,0,0,0,0,1};
    private static final float[] FOV={-(float)Math.PI/4,(float)Math.PI/4,(float)Math.PI/4,-(float)Math.PI/4};
    private static void near(float got,float expected,String why){if(Math.abs(got-expected)>0.00002f)throw new AssertionError(why+": "+got+" != "+expected);}
    private static StereoViews eyes(float ipd,float cant) {
        float y=(float)Math.sin(cant/2),w=(float)Math.cos(cant/2);
        return new StereoViews(new float[]{-ipd/2,0,0,0,y,0,w},FOV,new float[]{ipd/2,0,0,0,-y,0,w},FOV);
    }
    private static float center(float[] v,int coordinate) {float sum=0,w=0;for(int i=0;i<4;i++){sum+=v[i*4+coordinate];w+=v[i*4+3];}return sum/w;}
    public static void main(String[] args) {
        MovieCanvas canvas=new MovieCanvas(HEAD,2560,1920);float[] v=new float[16];StereoViews parallel=eyes(0,0);
        canvas.vertices(HEAD,parallel,0,v);
        near(v[0]/v[3],-.5f,"Movie keeps 4:3 physical aspect");near(v[1]/v[3],-.375f,"Movie height fits cinema");
        near(v[4]/v[7],.5f,"Right edge");near(v[9]/v[11],.375f,"Top edge");
        canvas.vertices(new float[]{.2f,0,0,0,0,0,1},parallel,0,v);near(center(v,0),-.1f,"Walking right moves fixed screen left");
        StereoViews separated=eyes(.06302f,0);canvas.vertices(HEAD,separated,0,v);near(center(v,0),.015755f,"Left eye finite screen disparity");
        canvas.vertices(HEAD,separated,1,v);near(center(v,0),-.015755f,"Right eye finite screen disparity");
        float cant=(float)Math.toRadians(5.04382);StereoViews canted=eyes(0,cant);
        canvas.vertices(HEAD,canted,0,v);near(center(v,0),(float)Math.tan(cant),"Outward left eye sees screen to its right");
        canvas.vertices(HEAD,canted,1,v);near(center(v,0),-(float)Math.tan(cant),"Outward right eye sees screen to its left");
        float[] shifted={4,-3,6,0,(float)Math.sin(.35),(float)0,(float)Math.cos(.35)};
        MovieCanvas moved=new MovieCanvas(shifted,2560,1920);float[] expected=new float[16];canvas.vertices(HEAD,canted,0,expected);moved.vertices(shifted,canted,0,v);
        for(int i=0;i<16;i++)near(v[i],expected[i],"Common tracking-origin transform preserves screen");
        float[] pitch={0,0,0,(float)Math.sin(.2),0,0,(float)Math.cos(.2)};
        float[] roll={0,0,0,0,0,(float)Math.sin(.12),(float)Math.cos(.12)};
        float[] tilted=XrApiBridge.compose(shifted,XrApiBridge.compose(pitch,roll));
        MovieCanvas tiltedStart=new MovieCanvas(tilted,2560,1920);
        for(int eye=0;eye<2;eye++) {
            moved.vertices(shifted,canted,eye,expected);
            tiltedStart.vertices(shifted,canted,eye,v);
            for(int i=0;i<16;i++)near(v[i],expected[i],"Initial head tilt must not bank or raise the cinema");
            tiltedStart.vertices(tilted,canted,eye,v);
            moved.vertices(tilted,canted,eye,expected);
            for(int i=0;i<16;i++)near(v[i],expected[i],"Watching with tilted head preserves a level world anchor");
        }
        float[] asym={-(float)Math.atan(.8),(float)Math.atan(1.2),(float)Math.atan(.7),-(float)Math.atan(1.3)};
        StereoViews asymmetric=new StereoViews(HEAD,asym,HEAD,asym);canvas.vertices(HEAD,asymmetric,0,v);
        near(center(v,0),-.2f,"Asymmetric horizontal optical center");near(center(v,1),.3f,"Asymmetric vertical optical center");
        new MovieCanvas(HEAD,3200,1000).vertices(HEAD,parallel,0,v);near(v[0]/v[3],-.6f,"Wide movie retains width limit");near(v[1]/v[3],-.1875f,"Wide movie retains aspect");
        try {new MovieCanvas(HEAD,0,10);throw new AssertionError("Invalid dimensions accepted");}catch(IllegalArgumentException expectedFailure){}
        System.out.println("Cinema projection: aspect, head motion, finite disparity, outward cant, asymmetric FOV and origin invariance passed");
    }
}
