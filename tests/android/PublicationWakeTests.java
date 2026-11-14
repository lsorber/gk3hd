package org.gk3hd.standalone;

import java.util.concurrent.atomic.AtomicReference;

/** Publication notification changes scheduling, never image ownership or fences. */
public final class PublicationWakeTests {
    private static int checks;
    private static void check(boolean okay,String reason){checks++;if(!okay)throw new AssertionError(reason);}
    public static void main(String[] args)throws Exception {
        BorrowedPresentFrames.Fences fences=new BorrowedPresentFrames.Fences(){
            long next;public long create(){return ++next;}public void await(long fence){}
            public int status(long fence){return 1;}public void delete(long fence){}
        };
        BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(fences,2,true);
        Object window=new Object(),backing=new Object();Thread reader=Thread.currentThread();
        AtomicReference<Throwable> error=new AtomicReference<>();
        Thread producer=new Thread(()-> {
            try {
                long end=System.nanoTime()+1_000_000_000L;
                while(reader.getState()!=Thread.State.TIMED_WAITING) {
                    if(System.nanoTime()>end)throw new AssertionError("Reader never waited for publication");
                    Thread.yield();
                }
                if(!queue.offer(window,backing,1,128,17,false,0,0,0,()->{}))throw new AssertionError("Publication rejected");
            }catch(Throwable failure){error.set(failure);}
        });
        producer.start();long begin=System.nanoTime();
        long observed=queue.awaitPublication(0,begin+500_000_000L),elapsed=System.nanoTime()-begin;
        producer.join(1000);check(!producer.isAlive()&&error.get()==null,"Producer did not complete");
        check(observed==1&&elapsed<250_000_000L,"A publication did not wake the waiting reader");
        check(queue.counts()[3]==1,"Wakeup retired a still-owned image");
        check(queue.awaitPublication(0,System.nanoTime()+100_000_000L)==1,"Existing publication should not wait");
        begin=System.nanoTime();check(queue.awaitPublication(1,begin+2_000_000L)==1,"Empty wait invented an image");
        check(System.nanoTime()-begin<100_000_000L,"Empty wait exceeded its finite deadline");
        Thread.currentThread().interrupt();boolean interrupted=false;
        try {queue.awaitPublication(1,System.nanoTime()+100_000_000L);}catch(InterruptedException expected){interrupted=true;}
        check(interrupted&&!Thread.currentThread().isInterrupted(),"Interrupted wait was swallowed");
        queue.close();check(queue.awaitPublication(1,System.nanoTime()+100_000_000L)==1,"Closed queue should not wait");
        System.out.println(checks+" publication notification, bounded wait, interruption and ownership checks passed");
    }
}
