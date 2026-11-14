package org.gk3hd.standalone;

/** One coherent, one-shot observation of a graphics owner's current call. */
final class NativeDrawProgress {
    enum Phase { SETUP, RESIZE, DRAW, SWAP }

    static final class Stall {
        final Phase phase;
        final long elapsedNs;
        private final long call;
        Stall(Phase phase,long elapsedNs,long call) {
            this.phase=phase;this.elapsedNs=elapsedNs;this.call=call;
        }
    }

    private static final long THRESHOLD_NS=10_000_000_000L;
    private Phase phase;
    private long started,call;
    private boolean active,reported;

    synchronized void active(boolean value) {
        active=value;
        if(!value)phase=null;
    }

    synchronized void begin(Phase value,long now) {
        if(!active)return;
        phase=value;
        started=now;
        call++;
        reported=false;
    }

    synchronized void finish() {phase=null;}

    synchronized Stall inspect(long now) {
        if(reported)return null;
        Stall stall=pending(now);
        if(stall!=null)reported=true;
        return stall;
    }
    synchronized Stall pending(long now) {
        return phase==null||now-started<THRESHOLD_NS ? null : new Stall(phase,now-started,call);
    }
    synchronized boolean stillPending(Stall stall) {
        return phase!=null&&stall!=null&&stall.call==call;
    }
}
