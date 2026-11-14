package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.util.ArrayDeque;

/** Bounded image/pose association. No guessed poses or 8-bit frame-ID reuse. */
public final class FramePoses<T> {
    public static final int MAGIC=0x47583346, PIXELS=96;
    private static final long MAX_AGE_NS=250_000_000L;
    static final class Sample<T> {
        // The native matching clock can differ from the host observation clock.
        final int id;final T pose;final long time,order,observed;
        Sample(int id,T pose,long time,long order,long observed) {
            this.id=id;this.pose=pose;this.time=time;this.order=order;this.observed=observed;
        }
    }
    private final ArrayDeque<Sample<T>> samples=new ArrayDeque<>();
    private long order,lastAccepted=-1;
    private long epoch,generation;
    private Sample<T> presented;
    private long presentedSnapshot,lastPresentationTime;
    private Boolean focused;
    private int validity;
    public synchronized void clear() {
        generation++;
        samples.clear();lastAccepted=-1;forgetImage();lastPresentationTime=0;validity=0;
    }
    private void forgetImage() {presented=null;presentedSnapshot=0;}
    /** Losing or regaining focus must not revive an earlier held image. */
    public synchronized void focused(boolean value) {
        if(focused==null||focused!=value) {clear();focused=value;}
    }
    /** A changed native coordinate basis invalidates old image/pose matches. */
    public synchronized void beginEpoch(long value) {
        if(epoch!=value) {clear();epoch=value;}
    }
    /** Capture before a native query; focus/reset can change while it runs. */
    public synchronized long samplingGeneration() {return generation;}
    /** Reject a query that crossed a boundary, even if focus has since returned. */
    public synchronized boolean rememberIfCurrent(long expected,int id,T pose,int flags,long sampled) {
        return rememberIfCurrent(expected,id,pose,flags,sampled,sampled);
    }
    synchronized boolean rememberIfCurrent(long expected,int id,T pose,int flags,long sampled,long observed) {
        if(expected!=generation)return false;
        remember(id,pose,flags,sampled,observed);return true;
    }
    // The device adapter must pass an immutable snapshot of the native pose.
    public synchronized void remember(int id,T pose,int flags,long now) {
        remember(id,pose,flags,now,now);
    }
    synchronized void remember(int id,T pose,int flags,long now,long observed) {
        // Orientation-only matching is allowed for a device's real 3DoF mode.
        // Valid predicted orientation does not require an actively-tracked bit.
        // Position validity remains a separate fact supplied to the renderer.
        if((flags&1)==0) {clear();return;}
        if(pose==null) throw new IllegalArgumentException("Missing native pose snapshot");
        if(validity!=0&&validity!=(flags&3))clear();
        validity=flags&3;
        samples.addLast(new Sample<>(id,pose,now,order++,observed));
        while(samples.size()>256||now-samples.getFirst().time>MAX_AGE_NS) samples.removeFirst();
    }
    private Sample<T> fresh(Integer id,long now) {
        if(id==null) return null;
        for(Sample<T> sample:samples) if(sample.id==id) {
            if(now<sample.time||now-sample.time>MAX_AGE_NS||sample.order<lastAccepted) return null;
            lastAccepted=sample.order;return sample;
        }
        return null;
    }
    public synchronized T match(Integer id,long now) {
        Sample<T> sample=fresh(id,now);return sample==null?null:sample.pose;
    }
    /** First qualify fresh pixels, then retain only that exact immutable image.
     * This never updates the original pose/time or accepts an unseen late image.
     */
    public T matchImage(Integer id,long snapshot,long now) {
        Sample<T> match=matchImageSample(id,snapshot,now);
        return match==null?null:match.pose;
    }
    synchronized Sample<T> matchImageSample(Integer id,long snapshot,long now) {
        if(now<lastPresentationTime||id==null) {forgetImage();return null;}
        lastPresentationTime=now;
        if(snapshot!=0&&presented!=null&&snapshot==presentedSnapshot) {
            if(id!=presented.id||now<presented.time) {forgetImage();return null;}
            return presented;
        }
        forgetImage();
        presented=fresh(id,now);
        if(presented==null)return null;
        presentedSnapshot=snapshot;return presented;
    }
    /** Withdraw stale game actions while leaving tracking/focus free to recover. */
    public synchronized boolean inputsCurrent(long now) {
        return Boolean.TRUE.equals(focused)&&presented!=null&&now>=presented.time&&
            now-presented.time<=MAX_AGE_NS;
    }
    /** One grayscale bit per RGBA pixel: magic, full frame ID, inverted ID.
     * Endpoints survive sRGB conversion. Midtones, missing alpha and RGB
     * disagreement reject rescaled/corrupt metadata rather than guessing.
     */
    public static Integer decode(ByteBuffer pixels) {
        if(pixels.remaining()!=PIXELS*4) return null;
        int[] words=new int[3];
        for(int i=0;i<PIXELS;i++) {
            int offset=pixels.position()+i*4,r=pixels.get(offset)&255,g=pixels.get(offset+1)&255,
                b=pixels.get(offset+2)&255,a=pixels.get(offset+3)&255;
            boolean high=r>=239&&g>=239&&b>=239,low=r<=16&&g<=16&&b<=16;
            if((!high&&!low)||a<239) return null;
            if(high) words[i/32]|=1<<(i%32);
        }
        return words[0]==MAGIC&&words[2]==~words[1] ? words[1] : null;
    }
}
