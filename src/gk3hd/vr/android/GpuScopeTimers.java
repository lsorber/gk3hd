package org.gk3hd.standalone;

/** Bounded asynchronous elapsed-query policy, independent of Android/headsets. */
public final class GpuScopeTimers {
    public interface Driver {
        boolean current();
        int counterBits();
        boolean canBegin();
        int create();
        void begin(int query);
        void end();
        boolean disjoint();
        boolean available(int query);
        long result(int query);
        void delete(int query);
    }
    public interface Clock {long now();}
    public interface Sink {
        void sample(int stage,long identity,long begin,long recorded,long collected,long gpuNanos,String rejected);
    }
    // Every accepted interval fits below the extension's minimum 30-bit
    // counter and a 32-bit unsigned result. Older/blocked samples are rejected.
    public static final long MAX_LATENCY_NANOS=250_000_000L;
    private static final class Slot {
        int query,stage;
        long identity,begin,recorded;
        boolean pending;
        String rejected;
    }
    private final Driver driver;
    private final Clock clock;
    private final Sink sink;
    private final Slot[] slots;
    private final int every,maximum;
    private final long window;
    private final boolean supported;
    private int active=-1,completed;
    private final java.util.HashMap<Integer,Integer> attempts=new java.util.HashMap<>();
    private long armed=-1;
    private boolean closed;
    public GpuScopeTimers(Driver driver,Clock clock,Sink sink,int capacity,int every,int maximum,long window) {
        if(capacity<1||capacity>32||every<1||maximum<1||maximum>1024||window<1||window>30_000_000_000L)
            throw new IllegalArgumentException("Invalid GPU timing budget");
        this.driver=driver;this.clock=clock;this.sink=sink;this.every=every;this.maximum=maximum;this.window=window;
        int bits=driver.current() ? driver.counterBits() : 0;
        supported=bits>=30&&bits<=64;
        slots=new Slot[capacity];for(int i=0;i<capacity;i++) slots[i]=new Slot();
    }
    public boolean supported() {return supported;}
    private void invalidate(String reason) {
        for(Slot slot:slots) if(slot.pending) slot.rejected=reason;
        if(active>=0) slots[active].rejected=reason;
    }
    private void checkDisjoint() {if(driver.disjoint()) invalidate("gpu_disjoint");}
    public void poll() {
        if(closed||!supported||active>=0) return;
        if(!driver.current()) {abandon("context_lost");return;}
        long elapsed=armed<0 ? 0 : clock.now()-armed;
        if(completed>=maximum||elapsed<0||elapsed>window+MAX_LATENCY_NANOS) {
            stop("capture_budget_finished");return;
        }
        checkDisjoint();
        for(Slot slot:slots) {
            if(!slot.pending) continue;
            long now=clock.now(),age=now-slot.begin;
            if(age<0||age>MAX_LATENCY_NANOS) slot.rejected="expired_or_reversed_clock";
            if(!driver.available(slot.query)) continue;
            long result=slot.rejected==null ? driver.result(slot.query) : -1;
            checkDisjoint();
            now=clock.now();age=now-slot.begin;
            if(age<0||age>MAX_LATENCY_NANOS) slot.rejected="expired_or_reversed_clock";
            if(slot.rejected==null&&(result<0||result>MAX_LATENCY_NANOS||result>age+100_000))
                slot.rejected="invalid_duration";
            emit(slot,now,slot.rejected==null ? result : -1);
        }
    }
    private void emit(Slot slot,long now,long result) {
        if(completed<maximum) {sink.sample(slot.stage,slot.identity,slot.begin,slot.recorded,now,result,slot.rejected);completed++;}
        slot.pending=false;
    }
    /** Zero means skipped. No query waits or forced GPU completion occur. */
    public int begin(int stage,long identity) {
        if(closed||!supported||active>=0) return 0;
        // Collection belongs to the caller's service point, outside producer
        // locks. Begin must not perform result reads or write sample reports.
        if(!driver.current()) {abandon("context_lost");return 0;}
        if(closed||completed>=maximum) return 0;
        long now=clock.now();
        if(armed>=0&&(now<armed||now-armed>window)) return 0;
        // A shared stride aliases a repeating pipeline: with two alternating
        // stages, every eighth call always selects the second one. Sample each
        // stage independently, with a bounded number of diagnostic counters.
        Integer previous=attempts.get(stage);
        if(previous==null&&attempts.size()>=32)return 0;
        int attempt=previous==null ? 1 : previous+1;
        attempts.put(stage,attempt==every ? 0 : attempt);
        if(attempt!=every||!driver.canBegin()) return 0;
        for(int i=0;i<slots.length;i++) {
            Slot slot=slots[i];if(slot.pending) continue;
            if(slot.query==0) slot.query=driver.create();
            if(slot.query==0) return 0;
            checkDisjoint();
            slot.stage=stage;slot.identity=identity;slot.begin=clock.now();slot.recorded=0;slot.rejected=null;
            if(armed<0) armed=slot.begin;
            driver.begin(slot.query);active=i;return i+1;
        }
        return 0;
    }
    public void end(int ticket) {
        if(ticket==0) return;
        if(closed||active!=ticket-1) throw new IllegalStateException("Mismatched GPU timing scope");
        if(!driver.current()) {abandon("context_lost");return;}
        Slot slot=slots[active];driver.end();slot.recorded=clock.now();slot.pending=true;
        active=-1;checkDisjoint();
    }
    private void abandon(String reason) {
        for(int i=0;i<slots.length;i++) {
            Slot slot=slots[i];
            if(slot.pending||i==active) {slot.rejected=reason;emit(slot,clock.now(),-1);}
        }
        active=-1;closed=true;
    }
    /** No GL calls after context loss. In-flight samples are never waited for. */
    private void stop(String reason) {
        if(closed) return;
        boolean current=driver.current();
        if(current&&active>=0) {driver.end();slots[active].pending=true;active=-1;}
        abandon(current ? reason : "context_lost");
        if(current) for(Slot slot:slots) if(slot.query!=0) driver.delete(slot.query);
    }
    public void close() {stop("closed_before_collection");}
}
