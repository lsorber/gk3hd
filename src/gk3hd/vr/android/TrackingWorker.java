package org.gk3hd.standalone;

import java.util.concurrent.TimeUnit;

/** Session-owned input reader. Construct before a vendor changes thread scheduling. */
final class TrackingWorker implements AutoCloseable {
    interface Sampler {void sample() throws Exception;}
    private final Object lock=new Object();
    private final Thread thread;
    private final long period;
    private Sampler sampler;
    private boolean closed,inFlight;
    private volatile Throwable failure;

    TrackingWorker(int hz) {
        if(hz<30||hz>1000)throw new IllegalArgumentException("Unsupported tracking cadence");
        period=1_000_000_000L/hz;
        thread=new Thread(this::run,"GK3HDTracking");thread.setDaemon(true);thread.start();
    }
    void activate(Sampler next) {
        if(next==null)throw new IllegalArgumentException("Missing native sampler");
        synchronized(lock) {
            checkFailure();
            if(closed||sampler!=null||inFlight)throw new IllegalStateException("Tracking reader is not idle");
            sampler=next;lock.notifyAll();
        }
    }
    void checkFailure() {
        Throwable error=failure;
        if(error!=null)throw new IllegalStateException("Native tracking reader failed",error);
    }
    private void run() {
        long next=0;
        try {
            while(true) {
                Sampler current;
                synchronized(lock) {
                    while(!closed&&sampler==null) {next=0;lock.wait();}
                    if(closed)return;
                    if(next==0)next=System.nanoTime();
                    long remaining=next-System.nanoTime();
                    if(remaining>0) {TimeUnit.NANOSECONDS.timedWait(lock,remaining);continue;}
                    current=sampler;inFlight=true;
                }
                try {current.sample();}
                catch(Throwable error) {
                    failure=error;
                    synchronized(lock) {sampler=null;}
                } finally {
                    synchronized(lock) {inFlight=false;lock.notifyAll();}
                }
                long now=System.nanoTime();
                do {next+=period;}while(next<=now);
            }
        } catch(InterruptedException error) {
            failure=error;Thread.currentThread().interrupt();
        } finally {
            synchronized(lock) {inFlight=false;lock.notifyAll();}
        }
    }
    /** Do not end a native session until its last reader callback has returned. */
    void deactivate() {deactivate(2,TimeUnit.SECONDS);}
    void deactivate(long duration,TimeUnit unit) {
        long until=System.nanoTime()+unit.toNanos(duration);
        synchronized(lock) {
            sampler=null;lock.notifyAll();
            while(inFlight) {
                long remaining=until-System.nanoTime();
                if(remaining<=0)throw new IllegalStateException("Native tracking reader is still using its session");
                try {TimeUnit.NANOSECONDS.timedWait(lock,remaining);}
                catch(InterruptedException error) {Thread.currentThread().interrupt();throw new IllegalStateException("Tracking retirement interrupted",error);}
            }
        }
    }
    @Override public void close() {
        synchronized(lock) {closed=true;sampler=null;lock.notifyAll();}
        try {thread.join(2000);}
        catch(InterruptedException error) {Thread.currentThread().interrupt();throw new IllegalStateException("Tracking reader join interrupted",error);}
        if(thread.isAlive())throw new IllegalStateException("Native tracking reader has not retired");
    }
}
