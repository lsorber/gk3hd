package org.gk3hd.standalone;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Cross-language fixture uses real bridge encoding, never a headset/game pose. */
public final class StereoViewsTests {
    private static void require(boolean value,String message) {if(!value)throw new AssertionError(message);}
    public static void main(String[] args) throws Exception {
        float[] left={-.032f,.002f,.004f,0,(float)Math.sin(.05),0,(float)Math.cos(.05)};
        float[] right={.033f,-.003f,.005f,0,(float)Math.sin(-.07),0,(float)Math.cos(-.07)};
        float[] lf={-.9f,.7f,.85f,-.8f},rf={-.65f,.95f,.8f,-.9f};
        StereoViews views=new StereoViews(left,lf,right,rf);
        left[0]=99;lf[0]=99; // Captured optics must remain immutable.
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            bridge.focused(true);
            bridge.decode("0 0 1 1 90 90 1 101 2 0 0 0 0 0 0 1 0 1 0 101");
            float r=(float)Math.sqrt(.5);
            float[] head={1,2,3,0,r,0,r};
            byte[] bytes=bridge.encode(head,15,.065f,1.6f,1.65f,90,73,XrInput.EMPTY,views);
            ByteBuffer data=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
            require(bytes.length==68+68+32+88&&data.get(3)==10,"Exact-eye lifetime wire contract");
            require(data.getInt(52)==73&&data.getInt(64)==1&&data.getInt(76)==15,"Frame/query identity changed");
            require(data.getFloat(168)==-.032f&&data.getFloat(196)==-.9f,"Immutable eye snapshot lost");
            byte[] invalid=bridge.encode(head,0,.065f,1.6f,1.65f,90,74,XrInput.EMPTY,views);
            require(ByteBuffer.wrap(invalid).order(ByteOrder.LITTLE_ENDIAN).getInt(76)==0,"Eye optics promoted tracking");
            if(args.length==1)Files.write(Paths.get(args[0]),bytes);
        }
        float[][] badFovs={{Float.NaN,.7f,.8f,-.8f},{.5f,-.5f,.8f,-.8f},{-.8f,.8f,-.5f,.5f},{-2,.8f,.8f,-.8f}};
        for(float[] fov:badFovs) {
            try {new StereoViews(right,fov,right,rf);throw new AssertionError("Invalid FOV accepted");}
            catch(IllegalArgumentException expected) { /* expected */ }
        }
        try {new StereoViews(new float[7],rf,right,rf);throw new AssertionError("Invalid quaternion accepted");}
        catch(IllegalArgumentException expected) { /* expected */ }
        System.out.println("Exact eye optics: asymmetric/canted immutable views, tracking loss and malformed optics passed");
    }
}
