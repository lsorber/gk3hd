package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.Iterator;

/** Retire client pixmaps only after the shared-context GPU copy completes.
 * Existing GL servicing polls bounded work without a waiter thread or GPU idle. */
public final class PresentCopyRetirement {
    interface Fences {long create();int status(long fence);void delete(long fence);}
    static final int WAITING=0,READY=1,FAILED=2;
    private static final Fences GL=new Fences() {
        public long create() {
            long fence=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);
            if(fence!=0)GLES30.glFlush();
            return fence;
        }
        public int status(long fence) {
            int state=GLES30.glClientWaitSync(fence,0,0);
            if(state==GLES30.GL_ALREADY_SIGNALED||state==GLES30.GL_CONDITION_SATISFIED)return READY;
            return state==GLES30.GL_TIMEOUT_EXPIRED?WAITING:FAILED;
        }
        public void delete(long fence) {GLES30.glDeleteSync(fence);}
    };
    static final class Job {
        final long fence;final Runnable retired;
        Job(long fence,Runnable retired){this.fence=fence;this.retired=retired;}
    }
    static final class Queue {
        private final Fences fences;
        private final int limit;
        private final Thread reader=Thread.currentThread();
        private final ArrayDeque<Job> incoming=new ArrayDeque<>(),active=new ArrayDeque<>();
        private boolean closing;
        private int outstanding;
        long submitted,completed,cancelled;
        Queue(Fences fences,int limit) {
            if(fences==null||limit<1||limit>32)throw new IllegalArgumentException("Invalid present retirement bound");
            this.fences=fences;this.limit=limit;
        }
        boolean defer(Runnable retired) {
            if(retired==null)throw new IllegalArgumentException("Missing present retirement callback");
            synchronized(this){if(closing||outstanding>=limit)return false;}
            long fence=fences.create();if(fence==0)return false;
            synchronized(this) {
                if(!closing&&outstanding<limit) {
                    incoming.addLast(new Job(fence,retired));++outstanding;++submitted;return true;
                }
            }
            fences.delete(fence);return false;
        }
        private void readerOnly() {
            if(Thread.currentThread()!=reader)throw new IllegalStateException("Present retirement requires its consuming GL thread");
        }
        void poll() {
            readerOnly();
            synchronized(this) {
                if(closing)return;
                while(!incoming.isEmpty())active.addLast(incoming.removeFirst());
            }
            Iterator<Job> iterator=active.iterator();
            while(iterator.hasNext()) {
                Job job=iterator.next();int state=fences.status(job.fence);
                if(state==WAITING)continue;
                if(state!=READY)throw new IllegalStateException("Present copy completion failed; pixmap not retired");
                iterator.remove();fences.delete(job.fence);
                synchronized(this){--outstanding;++completed;}
                // Caller does not own the server/drawable/queue lock here.
                job.retired.run();
            }
        }
        void close() {
            readerOnly();
            ArrayList<Job> abandoned=new ArrayList<>();
            synchronized(this) {
                closing=true;abandoned.addAll(incoming);incoming.clear();
                abandoned.addAll(active);active.clear();cancelled+=abandoned.size();outstanding=0;
            }
            // Activity must stop its guest before closing. Cancelling never
            // tells a still-running producer that its pixmap is reusable.
            for(Job job:abandoned)fences.delete(job.fence);
        }
        synchronized int outstanding(){return outstanding;}
    }
    private static final IdentityHashMap<Object,Queue> queues=new IdentityHashMap<>();
    public static void enable(Object owner) {
        if(owner==null)throw new IllegalArgumentException("Missing present owner");
        synchronized(queues) {
            if(queues.containsKey(owner))throw new IllegalStateException("Present retirement already enabled");
            queues.put(owner,new Queue(GL,32));
        }
    }
    private static Queue get(Object owner){synchronized(queues){return queues.get(owner);}}
    public static boolean active(Object owner){return get(owner)!=null;}
    public static boolean defer(Object owner,Runnable retired){Queue queue=get(owner);return queue!=null&&queue.defer(retired);}
    public static void poll(Object owner){Queue queue=get(owner);if(queue!=null)queue.poll();}
    public static long[] counts(Object owner) {
        Queue queue=get(owner);
        if(queue==null)return new long[]{0,0,0,0};
        synchronized(queue){return new long[]{queue.submitted,queue.completed,queue.cancelled,queue.outstanding};}
    }
    public static void close(Object owner) {
        Queue queue;
        synchronized(queues){queue=queues.get(owner);}
        if(queue!=null) {
            // Enforce the context/thread precondition before forgetting ownership.
            queue.close();
            synchronized(queues){if(queues.get(owner)==queue)queues.remove(owner);}
        }
    }
}
