package org.gk3hd.standalone;

public final class LongTravelMotionTests {
    public static void main(String[] args) {
        double integral=0;boolean forward=false,backward=false;
        for(int i=0;i<6000;i++) {
            float value=LongTravelMotion.step(i/1000.);
            if(!Float.isFinite(value)||Math.abs(value)>1)throw new AssertionError("Unbounded stick input");
            integral+=value;forward|=value>0;backward|=value<0;
            if(value!=LongTravelMotion.step(18+i/1000.))throw new AssertionError("Cycle changes with prior travel");
        }
        if(!forward||!backward||integral!=0||LongTravelMotion.step(0)!=0||LongTravelMotion.step(5.9)!=0)
            throw new AssertionError("Travel must reverse symmetrically and leave neutral recovery");
        for(double invalid:new double[]{-1,Double.NaN,Double.POSITIVE_INFINITY}) {
            try {LongTravelMotion.step(invalid);throw new AssertionError("Invalid time accepted");}
            catch(IllegalArgumentException expected) {}
        }
        System.out.println("Bounded reversible travel, repeatable cycles, neutral recovery and invalid inputs passed");
    }
}
