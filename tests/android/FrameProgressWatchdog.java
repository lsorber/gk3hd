package org.gk3hd.standalone;

import android.util.Log;
import java.util.Map;

/** Opt-in owned-process evidence only. Never resets the device or kills a thread. */
public final class FrameProgressWatchdog implements AutoCloseable {
    private volatile boolean closed,paused;
    private volatile String stage="waiting for first frame";
    private volatile long markedAt=System.nanoTime();
    private final Thread monitor;
    public FrameProgressWatchdog() {this(3_000_000_000L);}
    public FrameProgressWatchdog(long budgetNanos) {
        if(budgetNanos<500_000_000L||budgetNanos>3_000_000_000L)
            throw new IllegalArgumentException("Bounded diagnostic stall threshold required");
        monitor=new Thread(()-> {
            int captures=0;long nextCapture=0;
            while(!closed&&captures<3) {
                try {Thread.sleep(250);} catch(InterruptedException stop) {return;}
                long now=System.nanoTime(),age;String observedStage;
                synchronized(FrameProgressWatchdog.this) {
                    observedStage=stage;age=now-markedAt;
                    long limit=observedStage.equals("waiting for first frame") ? 20_000_000_000L : budgetNanos;
                    if(paused||age<limit||now<nextCapture) continue;
                }
                nextCapture=now+3_000_000_000L;captures++;
                Log.w("GK3HDXR","Frame watchdog stage="+observedStage+" age_ms="+age/1_000_000+" capture="+captures);
                dumpThreads("Frame progress deadline");
            }
        },"GK3HDTestProgress");
        monitor.setDaemon(true);monitor.start();
    }
    static void dumpThreads(String reason) {
        Log.w("GK3HDXR",reason);int count=0;
        java.util.ArrayList<Map.Entry<Thread,StackTraceElement[]>> entries=
            new java.util.ArrayList<>(Thread.getAllStackTraces().entrySet());
        entries.sort(java.util.Comparator.comparing(entry->!entry.getKey().getName().equals("main")));
        for(Map.Entry<Thread,StackTraceElement[]> entry:entries) {
            if(count++>=48)break;
            Thread thread=entry.getKey();
            StringBuilder text=new StringBuilder("Owned Java thread ").append(thread.getName()).append(" ").append(thread.getState());
            StackTraceElement[] frames=entry.getValue();
            for(int i=0;i<frames.length&&i<20;i++)text.append("\n  ").append(frames[i]);
            Log.w("GK3HDXR",text.toString());
        }
    }
    public synchronized void mark(String next) {stage=next;markedAt=System.nanoTime();}
    public synchronized void pause() {paused=true;}
    public synchronized void resume() {markedAt=System.nanoTime();paused=false;}
    @Override public void close() {closed=true;monitor.interrupt();}
}
