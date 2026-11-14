package org.gk3hd.standalone;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Native-query stand-ins exercise real history/worker code, without a headset. */
public final class TrackingAdmissionTests {
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static void await(CountDownLatch event)throws InterruptedException {
        require(event.await(2,TimeUnit.SECONDS),"Tracking admission did not progress");
    }
    private static void boundaries() {
        FramePoses<Object> poses=new FramePoses<>();poses.focused(true);
        Object original=new Object();long time=1_000_000_000L;
        long generation=poses.samplingGeneration();
        poses.focused(true);poses.beginEpoch(0);
        require(poses.rememberIfCurrent(generation,1,original,3,time),"Unchanged state rejected a native query");
        require(poses.matchImage(1,101,time+1)==original,"Native pose identity changed");
        require(poses.inputsCurrent(time+249_000_000L),"Original sample expired early");
        require(!poses.inputsCurrent(time+251_000_000L),"Query completion renewed the original sample time");
        for(int boundary=0;boundary<4;boundary++) {
            generation=poses.samplingGeneration();
            switch(boundary) {
                case 0:poses.focused(false);poses.focused(true);break;
                case 1:poses.clear();break;
                case 2:poses.beginEpoch(17);break;
                default:poses.remember(99,null,0,time+2);break;
            }
            require(!poses.rememberIfCurrent(generation,2,original,3,time+3),"Crossed query revived after boundary "+boundary);
            require(poses.matchImage(2,102,time+4)==null,"Rejected query acquired image ownership");
            require(!poses.inputsCurrent(time+4),"Rejected query restored actions");
            Object recovery=new Object();generation=poses.samplingGeneration();
            require(poses.rememberIfCurrent(generation,3,recovery,3,time+5),"Fresh native query did not recover");
            require(poses.matchImage(3,103,time+6)==recovery&&poses.inputsCurrent(time+6),"Fresh pixels did not recover actions");
        }
        generation=poses.samplingGeneration();
        require(poses.rememberIfCurrent(generation,4,null,0,time+7),"Actual tracking loss was hidden");
        require(poses.matchImage(3,103,time+8)==null,"Invalid native flags retained valid pixels");
        generation=poses.samplingGeneration();
        require(poses.rememberIfCurrent(generation,5,original,1,time+9),"Real orientation-only query was rejected");
        require(poses.matchImage(5,105,time+10)==original,"Orientation-only identity was lost");
    }
    private static void focusDuringQuery()throws Exception {
        FramePoses<Object> poses=new FramePoses<>();poses.focused(true);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),returned=new CountDownLatch(1);
        AtomicInteger publications=new AtomicInteger();
        try(TrackingWorker worker=new TrackingWorker(360)) {
            worker.activate(()-> {
                long generation=poses.samplingGeneration();Object pose=new Object();long sampled=System.nanoTime();
                entered.countDown();release.await();
                if(poses.rememberIfCurrent(generation,1,pose,3,sampled))publications.incrementAndGet();
                returned.countDown();
            });
            try {
                await(entered);
                poses.focused(false);poses.focused(true);
                // Timeout leaves the real callback live, rather than claiming a clean pause.
                try {worker.deactivate(1,TimeUnit.MILLISECONDS);throw new AssertionError("Live query retired early");}
                catch(IllegalStateException expected) {}
            } finally {release.countDown();}
            await(returned);worker.deactivate();
            require(publications.get()==0,"A query spanning loss/regain reached publication");
            CountDownLatch recovered=new CountDownLatch(1);
            worker.activate(()-> {
                long generation=poses.samplingGeneration();Object pose=new Object();long sampled=System.nanoTime();
                if(poses.rememberIfCurrent(generation,2,pose,3,sampled))publications.incrementAndGet();
                recovered.countDown();
            });
            await(recovered);worker.deactivate();
            require(publications.get()>0,"Reader did not recover with a fresh query");
        }
    }
    public static void main(String[] args)throws Exception {
        boundaries();focusDuringQuery();
        System.out.println("Tracking admission: crossed focus/reset/space/loss rejected; original identity/time, recovery and worker retirement passed");
    }
}
