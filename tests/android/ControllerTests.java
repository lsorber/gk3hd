package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Synthetic record/wire fixtures. Never injected as real input into a game. */
public final class ControllerTests {
    private static void check(boolean value,String text) {if(!value) throw new AssertionError(text);}
    private static void near(float a,float b) {check(Math.abs(a-b)<.0001f,"Unexpected value "+a+" vs "+b);}
    private static ByteBuffer sample(long timestamp) {
        ByteBuffer out=ByteBuffer.allocate(544).order(ByteOrder.LITTLE_ENDIAN);
        for(int base:new int[]{0,272}) {
            out.putInt(base+136,2).put(base+140,(byte)1).putInt(base+236,2).putLong(base+240,timestamp);
            out.putFloat(base+220,1).putFloat(base+224,1).putFloat(base+228,2).putFloat(base+232,-3);
            out.putFloat(base+68,128).putFloat(base+72,128);
        }
        return out;
    }
    public static void main(String[] args) throws Exception {
        long now=1_000_000_000L;
        ByteBuffer raw=sample(now-1_000_000);
        XrInput input=PimaxControllerSample.decode(raw,now);
        check(input.left.flags==15&&input.right.flags==15,"Both genuine firmware status-2 poses accepted");
        near(input.left.x,0);near(input.left.trigger,0);near(input.left.pose()[0],1);near(input.left.pose()[2],-3);
        raw.putFloat(68,0).putFloat(72,255).putFloat(100,204).putFloat(108,255).putInt(64,1|2|(1<<15)|0x100);
        input=PimaxControllerSample.decode(raw,now);
        near(input.left.x,-1);near(input.left.y,127/128.f);near(input.left.trigger,.8f);near(input.left.grip,1);
        check(input.left.buttons==63,"Firmware buttons and analog click thresholds mapped");
        check(input.right.buttons==0,"Left input doesn't leak to right");
        check(PimaxControllerSample.decode(raw,now+250_000_001L).left.flags==0,"Stale sensor input rejected");
        check(PimaxControllerSample.decode(raw,0).left.flags==0,"Wrong/future timestamp rejected");
        raw.putInt(136,1);check(PimaxControllerSample.decode(raw,now).left.buttons==0,"Disconnected buttons released");
        raw=sample(now);raw.put(140,(byte)0);
        check(PimaxControllerSample.decode(raw,now).left.flags==0,"Position loss stays unlocated");
        raw=sample(now);raw.putFloat(220,0);
        check(PimaxControllerSample.decode(raw,now).left.flags==0,"Invalid quaternion not normalized into tracking");
        float[] pose={1,2,-3,0,0,0,1};XrInput.Hand left=new XrInput.Hand(pose,15,63,-1,.5f,.8f,1);
        pose[0]=99;near(left.pose()[0],1);left.pose()[0]=100;near(left.pose()[0],1);
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            bridge.focused(true);
            // LOCAL origin, a left aim with an offset, and a right grip. Three locations.
            bridge.decode("0 0 1 1 90 90 1 101 2 0 0 0 0 0 0 1 2 201 1 0 0 1 0 0 0 0 1 202 2 1 0 0 0 0 0 0 1 3 201 101 202 101 201 0");
            ByteBuffer packet=ByteBuffer.wrap(bridge.encode(new float[]{0,0,0,0,0,0,1},0,.064f,1.5f,1.5f,90,7,
                new XrInput(left,XrInput.UNLOCATED))).order(ByteOrder.LITTLE_ENDIAN);
            near(packet.getFloat(4),-1);near(packet.getFloat(8),.5f);near(packet.getFloat(20),.8f);
            check(packet.getInt(60)==((1<<8)|(1<<9)|(1<<1)|(1<<2)|(1<<7)|1),"Correct left wire buttons, no right buttons");
            check(packet.getInt(76)==15,"Controller relative to LOCAL doesn't invent or require a valid head");
            near(packet.getFloat(80),1);near(packet.getFloat(84),3);near(packet.getFloat(88),-3);
            check(packet.getInt(144)==0,"Unlocated right hand remains unlocated");
            check(packet.getInt(212)==0,"Controller relative to invalid head remains unlocated");
            packet=ByteBuffer.wrap(bridge.encode(new float[]{0,0,0,0,0,0,1},15,.064f,1.5f,1.5f,90,8,XrInput.EMPTY)).order(ByteOrder.LITTLE_ENDIAN);
            check(packet.getInt(60)==0&&packet.getInt(76)==0,"Disconnect clears actions and location together");
        }
        System.out.println("Controllers passed: native layout, freshness, basis, axes/buttons, disconnection, immutable poses and action-space wire routing");
    }
}
