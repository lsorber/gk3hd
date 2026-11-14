package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Host-side wire/space tests. Synthetic samples never reach a headset or game. */
public final class XrApiBridgeTests {
    private static void check(boolean value,String message) {if(!value) throw new AssertionError(message);}
    private static void near(float a,float b) {check(Math.abs(a-b)<1e-5f,"Pose mismatch: "+a+" vs "+b);}
    public static void main(String[] args) throws Exception {
        float r=(float)Math.sqrt(.5);
        float[] a={1,2,3,0,r,0,r},b={0,0,-1,0,0,0,1};
        float[] result=XrApiBridge.compose(a,b);
        near(result[0],0);near(result[1],2);near(result[2],3);
        float[] identity=XrApiBridge.compose(XrApiBridge.inverse(a),a);
        for(int i=0;i<6;i++) near(identity[i],0);near(identity[6],1);
        near(PimaxTracking.fullIpd(.03176f),.06352f);
        check(PimaxTracking.locationFlags(0)==0,"Lost tracking stays invalid");
        check(PimaxTracking.locationFlags(1)==5,"Orientation-only is not positional tracking");
        check(PimaxTracking.locationFlags(2)==10,"Position-only is not orientation tracking");
        check(PimaxTracking.locationFlags(3)==15,"Both native tracking bits propagated");
        check(PimaxTracking.locationFlags(4)==0,"Eye-only status is not head tracking");
        float[] physical=PimaxTracking.headPose(new float[]{1,-2,3,0,r,0,r});
        near(physical[0],-1);near(physical[1],2);near(physical[2],-3);near(physical[4],-r);near(physical[6],r);
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            check(!bridge.runtimeConnected(),"Cold guest is not ready");
            bridge.decode("0 0 2");bridge.decode("0 0 1 0");
            check(!bridge.runtimeConnected(),"Unrecognized short packet is not readiness");
            bridge.decode("0 0 2 0");
            check(bridge.runtimeConnected()&&bridge.receivedCommands()==0,"Runtime hello needs no host tracking or spaces");
            bridge.decode("0 0 1 1 90 90 1 101 2 1 0 0 0 0 0 1 0 2 0 101 999 101");
            check(bridge.receivedCommands()==1,"Reference request accepted");
            byte[] packet=bridge.encode(a,15,.064f,1.5f,1.5f,90,42);
            ByteBuffer data=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
            check(data.get()=='W'&&data.get()=='X'&&data.get()=='R'&&data.get()==10,"Explicit lifetime protocol");
            check(data.getInt(52)==42 && data.getInt(64)==2,"Frame and query count");
            check(packet.length==68+2*68+32,"Bounded lifetime packet length");
            check(data.getInt(76)==15,"Known head location flags");
            near(data.getFloat(80),0);near(data.getFloat(84),2);near(data.getFloat(88),3);
            check(data.getInt(144)==0,"Unknown controller stays unlocated");
            byte[] invalid=bridge.encode(a,0,.064f,1.5f,1.5f,90,43);
            data=ByteBuffer.wrap(invalid).order(ByteOrder.LITTLE_ENDIAN);
            check(data.getInt(76)==0,"Tracking loss is not upgraded");
            for(int i=0;i<7;i++) near(data.getFloat(80+i*4),0);
            try {bridge.decode("0 0 1 1 90 90 128");throw new AssertionError("Truncated command accepted");}
            catch(IllegalArgumentException expected) {check(bridge.receivedCommands()==1,"Malformed update is atomic");}
            try {bridge.encode(a,15,Float.NaN,1.5f,1.5f,90,0);throw new AssertionError("Invalid metadata accepted");}
            catch(IllegalArgumentException expected) { /* expected */ }
        }
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            bridge.decode("0 0 1 1 90 90 0 0 0");
            check(bridge.runtimeConnected(),"Full runtime state also establishes readiness");
        }
        System.out.println("XR bridge: space composition, explicit validity, unknown hands, malformed input and metadata checks passed");
    }
}
