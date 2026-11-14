package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.function.LongSupplier;
import java.util.function.Predicate;

/** Retain a stereo pixmap for the exact destination drawable until its GPU read finishes. */
public final class BorrowedPresentFrames {
    interface Fences {long create();void await(long fence);int status(long fence);void delete(long fence);}
    static final Fences GL=new Fences() {
        public long create(){long fence=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);if(fence!=0)GLES30.glFlush();return fence;}
        public void await(long fence){GLES30.glWaitSync(fence,0,GLES30.GL_TIMEOUT_IGNORED);}
        public int status(long fence) {
            int value=GLES30.glClientWaitSync(fence,0,0);
            if(value==GLES30.GL_TIMEOUT_EXPIRED)return 0;
            if(value==GLES30.GL_ALREADY_SIGNALED||value==GLES30.GL_CONDITION_SATISFIED)return 1;
            throw new IllegalStateException("Borrowed source completion failed");
        }
        public void delete(long fence){GLES30.glDeleteSync(fence);}
    };
    public static final class Frame {
        final Object target,keepAlive;
        public final int texture,width,height,windowId,pixmapId,presentSerial;
        public final boolean flip;
        public final long sequence;
        long offeredAt,takeBegin,takeEnd;
        private final Queue owner;
        private final Runnable retired;
        private long fence,fenceStartedAt;
        private int state; // 0 pending, 1 acquired, 2 retiring, 3 complete/cancelled
        Frame(Queue owner,Object target,Object keepAlive,int texture,int width,int height,boolean flip,long sequence,long fence,int windowId,int pixmapId,int presentSerial,Runnable retired) {
            this.owner=owner;this.target=target;this.keepAlive=keepAlive;this.texture=texture;this.width=width;this.height=height;
            this.flip=flip;this.windowId=windowId;this.pixmapId=pixmapId;this.presentSerial=presentSerial;this.sequence=sequence;this.fence=fence;this.retired=retired;
        }
    }
    static final class Queue {
        private final Fences fences;
        private final int limit;
        private final boolean oldestFirst;
        private final boolean preferNewestReady;
        private final boolean measureTiming;
        private final LongSupplier clock;
        private final Thread reader=Thread.currentThread();
        private final ArrayDeque<Frame> pending=new ArrayDeque<>();
        private final ArrayList<Frame> acquired=new ArrayList<>(),retiring=new ArrayList<>();
        private final IdentityHashMap<Object,Runnable> disposals=new IdentityHashMap<>();
        private boolean closing;
        private int outstanding;
        private long sequence,completed,dropped;
        Queue(Fences fences,int limit){this(fences,limit,false);}
        Queue(Fences fences,int limit,boolean oldestFirst){this(fences,limit,oldestFirst,false);}
        Queue(Fences fences,int limit,boolean oldestFirst,boolean measureTiming){
            this(fences,limit,oldestFirst,measureTiming,System::nanoTime);
        }
        Queue(Fences fences,int limit,boolean oldestFirst,boolean measureTiming,LongSupplier clock){
            this(fences,limit,oldestFirst,measureTiming,clock,false);
        }
        Queue(Fences fences,int limit,boolean oldestFirst,boolean measureTiming,LongSupplier clock,boolean preferNewestReady){
            if(fences==null||limit<1||limit>8)throw new IllegalArgumentException("Invalid borrowed-source bound");
            if(preferNewestReady&&!oldestFirst)throw new IllegalArgumentException("Ready selection requires an ordered queue");
            this.fences=fences;this.limit=limit;this.oldestFirst=oldestFirst;this.measureTiming=measureTiming;
            this.preferNewestReady=preferNewestReady;
            this.clock=clock;
        }
        private void readerOnly(){if(Thread.currentThread()!=reader)throw new IllegalStateException("Borrowed source requires its consuming GL thread");}
        boolean offer(Object target,Object keepAlive,int texture,int width,int height,boolean flip,int windowId,int pixmapId,int presentSerial,Runnable retired) {
            if(target==null||keepAlive==null||texture<=0||width<96||height<2||width>8192||height>8192||retired==null)
                throw new IllegalArgumentException("Invalid borrowed source");
            synchronized(this){if(closing||outstanding>=limit)return false;}
            long ready=fences.create();if(ready==0)throw new IllegalStateException("Borrowed source publication fence unavailable");
            synchronized(this) {
                if(!closing&&outstanding<limit) {
                    Frame frame=new Frame(this,target,keepAlive,texture,width,height,flip,++sequence,ready,windowId,pixmapId,presentSerial,retired);
                    frame.fenceStartedAt=clock.getAsLong();
                    frame.offeredAt=measureTiming ? frame.fenceStartedAt : 0;pending.addLast(frame);
                    outstanding++;notifyAll();return true;
                }
            }
            fences.delete(ready);return false;
        }
        Frame take(Object target,int width,int height) {
            readerOnly();Frame selected=null;
            synchronized(this) {
                if(closing)return null;
                Frame preferred=null;
                if(preferNewestReady&&pending.size()>1) {
                    for(Iterator<Frame> candidates=pending.descendingIterator();candidates.hasNext();) {
                        Frame candidate=candidates.next();
                        if(candidate.target==target&&candidate.width==width&&candidate.height==height&&
                                fences.status(candidate.fence)!=0) {
                            preferred=candidate;
                            break;
                        }
                    }
                }
                while(!pending.isEmpty()) {
                    Frame frame=pending.removeFirst();
                    if(frame.target==target&&frame.width==width&&frame.height==height) {
                        if(preferred!=null&&frame!=preferred) {
                            frame.state=2;retiring.add(frame);dropped++;
                            continue;
                        }
                        if(selected!=null){selected.state=2;retiring.add(selected);dropped++;}
                        selected=frame;
                        // Keep any newer pending image queued when taking from an ordered source.
                        if(oldestFirst)break;
                    } else {frame.state=2;retiring.add(frame);dropped++;}
                }
                if(selected!=null){selected.state=1;acquired.add(selected);}
            }
            if(selected!=null) {
                selected.takeBegin=measureTiming ? System.nanoTime() : 0;
                fences.await(selected.fence);fences.delete(selected.fence);selected.fence=0;
                // Return means the dependency was queued, not GPU completion.
                selected.takeEnd=measureTiming ? System.nanoTime() : 0;
            }
            return selected;
        }
        void release(Frame frame) {
            readerOnly();
            if(frame==null||frame.owner!=this||frame.state!=1)throw new IllegalStateException("Borrowed source is not acquired");
            long done=fences.create();if(done==0)throw new IllegalStateException("Borrowed source read fence unavailable");
            frame.fence=done;frame.fenceStartedAt=clock.getAsLong();
            frame.state=2;acquired.remove(frame);retiring.add(frame);
        }
        /** A withdrawn producer must not need another Present to recover its pixels.
         * Pending inputs keep their publication fence. The caller must release
         * any acquired images reported here after its last queued GPU read.
         */
        boolean discardUnavailable(Predicate<Object> available) {
            readerOnly();
            if(available==null)throw new IllegalArgumentException("Missing producer availability");
            synchronized(this) {
                for(Iterator<Frame> iterator=pending.iterator();iterator.hasNext();) {
                    Frame frame=iterator.next();
                    if(available.test(frame.target)&&!disposals.containsKey(frame.keepAlive))continue;
                    iterator.remove();frame.state=2;retiring.add(frame);dropped++;
                }
                for(Frame frame:acquired)
                    if(!available.test(frame.target)||disposals.containsKey(frame.keepAlive))return true;
                return false;
            }
        }
        void poll() {
            readerOnly();
            for(Iterator<Frame> iterator=retiring.iterator();iterator.hasNext();) {
                Frame frame=iterator.next();
                if(fences.status(frame.fence)==0) {
                    if(clock.getAsLong()-frame.fenceStartedAt>=RendererRecovery.STEREO_TIMEOUT_NS)
                        throw new RendererRecovery.StereoTimeout("Borrowed stereo image");
                    continue;
                }
                iterator.remove();fences.delete(frame.fence);frame.fence=0;frame.state=3;
                synchronized(this){outstanding--;completed++;}
                frame.retired.run();
            }
            disposeUnreferenced();
        }
        private boolean references(Object backing) {
            for(Frame frame:pending)if(frame.keepAlive==backing)return true;
            for(Frame frame:acquired)if(frame.keepAlive==backing)return true;
            for(Frame frame:retiring)if(frame.keepAlive==backing)return true;
            return false;
        }
        boolean deferDestroy(Object backing,Runnable destroy) {
            readerOnly();if(backing==null||destroy==null)throw new IllegalArgumentException("Missing GPU disposal");
            synchronized(this) {
                if(!references(backing))return false;
                if(!disposals.containsKey(backing))disposals.put(backing,destroy);
                return true;
            }
        }
        private void disposeUnreferenced() {
            ArrayList<Runnable> ready=new ArrayList<>();
            synchronized(this) {
                Iterator<java.util.Map.Entry<Object,Runnable>> iterator=disposals.entrySet().iterator();
                while(iterator.hasNext()) {
                    java.util.Map.Entry<Object,Runnable> item=iterator.next();
                    if(!references(item.getKey())){ready.add(item.getValue());iterator.remove();}
                }
            }
            for(Runnable dispose:ready)dispose.run();
        }
        void close() {
            readerOnly();ArrayList<Frame> cancelled=new ArrayList<>();
            synchronized(this) {
                closing=true;notifyAll();cancelled.addAll(pending);pending.clear();cancelled.addAll(acquired);acquired.clear();
                cancelled.addAll(retiring);retiring.clear();outstanding=0;
            }
            // The guest has stopped. Cancelling must never signal reusable pixels.
            for(Frame frame:cancelled){if(frame.fence!=0)fences.delete(frame.fence);frame.fence=0;frame.state=3;}
            disposeUnreferenced();
        }
        long awaitPublication(long observed,long deadline) throws InterruptedException {
            readerOnly();
            synchronized(this) {
                while(!closing&&sequence==observed) {
                    long remaining=deadline-System.nanoTime();if(remaining<=0)break;
                    wait(remaining/1_000_000L,(int)(remaining%1_000_000L));
                }
                return sequence;
            }
        }
        synchronized long[] counts(){return new long[]{sequence,completed,dropped,outstanding};}
    }
    private static final IdentityHashMap<Object,Queue> queues=new IdentityHashMap<>();
    public static void enable(Object owner){enable(owner,false);}
    public static void enable(Object owner,boolean oldestFirst){enable(owner,oldestFirst,false);}
    public static void enable(Object owner,boolean oldestFirst,boolean measureTiming){enable(owner,oldestFirst,measureTiming,false);}
    public static void enable(Object owner,boolean oldestFirst,boolean measureTiming,boolean preferNewestReady) {
        synchronized(queues) {
            if(owner==null||queues.containsKey(owner))throw new IllegalStateException("Borrowed input already active");
            queues.put(owner,new Queue(GL,8,oldestFirst,measureTiming,System::nanoTime,preferNewestReady));
        }
    }
    private static Queue get(Object owner){synchronized(queues){return queues.get(owner);}}
    public static boolean active(Object owner){return get(owner)!=null;}
    public static long awaitPublication(Object owner,long observed,long deadline) throws InterruptedException {
        Queue queue=get(owner);if(queue!=null)return queue.awaitPublication(observed,deadline);
        long remaining=deadline-System.nanoTime();if(remaining>0)java.util.concurrent.locks.LockSupport.parkNanos(remaining);
        return observed;
    }
    public static boolean offer(Object owner,Object target,Object keepAlive,int texture,int width,int height,boolean flip,int windowId,int pixmapId,int presentSerial,Runnable retired) {
        Queue queue=get(owner);return queue!=null&&queue.offer(target,keepAlive,texture,width,height,flip,windowId,pixmapId,presentSerial,retired);
    }
    public static Frame take(Object owner,Object target,int width,int height){Queue queue=get(owner);return queue==null?null:queue.take(target,width,height);}
    public static void release(Object owner,Frame frame){Queue queue=get(owner);if(queue==null)throw new IllegalStateException("Borrowed source owner lost");queue.release(frame);}
    public static boolean discardUnavailable(Object owner,Predicate<Object> available){Queue queue=get(owner);return queue!=null&&queue.discardUnavailable(available);}
    public static void poll(Object owner){Queue queue=get(owner);if(queue!=null)queue.poll();}
    public static boolean deferDestroy(Object owner,Object backing,Runnable destroy){Queue queue=get(owner);return queue!=null&&queue.deferDestroy(backing,destroy);}
    public static long[] counts(Object owner){Queue queue=get(owner);return queue==null?new long[4]:queue.counts();}
    public static void close(Object owner){Queue queue=get(owner);if(queue!=null){queue.close();synchronized(queues){if(queues.get(owner)==queue)queues.remove(owner);}}}
}
