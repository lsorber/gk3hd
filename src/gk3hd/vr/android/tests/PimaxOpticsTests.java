package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Calibrated rays and eye transforms survive the vendor-to-shared boundary. */
public final class PimaxOpticsTests {
    private static void near(float actual,float expected,String message) {
        if(Math.abs(actual-expected)>.000001f)throw new AssertionError(message+": "+actual+" != "+expected);
    }
    private static float[] eye(float x,float yaw) {
        return new float[]{-.07f,.11f,.12f,-.08f,.1f,x,.002f,.003f,
            0,(float)Math.sin(yaw/2),0,(float)Math.cos(yaw/2)};
    }
    private static ByteBuffer encode(float[] left,float[] right) {
        ByteBuffer result=ByteBuffer.allocate(StereoViews.WIRE_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        PimaxTracking.stereoViews(left,right).write(result);result.flip();return result;
    }
    private static void capturedCrystalOptics() {
        // Firmware calibration captured after native compositor initialization.
        // The old centered approximation lost both cant and vertical asymmetry.
        float[] left={-.05666289f,.05666289f,.049107783f,-.066923715f,.057300005f,
            -.03151f,0,0,0,.044000003f,0,.999f};
        float[] right=left.clone();right[5]=-left[5];right[9]=-left[9];
        ByteBuffer data=encode(left,right);
        near(data.getFloat(44)-data.getFloat(0),.06302f,"Physical eye separation changed");
        for(int side=0;side<2;side++) {
            int offset=side*44;
            double yaw=2*Math.atan2(data.getFloat(offset+16),data.getFloat(offset+24));
            // OpenXR looks along -Z: positive eye yaw faces toward negative X.
            double forwardX=-Math.sin(yaw);
            if(side==0 ? forwardX>=-.08 : forwardX<=.08)
                throw new AssertionError("Canted eyes became parallel or converged inward");
            double up=data.getFloat(offset+36),down=data.getFloat(offset+40);
            if(Math.abs(down)-up<.15)
                throw new AssertionError("Calibrated vertical projection became centered");
            near(data.getFloat(offset+32)-data.getFloat(offset+28),
                (float)Math.toRadians(89.359375),"Per-eye field of view changed");
        }
    }
    public static void main(String[] args) {
        capturedCrystalOptics();
        float[] left=eye(-.0315f,.06f),right=eye(.0315f,-.04f);
        ByteBuffer data=encode(left,right);
        for(int side=0;side<2;side++) {
            float[] source=side==0?left:right;int offset=side*44;
            for(int index=0;index<7;index++)near(data.getFloat(offset+index*4),source[index+5],"Eye transform changed");
            for(int index=0;index<4;index++) {
                float ray=(float)Math.tan(data.getFloat(offset+28+index*4));
                near(ray,source[index]/source[4],"Calibrated projection edge changed");
            }
        }
        near(data.getFloat(0),-.0315f,"Left/right eye swapped");
        near(data.getFloat(44),.0315f,"Left/right eye swapped");
        float[] scaled=left.clone();for(int i=0;i<5;i++)scaled[i]*=3;
        ByteBuffer scaledData=encode(scaled,right);
        for(int i=0;i<4;i++)near(scaledData.getFloat(28+i*4),data.getFloat(28+i*4),"Near-plane scale changed FOV");
        StereoViews snapshot=PimaxTracking.stereoViews(left,right);left[5]=99;
        ByteBuffer immutable=ByteBuffer.allocate(88).order(ByteOrder.LITTLE_ENDIAN);snapshot.write(immutable);
        near(immutable.getFloat(0),-.0315f,"Mutable device data changed captured optics");
        for(int fault=0;fault<5;fault++) {
            float[] bad=eye(-.03f,0);
            if(fault==0)bad[4]=0;
            if(fault==1)bad[0]=bad[1];
            if(fault==2)bad[3]=bad[2];
            if(fault==3)bad[8]=Float.NaN;
            if(fault==4)bad[11]=0;
            try {encode(bad,right);throw new AssertionError("Invalid calibration accepted");}
            catch(IllegalArgumentException expected) { /* expected */ }
        }
        System.out.println("Pimax optics: calibrated asymmetric rays, canted eye transforms, units and invalid data passed");
    }
}
