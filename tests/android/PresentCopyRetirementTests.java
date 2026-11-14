package org.gk3hd.standalone;

import java.util.HashMap;
import java.util.concurrent.atomic.AtomicInteger;

public final class PresentCopyRetirementTests {
    private static int checks;
    private static void check(boolean value){if(!value)throw new AssertionError("Present retirement check "+checks);++checks;}
    static final class Fake implements PresentCopyRetirement.Fences {
        long next;boolean failCreate;
        final HashMap<Long,Integer> states=new HashMap<>();
        int deleted;
        public synchronized long create(){if(failCreate)return 0;states.put(++next,PresentCopyRetirement.WAITING);return next;}
        public synchronized int status(long fence){return states.getOrDefault(fence,PresentCopyRetirement.FAILED);}
        public synchronized void delete(long fence){check(states.remove(fence)!=null);++deleted;}
        synchronized void ready(long fence){states.put(fence,PresentCopyRetirement.READY);}
    }
    public static void run() {
        Fake backend=new Fake();PresentCopyRetirement.Queue queue=new PresentCopyRetirement.Queue(backend,2);
        AtomicInteger callbacks=new AtomicInteger();
        check(queue.defer(callbacks::incrementAndGet));queue.poll();check(callbacks.get()==0);
        check(queue.defer(callbacks::incrementAndGet));check(!queue.defer(callbacks::incrementAndGet));
        backend.ready(2);queue.poll();check(callbacks.get()==1&&queue.outstanding()==1);
        backend.ready(1);queue.poll();check(callbacks.get()==2&&queue.outstanding()==0);
        queue.poll();check(callbacks.get()==2);
        backend.failCreate=true;check(!queue.defer(callbacks::incrementAndGet));backend.failCreate=false;
        for(int i=0;i<256;i++) {
            check(queue.defer(callbacks::incrementAndGet));
            backend.ready(backend.next);queue.poll();check(queue.outstanding()==0);
        }
        check(queue.submitted==queue.completed);
        check(queue.defer(callbacks::incrementAndGet));queue.poll();
        int before=callbacks.get();queue.close();check(callbacks.get()==before&&queue.outstanding()==0&&queue.cancelled==1);
        check(!queue.defer(callbacks::incrementAndGet));check(backend.states.isEmpty());
        Fake failed=new Fake();queue=new PresentCopyRetirement.Queue(failed,2);
        check(queue.defer(callbacks::incrementAndGet));failed.states.put(1L,PresentCopyRetirement.FAILED);
        try {queue.poll();throw new AssertionError("Failed fence was accepted");}catch(IllegalStateException expected){checks++;}
        check(callbacks.get()==before);queue.close();check(failed.states.isEmpty());
        Fake threaded=new Fake();final PresentCopyRetirement.Queue cross=new PresentCopyRetirement.Queue(threaded,2);
        Thread producer=new Thread(()->check(cross.defer(callbacks::incrementAndGet)));
        try {producer.start();producer.join(2000);}catch(InterruptedException error){throw new AssertionError(error);}
        check(!producer.isAlive());threaded.ready(1);cross.poll();check(callbacks.get()==before+1);cross.close();
        Fake wrongThread=new Fake();PresentCopyRetirement.Queue owned=new PresentCopyRetirement.Queue(wrongThread,2);
        check(owned.defer(callbacks::incrementAndGet));
        AtomicInteger rejected=new AtomicInteger();
        Thread stranger=new Thread(()-> {
            try {owned.poll();}catch(IllegalStateException expected){rejected.incrementAndGet();}
            try {owned.close();}catch(IllegalStateException expected){rejected.incrementAndGet();}
        });
        try {stranger.start();stranger.join(2000);}catch(InterruptedException error){throw new AssertionError(error);}
        check(!stranger.isAlive()&&rejected.get()==2&&owned.outstanding()==1);
        owned.close();owned.close();check(wrongThread.deleted==1);
        // Stop can race a producer creating a fence outside the queue lock.
        Fake racing=new Fake();
        java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch proceed=new java.util.concurrent.CountDownLatch(1);
        PresentCopyRetirement.Fences blocked=new PresentCopyRetirement.Fences() {
            public long create() {
                entered.countDown();
                try {if(!proceed.await(2,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Creation race timed out");}
                catch(InterruptedException error){throw new AssertionError(error);}
                return racing.create();
            }
            public int status(long fence){return racing.status(fence);}
            public void delete(long fence){racing.delete(fence);}
        };
        PresentCopyRetirement.Queue raced=new PresentCopyRetirement.Queue(blocked,2);
        AtomicInteger accepted=new AtomicInteger();
        java.util.concurrent.atomic.AtomicReference<Throwable> producerError=new java.util.concurrent.atomic.AtomicReference<>();
        Thread inFlight=new Thread(()-> {
            try {if(raced.defer(callbacks::incrementAndGet))accepted.incrementAndGet();}
            catch(Throwable error){producerError.set(error);}
        });
        try {
            inFlight.start();check(entered.await(2,java.util.concurrent.TimeUnit.SECONDS));
            raced.close();proceed.countDown();inFlight.join(2000);
        }catch(InterruptedException error){throw new AssertionError(error);}
        check(!inFlight.isAlive()&&producerError.get()==null&&accepted.get()==0);
        check(raced.outstanding()==0&&racing.deleted==1&&racing.states.isEmpty());
        Fake callbackFailure=new Fake();PresentCopyRetirement.Queue resilient=new PresentCopyRetirement.Queue(callbackFailure,2);
        AtomicInteger attempted=new AtomicInteger();
        check(resilient.defer(()-> {attempted.incrementAndGet();throw new IllegalStateException("Callback failed");}));
        check(resilient.defer(callbacks::incrementAndGet));callbackFailure.ready(1);callbackFailure.ready(2);
        try {resilient.poll();throw new AssertionError("Callback failure hidden");}catch(IllegalStateException expected){checks++;}
        check(attempted.get()==1&&resilient.outstanding()==1);
        resilient.poll();check(attempted.get()==1&&resilient.outstanding()==0);resilient.close();
        System.out.println(checks+" bounded present retirement readiness/capacity/failure/cancellation/thread checks passed");
    }
    public static void main(String[] arguments){run();}
}
