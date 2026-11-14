package org.gk3hd.standalone;
import java.util.HashMap;
import java.util.HashSet;

public final class OutputFenceTests {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("Output completion "+checks);}
    private static final class Fake implements OutputFenceTrace.Fences,OutputFenceTrace.Clock {
        long time=100,next=1;boolean invalid;final HashMap<Long,Integer> status=new HashMap<>();final HashSet<Long> deleted=new HashSet<>();
        public long now(){return time++;}
        public long create(){if(invalid)return 0;status.put(next,0);return next++;}
        public int status(long fence){return status.get(fence);}
        public void delete(long fence){check(status.containsKey(fence)&&deleted.add(fence));}
    }
    private static void fails(Runnable run){boolean failed=false;try{run.run();}catch(IllegalArgumentException|IllegalStateException expected){failed=true;}check(failed);}
    public static void main(String[] args) throws Exception {
        Fake f=new Fake();OutputFenceTrace trace=new OutputFenceTrace(f,f,2);
        check(trace.issue(1,1,Integer.MIN_VALUE,10,20,30));check(trace.issued()==1&&trace.pending()==1);
        check(!trace.issue(1,1,Integer.MIN_VALUE,10,20,30));check(trace.issued()==1);
        fails(()->trace.issue(1,1,7,10,20,30));fails(()->trace.issue(1,1,Integer.MIN_VALUE,11,20,30));
        trace.poll();check(trace.rows().length==0);long lastPending=f.time-2;
        trace.issue(1,2,-1,11,21,31);fails(()->trace.issue(1,3,3,12,22,32));
        // Completion is allowed out of order. Each fence retains its own pose.
        f.status.put(2L,1);trace.poll();long[][] rows=trace.rows();check(rows.length==1&&rows[0][1]==2&&rows[0][2]==0xffffffffL);
        String pending=trace.describePending();
        check(pending.contains("snapshot=1 pose=2147483648")&&!pending.contains("snapshot=2")&&pending.contains("polls=2"));
        check(trace.pending()==1&&trace.rows().length==1);
        f.status.put(1L,1);trace.poll();rows=trace.rows();check(rows.length==2&&rows[1][1]==1&&rows[1][2]==0x80000000L);
        check(rows[1][9]>=lastPending&&rows[1][11]>=rows[1][10]&&rows[1][12]==3);
        rows[1][1]=999;check(trace.rows()[1][1]==1);
        fails(()->trace.issue(1,1,1,10,20,30));fails(()->trace.issue(2,3,3,12,22,32));
        fails(()->trace.issue(1,3,3,30,20,40));
        boolean[] foreign={false};Thread t=new Thread(()->{try{trace.poll();}catch(IllegalStateException expected){foreign[0]=true;}});t.start();t.join();check(foreign[0]);
        trace.close();check(f.deleted.size()==2);fails(trace::poll);
        Fake bad=new Fake();bad.invalid=true;OutputFenceTrace unavailable=new OutputFenceTrace(bad,bad,2);fails(()->unavailable.issue(1,1,1,1,2,3));unavailable.close();
        Fake error=new Fake();OutputFenceTrace failed=new OutputFenceTrace(error,error,2);failed.issue(1,1,1,1,2,3);error.status.put(1L,-1);fails(failed::poll);failed.close();check(error.deleted.size()==1);
        System.out.println(checks+" exact-output completion/order/capacity/error/thread/lifetime checks passed");
    }
}
