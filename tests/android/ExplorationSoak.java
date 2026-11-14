package org.gk3hd.standalone;

/** Bounded reliability interval before the separate timing sample. */
public final class ExplorationSoak {
    private final long duration;
    private long first,last,frames,maximumGap;
    public ExplorationSoak(int seconds) {
        if(seconds<0||seconds>600)throw new IllegalArgumentException("Soak requires 0..600 seconds");
        duration=seconds*1_000_000_000L;
    }
    public void observe(long now) {
        if(now<=0||last!=0&&now<=last)throw new IllegalStateException("Non-monotonic source observation");
        if(first==0)first=now;
        if(last!=0)maximumGap=Math.max(maximumGap,now-last);
        last=now;frames++;
    }
    public boolean complete() {return duration==0||first!=0&&last-first>=duration;}
    public long frames() {return frames;}
    public long elapsedNanos() {return first==0 ? 0 : last-first;}
    public long maximumGapNanos() {return maximumGap;}
}
