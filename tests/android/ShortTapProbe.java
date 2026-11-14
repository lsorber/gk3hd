package org.gk3hd.standalone;

/** Explicit test-only pulse, with a later normal hold to finish a missed-tap control. */
public final class ShortTapProbe {
    private long started=-1,released=-1,lastDown=-1,lastSample=-1;
    private int downSamples;
    private boolean fallback;
    public boolean held(long now) {
        if(now<0||now<lastSample)throw new IllegalArgumentException("Invalid probe clock");
        lastSample=now;
        if(started<0)started=now;
        long elapsed=now-started;
        if(elapsed<20_000_000L) {downSamples++;lastDown=now;return true;}
        if(released<0)released=now;
        if(elapsed<1_500_000_000L)return false;
        fallback=true;
        return (elapsed-1_500_000_000L)%1_000_000_000L<350_000_000L;
    }
    public long started() {return started;}
    public long released() {return released;}
    public long lastDown() {return lastDown;}
    public int downSamples() {return downSamples;}
    public boolean fallback() {return fallback;}
}
