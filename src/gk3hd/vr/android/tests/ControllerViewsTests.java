package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Real raw-record decoder and guest wire routing, without headset/game input. */
public final class ControllerViewsTests {
    private static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
    private static void approx(float actual,float expected){check(Math.abs(actual-expected)<.0001f,"Unexpected pose/axis "+actual+" vs "+expected);}
    public static void main(String[] args) throws Exception {
        float[] raw=new float[36];
        for(int hand=0;hand<2;hand++) {
            int p=hand*18;
            raw[p]=1+hand*6;raw[p+1]=2+hand*6;raw[p+2]=-3-hand*6;raw[p+6]=1;
            raw[p+7]=4+hand*6;raw[p+8]=5+hand*6;raw[p+9]=-6-hand*6;raw[p+13]=1;
            raw[p+14]=-.25f+hand*.5f;raw[p+15]=.5f;raw[p+16]=.8f;raw[p+17]=.9f;
        }
        float root=(float)Math.sqrt(.5);raw[11]=root;raw[13]=root;
        int[] state={15,3,63,15,15,63};
        XrInput input=OpenXrControllerSample.decode(raw,state);
        check(input.left.flags==15&&input.left.gripFlags==3&&input.right.gripFlags==15,"Independent validity/tracked flags lost");
        raw[0]=100;raw[7]=200;
        approx(input.left.pose()[0],1);approx(input.left.gripPose()[0],4);
        input.left.gripPose()[0]=300;approx(input.left.gripPose()[0],4);
        raw[0]=1;raw[7]=4;
        for(int flags=0;flags<16;flags++)check(OpenXrControllerSample.flags(flags)==flags,"Native hand flags changed");
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            bridge.focused(true);
            bridge.decode("0 0 1 1 90 90 1 101 2 0 0 0 0 0 0 1 4 201 1 0 0 1 0 0 0 0 1 202 1 1 0 0 -1 0 0 0 1 203 2 0 0 0 0 0 0 0 1 204 2 1 0 0 0 0 0 0 1 4 201 101 202 101 203 101 204 101");
            float[] head={0,0,0,0,0,0,1};
            ByteBuffer packet=ByteBuffer.wrap(bridge.encode(head,15,.064f,1.5f,1.5f,90,9,input)).order(ByteOrder.LITTLE_ENDIAN);
            check(packet.getInt(64)==4,"Missing actual action queries");
            check(packet.getInt(76)==15&&packet.getInt(144)==3&&packet.getInt(212)==15&&packet.getInt(280)==15,"Aim/grip flags not routed independently");
            approx(packet.getFloat(80),1);approx(packet.getFloat(84),3);approx(packet.getFloat(88),-3);
            approx(packet.getFloat(148),3);approx(packet.getFloat(152),5);approx(packet.getFloat(156),-6);
            approx(packet.getFloat(216),7);approx(packet.getFloat(284),10);
            approx(packet.getFloat(4),-.25f);approx(packet.getFloat(12),.25f);
            if(args.length==1)java.nio.file.Files.write(java.nio.file.Paths.get(args[0],"controller-located.bin"),packet.array(),java.nio.file.StandardOpenOption.CREATE_NEW);
            state[0]=0;state[1]=15;state[3]=0;state[4]=15;
            XrInput lostAim=OpenXrControllerSample.decode(raw,state);
            check(lostAim.left.buttons==0&&lostAim.right.buttons==0&&lostAim.left.trigger==0&&lostAim.left.x==0,"Aim loss left controls held");
            packet=ByteBuffer.wrap(bridge.encode(head,15,.064f,1.5f,1.5f,90,10,lostAim)).order(ByteOrder.LITTLE_ENDIAN);
            check(packet.getInt(60)==0&&packet.getInt(76)==0&&packet.getInt(212)==0&&packet.getInt(144)==15&&packet.getInt(280)==15,"Grip tracking was conflated with aim tracking");
            if(args.length==1)java.nio.file.Files.write(java.nio.file.Paths.get(args[0],"controller-lost-aim.bin"),packet.array(),java.nio.file.StandardOpenOption.CREATE_NEW);
        }
        for(int flags=0;flags<16;flags++) {
            state[0]=flags;
            XrInput.Hand hand=OpenXrControllerSample.decode(raw,state).left;
            check(hand.buttons==((flags&3)==3?63:0),"Controller actions confused validity with active tracking");
        }
        XrInput.Hand onePose=new XrInput.Hand(new float[]{1,2,3,0,0,0,1},15,0,0,0,0,0);
        approx(onePose.gripPose()[0],onePose.pose()[0]);check(onePose.gripFlags==onePose.flags,"Single-pose firmware contract changed");
        System.out.println("Native controllers: independent immutable aim/grip, flags, axes, action offsets and actual wire routing passed");
    }
}
