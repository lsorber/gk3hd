package org.gk3hd.standalone;

/** Test workload equivalence, without a headset, clocks, sleeps or game writes. */
public final class BenchmarkMotionTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void rejected(Runnable action) {
        try {action.run();throw new AssertionError("Invalid measurement boundary was accepted");}
        catch(IllegalStateException expected) {}
    }
    public static void main(String[] args) {
        BenchmarkMotion early=new BenchmarkMotion(),late=new BenchmarkMotion();
        early.alignToMeasurement();late.alignToMeasurement();early.prepare(1);late.prepare(1);
        long a=1_000_000_000L,b=21_000_000_000L;
        for(long now=1;now<=b;now+=100_000_000L) {
            check(!late.active()&&late.step(now)==0&&late.seconds(now)==0,
                "Preparation generated motion before the timing sample");
        }
        early.beginMeasurement(a);late.beginMeasurement(b);
        check(early.prepared()&&late.prepared()&&early.origin()==a&&late.origin()==b,"Timing origin changed");
        boolean forward=false,backward=false;
        for(long offset=0;offset<=5_000_000_000L;offset+=7_000_000L) {
            check(early.seconds(a+offset)==late.seconds(b+offset)&&
                  early.step(a+offset)==late.step(b+offset),"Preparation length changed the measured path");
            check(early.seconds(a+offset)==offset/1e9,"Motion used a substituted observation time");
            forward|=early.step(a+offset)>0;backward|=early.step(a+offset)<0;
        }
        check(forward&&backward,"The measured exploration path does not move both ways");
        rejected(()->late.beginMeasurement(b+1));rejected(()->late.seconds(b-1));
        rejected(()->late.alignToMeasurement());
        late.reset();check(late.aligned()&&!late.prepared()&&!late.active()&&late.step(b+1)==0,
            "A scene transition revived the previous motion origin");
        rejected(()->late.beginMeasurement(b+1));late.prepare(b+2);late.beginMeasurement(b+3);
        check(late.seconds(b+3)==0,"New scene did not get its own origin");
        BenchmarkMotion ordinary=new BenchmarkMotion();ordinary.prepare(a);
        check(ordinary.active()&&ordinary.origin()==a&&ordinary.seconds(a+1_000_000_000L)==1,
            "Unaligned native correctness journeys lost their ordinary motion");
        BenchmarkMotion invalid=new BenchmarkMotion();invalid.alignToMeasurement();
        rejected(()->invalid.prepare(0));invalid.prepare(2);rejected(()->invalid.prepare(3));
        rejected(()->invalid.beginMeasurement(1));
        System.out.println("Benchmark motion: neutral preparation, equal timed paths, original times, transitions and ordinary journeys passed");
    }
}
