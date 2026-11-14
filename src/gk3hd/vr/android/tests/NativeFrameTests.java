package org.gk3hd.standalone;

/** Pure Java mapping of actual native frame data, without initializing a loader. */
public final class NativeFrameTests {
    private static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
    public static void main(String[] args) throws Exception {
        float[] poses=new float[29];poses[0]=1;poses[1]=2;poses[2]=3;poses[6]=1;
        poses[7]=-.031f;poses[13]=1;poses[14]=-.8f;poses[15]=.7f;poses[16]=.9f;poses[17]=-.6f;
        poses[18]=.033f;poses[24]=1;poses[25]=-.7f;poses[26]=.85f;poses[27]=.8f;poses[28]=-.7f;
        for(int bits=0;bits<16;bits++) {
            long[] state={123,1_000_000_000L,11_111_111,bits,1,1,42,(bits&3)==3?113:0};
            NativeOpenXr.Frame frame=new NativeOpenXr.Frame(poses,state);
            check(frame.serial==123&&frame.time==state[1]&&frame.period==state[2]&&frame.shouldRender&&frame.focused,"Native timing/state lost");
            check(frame.flags==bits,"Actual OpenXR tracking flags changed");
            check(frame.epoch==42,"Native coordinate epoch lost");
            check(frame.reusableSerial==state[7],"Released image ownership lost");
            if((bits&3)==3) {
                check(frame.views!=null&&Math.abs(frame.ipd-.064f)<1e-6f,"Actual eye separation lost");
                check(Math.abs(frame.fovX-1.55f)<.0001f,"Asymmetric FOV/radian contract lost");
                poses[0]=10;check(frame.head[0]==1,"Frame head snapshot mutated");poses[0]=1;
            } else check(frame.views==null,"Invalid native tracking produced exact views");
            try(XrApiBridge bridge=new XrApiBridge(0)) {
                byte[] packet=bridge.encode(frame.head,frame.flags,frame.ipd,frame.fovX,frame.fovY,
                    1_000_000_000f/frame.period,321,XrInput.EMPTY,frame.views);
                check(packet[3]==10,"Native frame did not reach the lifetime wire encoder");
            }
        }
        FramePoses<String> matches=new FramePoses<>();
        matches.beginEpoch(42);matches.remember(7,"old",3,100);
        matches.beginEpoch(42);check("old".equals(matches.match(7,101)),"Unchanged space lost its rendered image");
        matches.beginEpoch(43);check(matches.match(7,102)==null,"Recenter reused an image from the old coordinate basis");
        matches.remember(8,"new",3,103);check("new".equals(matches.match(8,104)),"New coordinate image did not recover");
        FramePoses<String> timed=new FramePoses<>();
        long nativeTime=1_000_000_000L;
        timed.remember(1,"rendered",3,nativeTime);
        check("rendered".equals(timed.match(1,nativeTime+240_000_000L)),"Valid native render age rejected");
        check(timed.match(1,nativeTime+260_000_000L)==null,"Native-expired pose reached presentation");
        FramePoses<String> retained=new FramePoses<>();retained.focused(true);
        long observed=420_000_000L;
        retained.remember(1,"original native view",3,nativeTime,observed);
        FramePoses.Sample<String> original=retained.matchImageSample(1,71,nativeTime+1);
        check(original!=null&&"original native view".equals(original.pose)&&original.observed==observed,
            "Fresh immutable source must retain its own host observation time");
        check("original native view".equals(retained.matchImage(1,71,nativeTime+300_000_000L)),"Known source pause lost its original view");
        check(retained.matchImageSample(1,71,nativeTime+300_000_000L)==original,
            "A held image must retain its original sample despite later submission");
        check(!retained.inputsCurrent(nativeTime+300_000_000L),"Known image hold renewed game actions");
        check(retained.matchImage(1,72,nativeTime+300_000_001L)==null,"Unseen late pixels inherited a held pose");
        retained.remember(2,"fresh native view",3,nativeTime+300_000_002L);
        check("fresh native view".equals(retained.matchImage(2,73,nativeTime+300_000_003L))&&retained.inputsCurrent(nativeTime+300_000_003L),"Fresh image did not recover input/view ownership");
        retained.focused(false);
        check(retained.matchImage(2,73,nativeTime+300_000_004L)==null,"Lost focus retained image ownership");
        System.out.println("Native frame: all tracking flag combinations, immutable head data, asymmetric optics and native timing passed");
    }
}
