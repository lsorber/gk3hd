package org.gk3hd.standalone;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public final class GraphicsRetirementTests {
    private static int checks;
    private static void check(boolean value) {
        checks++;if(!value)throw new AssertionError("Graphics retirement contract failed");
    }
    public static void main(String[] arguments) throws Exception {
        GraphicsRetirement gate=new GraphicsRetirement();
        AtomicInteger count=new AtomicInteger();
        Runnable queued=()->gate.run(count::incrementAndGet);
        check(!gate.await(0,TimeUnit.SECONDS));
        // The owner has queued teardown, but a fatal draw gets there first.
        gate.run(count::incrementAndGet);queued.run();queued.run();
        check(count.get()==1&&gate.await(0,TimeUnit.SECONDS));
        for(int attempt=0;attempt<16;attempt++) {
            GraphicsRetirement concurrent=new GraphicsRetirement();
            CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
            AtomicInteger executions=new AtomicInteger();
            AtomicReference<Throwable> failure=new AtomicReference<>();
            Thread winner=new Thread(()-> {
                try {concurrent.run(()-> {
                    executions.incrementAndGet();entered.countDown();
                    try {if(!release.await(2,TimeUnit.SECONDS))throw new AssertionError("Test release missing");}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new AssertionError(error);}
                });} catch(Throwable error){failure.set(error);}
            });
            winner.start();check(entered.await(2,TimeUnit.SECONDS));
            check(!concurrent.await(0,TimeUnit.SECONDS));
            concurrent.run(()-> {throw new AssertionError("Second cleanup executed");});
            check(!concurrent.await(0,TimeUnit.SECONDS));
            release.countDown();winner.join(2000);check(!winner.isAlive());
            check(failure.get()==null&&executions.get()==1&&concurrent.await(0,TimeUnit.SECONDS));
        }
        GraphicsRetirement failed=new GraphicsRetirement();
        IllegalStateException expected=new IllegalStateException("Owned cleanup failure");
        try {failed.run(()-> {throw expected;});throw new AssertionError("Failure hidden");}
        catch(IllegalStateException actual){check(actual==expected);}
        check(failed.await(0,TimeUnit.SECONDS));
        failed.run(()-> {throw new AssertionError("Failed cleanup retried");});
        System.out.println("Graphics retirement: "+checks+" execution, completion and failure checks passed");
    }
}
