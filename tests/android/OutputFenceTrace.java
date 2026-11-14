package org.gk3hd.standalone;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.StringJoiner;

/** Bounded nonblocking completion brackets for exact immutable output writes. */
public final class OutputFenceTrace {
    public interface Fences {long create();int status(long fence);void delete(long fence);}
    public interface Clock {long now();}
    public static final String[] COLUMNS={"target","snapshot","pose","sampled_ns","copy_begin_ns","cpu_received_ns",
        "fence_begin_ns","fence_end_ns","first_poll_begin_ns","last_pending_begin_ns","ready_poll_begin_ns","ready_poll_end_ns","polls"};
    private static final class Pending {
        final long fence;final long[] row;
        Pending(long fence,long[] row){this.fence=fence;this.row=row;}
    }
    private final Fences fences;private final Clock clock;private final int capacity;
    private final ArrayDeque<Pending> pending=new ArrayDeque<>();
    private final ArrayList<long[]> completed=new ArrayList<>();
    private final Thread owner=Thread.currentThread();
    private long issued,lastSnapshot,lastSampled;private int target,lastPose;private boolean closed;
    public OutputFenceTrace(Fences fences,Clock clock,int capacity) {
        if(fences==null||clock==null||capacity<1||capacity>8)throw new IllegalArgumentException("Invalid output observer");
        this.fences=fences;this.clock=clock;this.capacity=capacity;
    }
    private void owned(){if(Thread.currentThread()!=owner||closed)throw new IllegalStateException("Output observer requires its live GL thread");}
    public boolean issue(int target,long snapshot,int pose,long sampled,long copyBegin,long received) {
        owned();
        if(target<=0||snapshot<=0||sampled<=0||copyBegin<sampled||received<copyBegin)throw new IllegalArgumentException("Invalid output write identity/time");
        if(this.target!=0&&this.target!=target)throw new IllegalStateException("Output target changed without reset");
        if(snapshot==lastSnapshot){if(pose!=lastPose||sampled!=lastSampled)throw new IllegalStateException("Unchanged output was relabelled");return false;}
        if(snapshot<lastSnapshot)throw new IllegalStateException("Output identity regressed");
        if(pending.size()==capacity||issued>=4096)throw new IllegalStateException("Output completion bound exceeded");
        long begin=clock.now();if(begin<received)throw new IllegalStateException("Output clock regressed");
        long fence=fences.create();long end=clock.now();
        if(fence==0||end<begin){if(fence!=0)fences.delete(fence);throw new IllegalStateException("Output fence unavailable/time invalid");}
        long[] row={target,snapshot,pose&0xffffffffL,sampled,copyBegin,received,begin,end,0,0,0,0,0};
        pending.addLast(new Pending(fence,row));this.target=target;lastSnapshot=snapshot;lastPose=pose;lastSampled=sampled;issued++;
        return true;
    }
    public void poll() {
        owned();
        // Every query is zero-timeout in the adapter. Observe each exact fence,
        // not a newer unrelated output, and never wait for the whole queue.
        for(java.util.Iterator<Pending> iterator=pending.iterator();iterator.hasNext();) {
            Pending p=iterator.next();long begin=clock.now();int status=fences.status(p.fence);long end=clock.now();
            if(begin<p.row[7]||end<begin)throw new IllegalStateException("Output completion clock regressed");
            if(p.row[8]==0)p.row[8]=begin;p.row[12]++;
            if(status==0){p.row[9]=begin;continue;}
            if(status!=1)throw new IllegalStateException("Output completion failed");
            p.row[10]=begin;p.row[11]=end;fences.delete(p.fence);iterator.remove();completed.add(p.row);
        }
    }
    public int pending(){return pending.size();}
    public long issued(){return issued;}
    String describePending() {
        owned();
        StringJoiner report=new StringJoiner("; ","[","]");
        for(Pending output:pending) {
            long[] row=output.row;
            report.add("snapshot="+row[1]+" pose="+row[2]+" fence_issued_ns="+row[7]+
                " first_poll_ns="+row[8]+" last_pending_ns="+row[9]+" polls="+row[12]);
        }
        return report.toString();
    }
    public long[][] rows(){long[][] copy=new long[completed.size()][];for(int i=0;i<copy.length;i++)copy[i]=completed.get(i).clone();return copy;}
    public void close(){owned();for(Pending p:pending)fences.delete(p.fence);pending.clear();closed=true;}
}
