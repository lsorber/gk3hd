package org.gk3hd.standalone;

/** Completion belongs to exact immutable pixels in one unchanged output target. */
public final class OutputCompletion {
    private static final long BLANK=-1;
    private final long[] completed;
    private final long[] submitted;
    private long submissions;
    private int lastSubmitted=-1;
    public OutputCompletion(int targets) {
        if(targets<1||targets>16) throw new IllegalArgumentException("Invalid output target count");
        completed=new long[targets];
        submitted=new long[targets];
    }
    /** A caller may offer this identity only while the target and its pixels remain intact. */
    public long retained(int target) {return hasCompletedBlank(target)?0:completed[target];}
    public boolean hasCompletedBlank(int target) {return completed[target]==BLANK;}
    /** Unknown identities and any output write retain the conservative completion wait. */
    public boolean required(int target,long snapshot,boolean unchanged) {
        return !unchanged||snapshot==0||snapshot!=retained(target);
    }
    /** Call only after the output's writes have actually completed. Zero invalidates reuse. */
    public void completed(int target,long snapshot) {completed[target]=snapshot;}
    public void completedBlank(int target) {completed[target]=BLANK;}
    /** Preserve the ordinary ring's write spacing after any read-only repeat. */
    public int writableTarget() {
        for(int offset=0;offset<submitted.length;offset++) {
            int target=(int)((submissions+offset)%submitted.length);
            if(submitted[target]==0||submissions-submitted[target]+1>=submitted.length)return target;
        }
        throw new IllegalStateException("No retired output target");
    }
    public int lastSubmitted() {return lastSubmitted;}
    /** Count a repeated texture as a new read by the compositor. */
    public void submitted(int target) {submitted[target]=++submissions;lastSubmitted=target;}
    public void reset() {
        java.util.Arrays.fill(completed,0);
        java.util.Arrays.fill(submitted,0);
        submissions=0;
        lastSubmitted=-1;
    }
}
