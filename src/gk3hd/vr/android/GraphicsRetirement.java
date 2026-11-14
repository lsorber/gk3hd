package org.gk3hd.standalone;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Execute cleanup once, even when inline failure cleanup overtakes queued teardown. */
final class GraphicsRetirement {
    private final AtomicBoolean started=new AtomicBoolean();
    private final CountDownLatch complete=new CountDownLatch(1);
    void run(Runnable cleanup) {
        if(!started.compareAndSet(false,true))return;
        try {cleanup.run();} finally {complete.countDown();}
    }
    boolean await(long duration,TimeUnit unit) throws InterruptedException {
        return complete.await(duration,unit);
    }
}
