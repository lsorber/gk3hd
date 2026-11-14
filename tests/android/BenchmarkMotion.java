package org.gk3hd.standalone;

/** Simulated benchmark motion has one origin, independent of preparation time. */
public final class BenchmarkMotion {
    private boolean aligned;
    private long preparedAt,origin;
    public void alignToMeasurement() {
        if(preparedAt!=0)throw new IllegalStateException("Align motion before world preparation");
        aligned=true;
    }
    public void prepare(long now) {
        if(now<=0||preparedAt!=0)throw new IllegalStateException("Invalid motion preparation");
        preparedAt=now;if(!aligned)origin=now;
    }
    public void beginMeasurement(long now) {
        if(!aligned||preparedAt==0||origin!=0||now<preparedAt)
            throw new IllegalStateException("Motion has no prepared measurement boundary");
        origin=now;
    }
    public void reset(){preparedAt=0;origin=0;}
    public boolean prepared(){return preparedAt!=0;}
    public boolean active(){return origin!=0;}
    public boolean aligned(){return aligned;}
    public long preparedAt(){return preparedAt;}
    public long origin(){return origin;}
    public double seconds(long now) {
        if(!active())return 0;
        if(now<origin)throw new IllegalStateException("Motion observation precedes its origin");
        return (now-origin)/1e9;
    }
    public float step(long now) {
        if(!active())return 0;
        if(now<origin)throw new IllegalStateException("Motion observation precedes its origin");
        long age=(now-origin)%4_000_000_000L;
        return age<250_000_000L||age>=3_750_000_000L||
            (age>=1_750_000_000L&&age<2_250_000_000L) ? 0 : age<2_000_000_000L ? .35f : -.35f;
    }
}
