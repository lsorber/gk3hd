package org.gk3hd.standalone;

public final class NativeCameraReadinessTests {
    private static int checks;
    private static void check(boolean value){if(!value)throw new AssertionError("Camera readiness check "+checks);checks++;}
    public static void main(String[] args) {
        NativeCameraReadiness gate=new NativeCameraReadiness();
        double[] old={.2,.1,277,61,50},destination={.6,.1,135,59,-18};
        check(!gate.ready(1,100,old));
        check(!gate.ready(100_000_001L,102,old));
        check(!gate.ready(200_000_001L,103,destination));
        check(!gate.ready(300_000_001L,105,destination));
        check(!gate.ready(400_000_001L,104,destination));
        check(gate.ready(400_000_001L,105,destination));
        check(!gate.ready(500_000_001L,106,new double[5]));
        check(!gate.ready(600_000_001L,107,destination));
        check(!gate.ready(900_000_001L,108,destination));
        check(gate.ready(900_000_001L,109,destination));
        check(!gate.ready(1_000_000_001L,1,destination));
        check(!gate.ready(1_300_000_001L,3,new double[]{0,0,Double.NaN,1,2}));
        check(!gate.ready(1_400_000_001L,4,null));
        check(!gate.ready(1_500_000_001L,5,new double[]{1,2}));
        double[] mutable=destination.clone();
        check(!gate.ready(1_600_000_001L,6,mutable));
        mutable[2]+=1;
        check(!gate.ready(1_900_000_001L,9,mutable));
        check(gate.ready(2_100_000_001L,11,mutable));
        System.out.println(checks+" camera initialization/settlement/native-frame/transition checks passed");
    }
}
