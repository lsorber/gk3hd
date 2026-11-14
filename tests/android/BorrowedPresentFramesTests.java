package org.gk3hd.standalone;

import java.util.HashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** The actual lease state machine, with a deterministic fake GPU backend. */
public final class BorrowedPresentFramesTests {
    private static int checks;
    private static void check(boolean value){if(!value)throw new AssertionError("Borrowed frame check "+checks);checks++;}
    static final class Fake implements BorrowedPresentFrames.Fences {
        long next;boolean failCreate;
        final HashMap<Long,Integer> states=new HashMap<>();
        int awaits,deletes;
        public synchronized long create(){if(failCreate)return 0;states.put(++next,0);return next;}
        public synchronized void await(long fence){check(states.containsKey(fence));awaits++;}
        public synchronized int status(long fence){Integer value=states.get(fence);if(value==null||value<0)throw new IllegalStateException("Failed fake GPU");return value;}
        public synchronized void delete(long fence){check(states.remove(fence)!=null);deletes++;}
        synchronized void ready(long fence){states.put(fence,1);}
    }
    public static void run() {
        Fake gpu=new Fake();BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(gpu,3);
        Object window=new Object(),different=new Object(),pixels=new Object();AtomicInteger idle=new AtomicInteger();
        check(queue.offer(window,pixels,1,128,17,false,11,23,37,idle::incrementAndGet));queue.poll();check(idle.get()==0);
        BorrowedPresentFrames.Frame frame=queue.take(window,128,17);check(frame!=null&&frame.sequence==1&&gpu.awaits==1);check(frame.windowId==11&&frame.pixmapId==23&&frame.presentSerial==37);
        queue.poll();check(idle.get()==0);queue.release(frame);queue.poll();check(idle.get()==0);
        try {queue.release(frame);throw new AssertionError("Read completed twice");}catch(IllegalStateException expected){checks++;}
        gpu.ready(2);queue.poll();check(idle.get()==1);queue.poll();check(idle.get()==1);
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet));
        check(queue.offer(different,pixels,2,128,17,false,0,0,0,idle::incrementAndGet));
        check(queue.offer(window,pixels,3,128,17,true,0,0,0,idle::incrementAndGet));
        check(!queue.offer(window,pixels,4,128,17,false,0,0,0,idle::incrementAndGet));
        frame=queue.take(window,128,17);check(frame.texture==3&&frame.flip&&frame.sequence==4);
        check(idle.get()==1);gpu.ready(3);gpu.ready(4);queue.poll();check(idle.get()==3);
        queue.release(frame);gpu.ready(6);queue.poll();check(idle.get()==4&&queue.counts()[3]==0);
        for(int i=0;i<256;i++) {
            check(queue.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet));
            frame=queue.take(window,128,17);queue.release(frame);gpu.ready(gpu.next);queue.poll();
            check(queue.counts()[3]==0);
        }
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet));
        frame=queue.take(window,128,17);int before=idle.get();queue.close();check(idle.get()==before&&gpu.states.isEmpty());
        check(!queue.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet));
        Fake failure=new Fake();queue=new BorrowedPresentFrames.Queue(failure,2);
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet));frame=queue.take(window,128,17);
        failure.failCreate=true;
        try {queue.release(frame);throw new AssertionError("Missing read fence accepted");}catch(IllegalStateException expected){checks++;}
        check(idle.get()==before);queue.close();
        Fake threaded=new Fake();final BorrowedPresentFrames.Queue cross=new BorrowedPresentFrames.Queue(threaded,2);
        Thread producer=new Thread(()->check(cross.offer(window,pixels,1,128,17,false,0,0,0,idle::incrementAndGet)));
        try {producer.start();producer.join(2000);}catch(InterruptedException error){throw new AssertionError(error);}
        check(!producer.isAlive());frame=cross.take(window,128,17);check(frame!=null);
        cross.release(frame);threaded.ready(2);cross.poll();check(idle.get()==before+1);cross.close();
        check(gpu.states.isEmpty()&&threaded.states.isEmpty());
        Fake deletion=new Fake();BorrowedPresentFrames.Queue retiring=new BorrowedPresentFrames.Queue(deletion,3);
        AtomicInteger disposed=new AtomicInteger();Object resource=new Object();
        check(!retiring.deferDestroy(resource,disposed::incrementAndGet));
        check(retiring.offer(window,resource,1,128,17,false,0,0,0,idle::incrementAndGet));
        check(retiring.offer(window,resource,1,128,17,false,0,0,0,idle::incrementAndGet));
        check(retiring.deferDestroy(resource,disposed::incrementAndGet));
        check(retiring.deferDestroy(resource,()->{throw new AssertionError("Duplicate destruction");}));
        check(disposed.get()==0);frame=retiring.take(window,128,17);
        deletion.ready(1);retiring.poll();check(disposed.get()==0);
        retiring.release(frame);retiring.poll();check(disposed.get()==0);
        deletion.ready(3);retiring.poll();check(disposed.get()==1);
        retiring.poll();check(disposed.get()==1);retiring.close();check(disposed.get()==1);
        check(retiring.counts()[3]==0);
        Fake cancelledGpu=new Fake();BorrowedPresentFrames.Queue cancelled=new BorrowedPresentFrames.Queue(cancelledGpu,1);
        check(cancelled.offer(window,resource,1,128,17,false,0,0,0,idle::incrementAndGet));
        check(cancelled.deferDestroy(resource,disposed::incrementAndGet));int idleBefore=idle.get();
        cancelled.close();check(disposed.get()==2&&idle.get()==idleBefore&&cancelledGpu.states.isEmpty());
        ordered();newestReady();unavailableProducers();retirementTimeout();
        System.out.println(checks+" borrowed source ownership/latest/FIFO/capacity/completion/thread checks passed");
    }
    private static void ordered() {
        Fake gpu=new Fake();BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(gpu,3,true);
        Object window=new Object(),pixels=new Object();AtomicInteger retired=new AtomicInteger(),destroyed=new AtomicInteger();
        for(int i=1;i<=3;i++)check(queue.offer(window,pixels,i,128,17,i==2,0,0,0,retired::incrementAndGet));
        check(!queue.offer(window,pixels,4,128,17,false,0,0,0,retired::incrementAndGet));
        check(queue.deferDestroy(pixels,destroyed::incrementAndGet));
        for(int i=1;i<=3;i++) {
            BorrowedPresentFrames.Frame frame=queue.take(window,128,17);
            check(frame!=null&&frame.texture==i&&frame.sequence==i&&frame.flip==(i==2));
            queue.release(frame);queue.poll();check(retired.get()==0&&destroyed.get()==0);
        }
        check(queue.take(window,128,17)==null&&queue.counts()[2]==0&&queue.counts()[3]==3);
        gpu.ready(4);gpu.ready(6);queue.poll();
        check(retired.get()==2&&destroyed.get()==0&&queue.counts()[3]==1);
        gpu.ready(5);queue.poll();check(retired.get()==3&&destroyed.get()==1);
        queue.close();check(gpu.states.isEmpty());

        gpu=new Fake();queue=new BorrowedPresentFrames.Queue(gpu,3,true);
        check(queue.offer(new Object(),pixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        check(queue.offer(window,pixels,2,128,17,true,0,0,0,retired::incrementAndGet));
        check(queue.offer(window,pixels,3,256,17,false,0,0,0,retired::incrementAndGet));
        BorrowedPresentFrames.Frame frame=queue.take(window,128,17);
        check(frame.texture==2&&frame.sequence==2&&frame.flip&&queue.counts()[2]==1);
        queue.release(frame);check(queue.take(window,128,17)==null&&queue.counts()[2]==2);
        gpu.ready(1);gpu.ready(3);gpu.ready(4);queue.poll();
        check(retired.get()==6&&queue.counts()[3]==0);queue.close();check(gpu.states.isEmpty());

        gpu=new Fake();queue=new BorrowedPresentFrames.Queue(gpu,3,true);
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        check(queue.offer(window,pixels,2,128,17,false,0,0,0,retired::incrementAndGet));
        check(queue.deferDestroy(pixels,destroyed::incrementAndGet));
        frame=queue.take(window,128,17);queue.release(frame);gpu.ready(3);queue.poll();
        check(retired.get()==7&&destroyed.get()==1); // Pending input still owns its backing.
        check(queue.take(window,128,17).texture==2);
        queue.close();check(retired.get()==7&&destroyed.get()==2&&gpu.states.isEmpty());
    }
    private static void newestReady() {
        Fake gpu=new Fake();
        BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(gpu,4,true,false,System::nanoTime,true);
        Object window=new Object();AtomicInteger retired=new AtomicInteger();
        for(int i=1;i<=4;i++)check(queue.offer(window,new Object(),i,128,17,false,0,0,i,retired::incrementAndGet));
        gpu.ready(2);
        BorrowedPresentFrames.Frame selected=queue.take(window,128,17);
        check(selected.sequence==2&&gpu.awaits==1&&queue.counts()[2]==1);
        queue.poll();check(retired.get()==0);
        gpu.ready(1);queue.poll();check(retired.get()==1);
        queue.release(selected);
        BorrowedPresentFrames.Frame pending=queue.take(window,128,17);
        check(pending.sequence==3&&gpu.awaits==2&&queue.counts()[2]==1);
        queue.release(pending);
        gpu.ready(4);
        BorrowedPresentFrames.Frame last=queue.take(window,128,17);
        check(last.sequence==4&&gpu.awaits==3);
        queue.release(last);
        queue.poll();check(retired.get()==1);
        gpu.ready(5);gpu.ready(6);gpu.ready(7);queue.poll();
        check(retired.get()==4&&queue.counts()[3]==0);
        queue.close();check(gpu.states.isEmpty());
    }
    private static void unavailableProducers() {
        Fake gpu=new Fake();BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(gpu,4,true);
        Object oldWindow=new Object(),newWindow=new Object(),oldPixels=new Object(),newPixels=new Object();
        AtomicInteger retired=new AtomicInteger(),destroyed=new AtomicInteger();
        check(queue.offer(oldWindow,oldPixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        BorrowedPresentFrames.Frame selected=queue.take(oldWindow,128,17);
        check(queue.offer(oldWindow,oldPixels,2,128,17,false,0,0,0,retired::incrementAndGet));
        check(queue.offer(newWindow,newPixels,3,128,17,false,0,0,0,retired::incrementAndGet));
        check(!queue.discardUnavailable(window->true)); // Paused production keeps a usable image.
        check(queue.counts()[3]==3&&retired.get()==0);
        check(queue.discardUnavailable(window->window==newWindow));
        check(queue.counts()[3]==3&&retired.get()==0); // Withdrawal is not GPU completion.
        gpu.ready(2);queue.poll();check(retired.get()==1&&queue.counts()[3]==2);
        queue.release(selected);queue.poll();check(retired.get()==1);
        gpu.ready(4);queue.poll();check(retired.get()==2);
        BorrowedPresentFrames.Frame fresh=queue.take(newWindow,128,17);check(fresh.texture==3);
        check(queue.deferDestroy(newPixels,destroyed::incrementAndGet));
        check(queue.discardUnavailable(window->true)); // Same window, backing withdrawn.
        check(destroyed.get()==0);queue.release(fresh);queue.poll();check(destroyed.get()==0);
        gpu.ready(5);queue.poll();check(retired.get()==3&&destroyed.get()==1&&queue.counts()[3]==0);
        check(!queue.discardUnavailable(window->false));queue.close();check(gpu.states.isEmpty());
    }
    private static void retirementTimeout() {
        Fake gpu=new Fake();
        AtomicLong time=new AtomicLong();
        BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(gpu,2,true,false,time::get);
        Object window=new Object(),pixels=new Object();
        AtomicInteger retired=new AtomicInteger(),disposed=new AtomicInteger();
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        BorrowedPresentFrames.Frame held=queue.take(window,128,17);
        time.set(20_000_000_000L);queue.poll(); // A held image need not be replaced while paused.
        check(retired.get()==0&&queue.counts()[3]==1);
        queue.release(held);
        check(queue.deferDestroy(pixels,disposed::incrementAndGet));
        time.set(24_999_999_999L);queue.poll();
        check(retired.get()==0&&disposed.get()==0);
        time.incrementAndGet();
        try {queue.poll();throw new AssertionError("Unsignaled read never timed out");}
        catch(RendererRecovery.StereoTimeout expected){checks++;}
        check(retired.get()==0&&disposed.get()==0&&queue.counts()[3]==1&&gpu.states.containsKey(2L));
        queue.close();
        check(retired.get()==0&&disposed.get()==1&&queue.counts()[3]==0&&gpu.states.isEmpty());

        queue=new BorrowedPresentFrames.Queue(gpu,2,true,false,time::get);
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        time.addAndGet(6_000_000_000L);
        queue.discardUnavailable(candidate->false);
        gpu.ready(3);queue.poll();
        check(retired.get()==1&&queue.counts()[3]==0);
        check(queue.offer(window,pixels,1,128,17,false,0,0,0,retired::incrementAndGet));
        time.addAndGet(5_000_000_000L);
        queue.discardUnavailable(candidate->false);
        try {queue.poll();throw new AssertionError("Withdrawn publication never timed out");}
        catch(RendererRecovery.StereoTimeout expected){checks++;}
        check(retired.get()==1&&queue.counts()[3]==1&&gpu.states.containsKey(4L));
        queue.close();
        check(retired.get()==1&&gpu.states.isEmpty());
    }
    public static void main(String[] arguments){run();}
}
