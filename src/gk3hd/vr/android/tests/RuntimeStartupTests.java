package org.gk3hd.standalone;

/** Startup must not require an image or fabricate a pose to unblock the guest. */
public final class RuntimeStartupTests {
    private static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
    public static void main(String[] args) throws Exception {
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            check(!bridge.runtimeConnected(),"Cold runtime");
            bridge.decode("0 0 2");bridge.decode("0 0 1 0");
            check(!bridge.runtimeConnected(),"Incomplete/unknown hello");
            bridge.decode("0 0 2 0");
            check(bridge.runtimeConnected()&&bridge.receivedCommands()==0,"Hello before first host pose");
            byte[] unlocated=bridge.encode(new float[]{0,0,0,0,0,0,1},0,.064f,1.5f,1.5f,90,0);
            check(unlocated.length==100,"Readiness carries lifetime metadata without inventing spaces");
        }
        try(XrApiBridge bridge=new XrApiBridge(0)) {
            try {bridge.decode("0 0 1 1 90 90 128");throw new AssertionError("Truncated state accepted");}
            catch(IllegalArgumentException expected) {check(!bridge.runtimeConnected(),"Malformed state is not readiness");}
            bridge.decode("0 0 1 1 90 90 0 0 0");
            check(bridge.runtimeConnected(),"Complete state works if the hello was lost");
        }
        System.out.println("Guest startup: cold, malformed, retry hello and full-state readiness passed");
    }
}
