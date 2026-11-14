package org.gk3hd.standalone;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Reader ownership, pause/recovery and failure behavior; no headset or timed FPS test. */
public final class TrackingWorkerTests {
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static void await(CountDownLatch event)throws InterruptedException {
        require(event.await(2,TimeUnit.SECONDS),"Reader callback did not progress");
    }
    private static void sessions()throws Exception {
        AtomicInteger first=new AtomicInteger(),second=new AtomicInteger();
        try(TrackingWorker worker=new TrackingWorker(1000)) {
            CountDownLatch firstReady=new CountDownLatch(2);
            worker.activate(()-> {first.incrementAndGet();firstReady.countDown();});await(firstReady);
            worker.deactivate();int retired=first.get();
            CountDownLatch secondReady=new CountDownLatch(2);
            worker.activate(()-> {second.incrementAndGet();secondReady.countDown();});await(secondReady);
            worker.deactivate();require(first.get()==retired,"Retired session was sampled again");
            require(second.get()>=2,"New native session did not resume sampling");
        }
    }
    private static void retirementWaits()throws Exception {
        TrackingWorker worker=new TrackingWorker(1000);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        boolean unsafeRetirement=false;
        try {
            worker.activate(()-> {entered.countDown();release.await();});await(entered);
            try {worker.deactivate(1,TimeUnit.MILLISECONDS);unsafeRetirement=true;}
            catch(IllegalStateException expected) {}
            require(!unsafeRetirement,"Session retirement succeeded while native callback was still active");
        } finally {release.countDown();worker.close();}
        try {worker.activate(()-> {});throw new AssertionError("Closed reader accepted a session");}
        catch(IllegalStateException expected) {}
    }
    private static void failureIsVisible()throws Exception {
        Throwable original=new AssertionError("owned native callback failure");
        CountDownLatch entered=new CountDownLatch(1);
        try(TrackingWorker worker=new TrackingWorker(1000)) {
            worker.activate(()-> {entered.countDown();throw (AssertionError)original;});await(entered);
            worker.deactivate();
            try {worker.checkFailure();throw new AssertionError("Reader failure was lost");}
            catch(IllegalStateException expected) {require(expected.getCause()==original,"Native failure cause was replaced");}
        }
    }
    public static void main(String[] args)throws Exception {
        sessions();retirementWaits();failureIsVisible();
        System.out.println("Tracking worker session, retirement and failure checks passed");
    }
}
