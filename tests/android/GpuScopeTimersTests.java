package org.gk3hd.standalone;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;

public final class GpuScopeTimersTests {
    private static int checks;
    private static void check(boolean value,String message) {checks++;if(!value) throw new AssertionError(message);}
    private static final class Driver implements GpuScopeTimers.Driver,GpuScopeTimers.Clock,GpuScopeTimers.Sink {
        boolean current=true,ready,disjoint,external,disjointOnRead;
        int bits=64,next,active,reads,deletes,creates;
        long now=1,result=1000;
        final List<String> status=new ArrayList<>();
        final List<Long> identities=new ArrayList<>();
        final List<Integer> stages=new ArrayList<>();
        final HashMap<Integer,Boolean> pending=new HashMap<>();
        public boolean current() {return current;}
        public int counterBits() {return bits;}
        public boolean canBegin() {return !external;}
        public int create() {creates++;return ++next;}
        public void begin(int query) {check(active==0,"Queries nested");active=query;pending.put(query,false);}
        public void end() {check(active!=0,"No active query");pending.put(active,true);active=0;}
        public boolean disjoint() {boolean out=disjoint;disjoint=false;return out;}
        public boolean available(int query) {check(Boolean.TRUE.equals(pending.get(query)),"Unended query polled");return ready;}
        public long result(int query) {check(ready,"Blocking result request");reads++;if(disjointOnRead)disjoint=true;return result;}
        public void delete(int query) {check(current,"Delete in wrong context");deletes++;}
        public long now() {return now;}
        public void sample(int stage,long identity,long begin,long end,long collected,long nanos,String rejected) {
            check(rejected!=null||end>=begin&&collected>=end&&nanos>=0,"Invalid accepted sample");
            status.add(rejected==null ? "ok" : rejected);identities.add(identity);stages.add(stage);
        }
        GpuScopeTimers timer(int capacity,int every,int maximum,long window) {
            return new GpuScopeTimers(this,this,this,capacity,every,maximum,window);
        }
        void later() {now+=1_000_000;ready=true;}
    }
    public static void main(String[] args) {
        Driver d=new Driver();GpuScopeTimers t=d.timer(2,1,10,1_000_000_000);
        int ticket=t.begin(1,42);check(ticket!=0,"Supported scope skipped");
        check(t.begin(2,9)==0,"Nested scope accepted");t.end(ticket);t.poll();
        check(d.reads==0&&d.status.isEmpty(),"Unavailable sample read");
        d.later();t.poll();check(d.status.size()==1&&d.status.get(0).equals("ok")&&d.identities.get(0)==42,"Identity/result changed");
        t.close();check(d.deletes==1,"Owned query not retired");
        d=new Driver();d.bits=0;t=d.timer(1,1,10,1_000_000_000);
        check(!t.supported()&&t.begin(1,1)==0&&d.creates==0,"Unsupported query allocated");t.close();
        d=new Driver();t=d.timer(2,1,10,1_000_000_000);
        ticket=t.begin(1,1);t.end(ticket);ticket=t.begin(1,2);t.end(ticket);
        check(t.begin(1,3)==0&&d.creates==2,"Pending slots reused or unbounded");
        d.disjoint=true;d.later();t.poll();check(d.reads==0&&d.status.size()==2&&d.status.get(0).equals("gpu_disjoint"),"Disjoint batch accepted");t.close();
        d=new Driver();t=d.timer(1,1,10,1_000_000_000);
        ticket=t.begin(1,4);t.end(ticket);d.now+=GpuScopeTimers.MAX_LATENCY_NANOS+1;t.poll();
        check(t.begin(1,5)==0,"Expired unfinished query recycled");d.ready=true;t.poll();
        check(d.reads==0&&d.status.get(0).equals("expired_or_reversed_clock"),"Overflow-prone query accepted");t.close();
        d=new Driver();t=d.timer(1,1,10,1_000_000_000);
        ticket=t.begin(1,6);t.end(ticket);d.current=false;t.poll();
        check(d.status.get(0).equals("context_lost")&&d.reads==0&&d.deletes==0,"Lost context accessed");
        d=new Driver();t=d.timer(1,1,10,1_000_000_000);
        ticket=t.begin(1,7);t.end(ticket);d.later();d.result=0xffffffffL;t.poll();
        check(d.status.get(0).equals("invalid_duration"),"Truncated timer accepted");t.close();
        d=new Driver();t=d.timer(1,2,1,1_000_000_000);
        check(t.begin(1,8)==0,"Sampling budget ignored");ticket=t.begin(1,9);t.end(ticket);d.later();t.poll();
        check(t.begin(1,10)==0&&d.status.size()==1,"Result budget exceeded");t.close();
        d=new Driver();t=d.timer(2,8,20,1_000_000_000);
        for(int cycle=0;cycle<24;cycle++)for(int stage=1;stage<=4;stage++) {
            ticket=t.begin(stage,cycle*4+stage);
            if(ticket!=0){t.end(ticket);d.later();t.poll();}
        }
        for(int stage=1;stage<=4;stage++)check(java.util.Collections.frequency(d.stages,stage)==3,
            "A repeating pipeline stage was omitted or sampled disproportionately");
        t.close();
        d=new Driver();t=d.timer(1,1,10,10);
        ticket=t.begin(1,11);t.end(ticket);d.now+=20;
        check(t.begin(1,12)==0,"Capture window exceeded");t.close();
        d=new Driver();d.external=true;t=d.timer(1,1,10,1_000_000_000);
        check(t.begin(1,13)==0&&d.creates==0,"External query disturbed");t.close();
        d=new Driver();t=d.timer(2,1,10,1_000_000_000);
        ticket=t.begin(1,14);t.end(ticket);d.later();
        ticket=t.begin(2,15);check(d.reads==0&&d.status.isEmpty(),"Begin performed result collection inside a producer lock");t.end(ticket);t.close();
        d=new Driver();t=d.timer(1,1,10,1_000_000_000);
        ticket=t.begin(1,16);t.end(ticket);d.later();d.disjointOnRead=true;t.poll();
        check(d.status.get(0).equals("gpu_disjoint"),"Disjoint during collection accepted");t.close();
        d=new Driver();t=d.timer(1,1,10,1000);
        ticket=t.begin(1,17);t.end(ticket);d.now+=GpuScopeTimers.MAX_LATENCY_NANOS+1001;t.poll();
        check(d.deletes==1&&d.reads==0&&t.begin(1,18)==0,"Profiling continued beyond its bounded window");
        for(int bits:new int[]{0,29,65}) {
            d=new Driver();d.bits=bits;t=d.timer(1,1,10,1_000_000_000);
            check(!t.supported()&&t.begin(1,19)==0&&d.creates==0,"Unsupported counter width accepted");t.close();
        }
        for(int i=0;i<1000;i++) {
            d=new Driver();t=d.timer(1,1,2,1_000_000_000);
            ticket=t.begin(1,i);t.end(ticket);d.later();t.poll();
            ticket=t.begin(2,~i);t.end(ticket);d.now+=1_000_000;t.poll();
            check(d.identities.size()==2&&d.identities.get(0)==i&&d.identities.get(1)==~i,"Reused query returned stale identity");t.close();
        }
        System.out.println("GPU scope policy passed: "+checks+" checks; asynchronous availability, identity, disjoint, bounds, expiry and context loss");
    }
}
