package org.gk3hd.standalone;

import android.opengl.GLES30;
import android.opengl.GLES31;
import android.util.Log;
import java.nio.ByteBuffer;
import java.nio.Buffer;
import java.util.function.LongSupplier;
import java.util.function.LongToIntFunction;

/** Bounded immutable GPU images, owned or leased. Only metadata crosses to the CPU. */
public final class AsyncStereoTransfer {
    private static final int MARKER_BYTES=FramePoses.PIXELS*4;
    private static final class Slot {
        int texture,fbo,pbo;
        long fence,fenceStartedAt,sequence,capturedAt,readyAt;
        Integer id;
        boolean flip;
        BorrowedPresentFrames.Frame lease;
        FrameIdentity.Captured identity;
        ImageIdentity.Resolved composition;
        int[] epoch;
        long identifiedAt;
        boolean early;
        long firstPoll,lastPending;
        int window,pixmap,presentSerial;
    }
    private final Slot[] slots={new Slot(),new Slot(),new Slot()};
    private final int[] sourceFbo=new int[1];
    private Slot selected;
    private int width,height,visibleHeight;
    private long sequence;
    private long outputCopies,outputReuses;
    private boolean outputPaddedEyeBlit;
    private long inputCopies,completedSnapshots;
    private boolean pending;
    private boolean outputUnchanged;
    private final boolean measureTiming;
    private final GlTransferProfile profile;
    private final Object leaseOwner;
    private final boolean ordered;
    private final boolean linearOutput;
    private int[] blitState;
    private boolean blitPathReported,blitFallbackReported;
    private final LongSupplier clock;
    private final LongToIntFunction completionStatus;
    private FrameIdentity identities;
    private long copyBegin;
    private StereoCopy eyeCopy;
    private java.util.function.Consumer<long[]> completionObserver;
    /** Debug-only existing-fence observations. Adds no GPU commands or waits. */
    public void observeCompletions(java.util.function.Consumer<long[]> observer) {
        if(!measureTiming||width!=0||observer==null||completionObserver!=null)
            throw new IllegalStateException("Configure completion observation before timed transfer starts");
        completionObserver=observer;
    }
    /** Drain existing metadata reads without acquiring images or drawing output. */
    public void pollCompletions() {
        if(completionObserver==null)throw new IllegalStateException("Completion observation is not configured");
        poll();
    }
    /** Capability of this retained source, independent of the headset model. */
    public void identities(FrameIdentity tracker) {
        if(width!=0||tracker==null||identities!=null)
            throw new IllegalStateException("Configure image identities before retained transfer starts");
        identities=tracker;
    }
    private int metadataBytes() {return (identities==null ? FramePoses.PIXELS : FrameIdentity.PIXELS)*4;}
    private void select(Slot slot) {
        if(selected==null||slot.sequence>selected.sequence) {
            Slot previous=selected;selected=slot;
            if(previous!=null)releaseLease(previous);
        }
    }
    public AsyncStereoTransfer() {this(false);}
    public AsyncStereoTransfer(boolean measureTiming) {
        this(measureTiming,null);
    }
    public AsyncStereoTransfer(boolean measureTiming,GlTransferProfile profile) {
        this(measureTiming,profile,null);
    }
    public AsyncStereoTransfer(boolean measureTiming,GlTransferProfile profile,Object leaseOwner) {
        this(measureTiming,profile,leaseOwner,false);
    }
    public AsyncStereoTransfer(boolean measureTiming,GlTransferProfile profile,Object leaseOwner,boolean ordered) {
        this(measureTiming,profile,leaseOwner,ordered,false);
    }
    public AsyncStereoTransfer(boolean measureTiming,GlTransferProfile profile,Object leaseOwner,boolean ordered,boolean linearOutput) {
        this(measureTiming,profile,leaseOwner,ordered,linearOutput,System::nanoTime,
            fence->GLES30.glClientWaitSync(fence,0,0));
    }
    AsyncStereoTransfer(boolean measureTiming,GlTransferProfile profile,Object leaseOwner,boolean ordered,
            boolean linearOutput,LongSupplier clock,LongToIntFunction completionStatus) {
        this.clock=clock;this.completionStatus=completionStatus;
        if(ordered&&leaseOwner==null)throw new IllegalArgumentException("Ordered stereo requires retained producer images");
        this.profile=profile;this.leaseOwner=leaseOwner;
        this.ordered=ordered;
        this.linearOutput=linearOutput;
        this.measureTiming=measureTiming;GLES30.glGenFramebuffers(1,sourceFbo,0);
    }
    public boolean prepare(int width,int height,int visibleHeight,boolean changed) {
        // Only owned snapshots allocate full-size textures here. Leased slots
        // allocate bounded metadata PBOs and retain existing producer images;
        // free() separately bounds how many of those images may stay leased.
        if(width<FramePoses.PIXELS||width>8192||height<2||height>8192||visibleHeight<1||visibleHeight>=height||
           (leaseOwner==null&&(long)width*height*4*slots.length>128L*1024*1024))
            throw new IllegalArgumentException("Stereo snapshots exceed bounded GPU storage");
        if(this.width!=width||this.height!=height||this.visibleHeight!=visibleHeight) {
            retire();this.width=width;this.height=height;this.visibleHeight=visibleHeight;pending=true;
        }
        pending|=changed;
        poll();
        return pending&&free()!=null;
    }
    /** Opt in before drawing to a presenter-owned RGBA8 framebuffer. */
    public void preferPaddedEyeBlit() {
        int[] state=new int[2];
        GLES30.glGetIntegerv(GLES30.GL_MAJOR_VERSION,state,0);
        GLES30.glGetIntegerv(GLES30.GL_MINOR_VERSION,state,1);
        if(state[0]>3||state[0]==3&&state[1]>=1)blitState=state;
        else reportBlitFallback("requires GLES 3.1, got "+state[0]+"."+state[1]);
    }

    private void reportBlitFallback(String reason) {
        if(!blitFallbackReported) {
            Log.i("GK3HDXR","Padded eye blit using the shader: "+reason);
            blitFallbackReported=true;
        }
    }

    private boolean blitPaddedEyes(int outputWidth,int outputHeight) {
        // The split is pixel-qualified at these extents on Crystal.
        boolean qualifiedExtent=width==4120&&visibleHeight==2060||width==5376&&visibleHeight==2752||
            width==5632&&visibleHeight==2880||width==6752&&visibleHeight==3456;
        if(blitState==null)return false;
        if(linearOutput||selected.lease==null||!selected.flip||!qualifiedExtent||
            height!=visibleHeight+4||outputWidth!=width||outputHeight!=visibleHeight) {
            if(!blitFallbackReported)reportBlitFallback("source="+width+"x"+height+" visible="+visibleHeight+
                " target="+outputWidth+"x"+outputHeight+" leased="+(selected.lease!=null)+
                " flipped="+selected.flip+" linear="+linearOutput);
            return false;
        }
        if(GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST)) {
            reportBlitFallback("draw target uses scissoring");return false;
        }

        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,blitState,0);
        if(blitState[0]==0||blitState[0]==sourceFbo[0]) {
            reportBlitFallback("no distinct draw framebuffer");return false;
        }
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,blitState,0);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,selected.texture);
        GLES31.glGetTexLevelParameteriv(GLES30.GL_TEXTURE_2D,0,GLES31.GL_TEXTURE_INTERNAL_FORMAT,blitState,1);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,blitState[0]);
        if(blitState[1]!=GLES30.GL_RGBA8) {
            if(!blitFallbackReported)reportBlitFallback("source format=0x"+Integer.toHexString(blitState[1]));
            return false;
        }

        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,sourceFbo[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
            GLES30.GL_TEXTURE_2D,selected.texture,0);
        try {
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE) {
                reportBlitFallback("read framebuffer is incomplete");return false;
            }
            blitFlippedRows(width,visibleHeight);
            int error=GLES30.glGetError();
            if(error!=GLES30.GL_NO_ERROR) {
                Log.w("GK3HDXR","Padded eye blit failed, using the shader: "+error);
                blitState=null;
                return false;
            }
            if(!blitPathReported) {
                Log.i("GK3HDXR","Padded eye blit active at "+width+"x"+visibleHeight);
                blitPathReported=true;
            }
            return true;
        } finally {
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,0,0);
        }
    }

    // A full-height flipped blit can repeat or skip rows on Adreno.
    static void blitFlippedRows(int width,int height) {
        int split=2048;
        GLES30.glBlitFramebuffer(0,height,width,height-split,
            0,0,width,split,GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);
        GLES30.glBlitFramebuffer(0,height-split,width,0,
            0,split,width,height,GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);
    }
    private Slot free() {
        if(leaseOwner!=null) {
            // Ordered delivery keeps one selected and up to two pending images.
            // The runtime requests six transport images so retaining these
            // three immutable inputs leaves capacity for producer progress.
            // Latest-image/copy controls retain their original two-image bound.
            int held=0;for(Slot slot:slots)if(slot.lease!=null)held++;
            if(held>=(ordered ? 3 : 2))return null;
        }
        for(Slot slot:slots) if(slot!=selected&&slot.fence==0) return slot;
        return null;
    }
    private void allocate(Slot slot) {
        int[] ids=new int[1];
        if(leaseOwner==null) {
            GLES30.glGenTextures(1,ids,0);slot.texture=ids[0];
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,slot.texture);
            GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,width,height);
            GLES30.glGenFramebuffers(1,ids,0);slot.fbo=ids[0];
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,slot.fbo);
            GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,slot.texture,0);
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Async stereo snapshot incomplete");
        }
        GLES30.glGenBuffers(1,ids,0);slot.pbo=ids[0];
        GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,slot.pbo);
        GLES30.glBufferData(GLES30.GL_PIXEL_PACK_BUFFER,metadataBytes()*2,null,GLES30.GL_STREAM_READ);
    }
    public void capture(int texture,boolean flipHint) {
        if(leaseOwner!=null)throw new IllegalStateException("Leased metadata requires an owned frame");
        capture(texture,flipHint,null);
    }
    public void capture(BorrowedPresentFrames.Frame frame) {
        if(leaseOwner==null||frame==null||frame.width!=width||frame.height!=height)
            throw new IllegalArgumentException("Invalid leased stereo frame");
        capture(frame.texture,frame.flip,frame);
    }
    private void releaseLease(Slot slot) {
        if(slot.lease==null)return;
        // This queues a fence after every metadata/output read in this GL
        // context. It does not assume that returning from a draw finished it.
        BorrowedPresentFrames.release(leaseOwner,slot.lease);
        slot.lease=null;slot.texture=0;slot.id=null;
        if(slot.fence==0)slot.identity=null;
    }
    private void capture(int texture,boolean flipHint,BorrowedPresentFrames.Frame frame) {
        Slot slot=free();
        if(!pending||slot==null) throw new IllegalStateException("No free stereo snapshot");
        if(slot.lease!=null)throw new IllegalStateException("Leased slot reused before retirement");
        slot.lease=frame;
        slot.firstPoll=slot.lastPending=0;
        slot.window=frame==null ? 0 : frame.windowId;
        slot.pixmap=frame==null ? 0 : frame.pixmapId;
        slot.presentSerial=frame==null ? 0 : frame.presentSerial;
        slot.early=false;
        slot.identity=identities==null ? null : frame==null ? identities.captureCopy(width,height) :
            identities.acquire(leaseOwner,frame.keepAlive,width,height,frame.sequence);
        slot.composition=null;slot.identifiedAt=0;
        slot.epoch=!measureTiming||slot.identity==null||slot.identity.snapshot==null ? null : slot.identity.snapshot.epoch();
        int[] old=new int[8];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,old,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,old,1);
        GLES30.glGetIntegerv(GLES30.GL_PIXEL_PACK_BUFFER_BINDING,old,2);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,old,3);
        int[] packNames={GLES30.GL_PACK_ALIGNMENT,GLES30.GL_PACK_ROW_LENGTH,GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_SKIP_ROWS};
        for(int i=0;i<4;i++) GLES30.glGetIntegerv(packNames[i],old,4+i);
        boolean scissor=GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST);
        try {
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            for(int i=0;i<4;i++) GLES30.glPixelStorei(packNames[i],i==0 ? 4 : 0);
            if(slot.pbo==0) allocate(slot);
            if(frame!=null)slot.texture=texture;
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,sourceFbo[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,texture,0);
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Async stereo source incomplete");
            if(frame==null)GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,slot.fbo);
            slot.capturedAt=measureTiming ? System.nanoTime() : 0;slot.readyAt=0;
            if(frame==null) {
                int copy=profile==null ? 0 : profile.begin(GlTransferProfile.SNAPSHOT_COPY,sequence+1);
                try {GLES30.glBlitFramebuffer(0,0,width,height,0,0,width,height,GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);}
                finally {if(profile!=null) profile.end(copy);}
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,slot.fbo);
            }
            // Leased images already use the validated source framebuffer.
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,slot.pbo);
            int metadata=profile==null ? 0 : profile.begin(GlTransferProfile.METADATA_READBACK,sequence+1);
            try {
                int pixels=metadataBytes()/4;
                GLES30.glReadPixels(0,0,pixels,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,0);
                GLES30.glReadPixels(0,height-1,pixels,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,metadataBytes());
            } finally {if(profile!=null) profile.end(metadata);}
            slot.fence=GLES30.glFenceSync(GLES30.GL_SYNC_GPU_COMMANDS_COMPLETE,0);
            if(slot.fence==0) throw new IllegalStateException("Async stereo completion fence unavailable");
            slot.fenceStartedAt=clock.getAsLong();
            slot.flip=flipHint;slot.id=null;slot.sequence=++sequence;pending=false;
            if(measureTiming&&frame==null) inputCopies++;
            GLES30.glFlush();
            // The producer/consumer GL dependency already orders reading these
            // immutable pixels. Only their CPU label is available early. Keep
            // the PBO fence and verify it independently even after selection.
            if(slot.identity!=null&&slot.identity.predicted!=null&&slot.identity.flip!=null) {
                slot.composition=slot.identity.predicted;slot.identifiedAt=measureTiming ? System.nanoTime() : 0;
                slot.id=slot.identity.predicted.pose;slot.flip=slot.identity.flip;
                slot.early=true;select(slot);
            }
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[2]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,old[3]);
            for(int i=0;i<4;i++) GLES30.glPixelStorei(packNames[i],old[4+i]);
            if(scissor) GLES30.glEnable(GLES30.GL_SCISSOR_TEST);
        }
    }
    private void poll() {
        Slot oldest=null;
        if(ordered)for(Slot slot:slots)
            if(slot.fence!=0&&(oldest==null||slot.sequence<oldest.sequence))oldest=slot;
        for(Slot slot:slots) {
            if(ordered&&slot!=oldest)continue;
            if(slot.fence==0) continue;
            long pollBegin=completionObserver==null ? 0 : System.nanoTime();
            int status=completionStatus.applyAsInt(slot.fence);
            long pollEnd=completionObserver==null ? 0 : System.nanoTime();
            if(completionObserver!=null&&slot.firstPoll==0)slot.firstPoll=pollBegin;
            if(status==GLES30.GL_TIMEOUT_EXPIRED) {
                if(clock.getAsLong()-slot.fenceStartedAt>=RendererRecovery.STEREO_TIMEOUT_NS)
                    throw new RendererRecovery.StereoTimeout("Stereo metadata readback");
                slot.lastPending=pollBegin;continue;
            }
            if(status!=GLES30.GL_ALREADY_SIGNALED&&status!=GLES30.GL_CONDITION_SATISFIED)
                throw new IllegalStateException("Async stereo completion failed");
            GLES30.glDeleteSync(slot.fence);slot.fence=0;
            if(measureTiming) completedSnapshots++;
            slot.readyAt=measureTiming ? System.nanoTime() : 0;
            int[] old=new int[1];GLES30.glGetIntegerv(GLES30.GL_PIXEL_PACK_BUFFER_BINDING,old,0);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,slot.pbo);
            try {
                Buffer mapped=GLES30.glMapBufferRange(GLES30.GL_PIXEL_PACK_BUFFER,0,metadataBytes()*2,GLES30.GL_MAP_READ_BIT);
                if(!(mapped instanceof ByteBuffer)) throw new IllegalStateException("Async stereo metadata unavailable");
                ByteBuffer bytes=(ByteBuffer)mapped;
                try {
                    slot.id=decodeAt(bytes,slot.flip ? metadataBytes() : 0);
                    if(slot.id==null) {
                        slot.id=decodeAt(bytes,slot.flip ? 0 : metadataBytes());
                        if(slot.id!=null) slot.flip=!slot.flip;
                    }
                    if(slot.identity!=null) {
                        slot.composition=identities.complete(slot.identity,bytes,slot.flip ? metadataBytes() : 0);
                        slot.identity=null;
                    }
                    if(slot.id!=null&&slot.identifiedAt==0&&measureTiming)slot.identifiedAt=System.nanoTime();
                } finally {
                    if(!GLES30.glUnmapBuffer(GLES30.GL_PIXEL_PACK_BUFFER))
                        throw new IllegalStateException("Async stereo metadata corrupted");
                }
            } finally {GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[0]);}
            if(completionObserver!=null) {
                int[] epoch=slot.epoch==null ? new int[4] : slot.epoch;
                completionObserver.accept(new long[]{slot.sequence,slot.id==null ? -1 : slot.id&0xffffffffL,
                    slot.composition==null ? 0 : slot.composition.composition,
                    epoch[0]&0xffffffffL,epoch[1]&0xffffffffL,epoch[2]&0xffffffffL,epoch[3]&0xffffffffL,
                    slot.capturedAt,slot.firstPoll,slot.lastPending,pollBegin,pollEnd,System.nanoTime(),
                    slot.window&0xffffffffL,slot.pixmap&0xffffffffL,slot.presentSerial&0xffffffffL});
            }
            if(slot.id!=null&&(selected==null||slot.sequence>selected.sequence))select(slot);
            else if(slot!=selected)releaseLease(slot);
        }
    }
    public Integer draw(int outputWidth,int outputHeight) {
        return draw(outputWidth,outputHeight,0);
    }
    /** Retain only the exact immutable snapshot already in this unchanged output. */
    public Integer draw(int outputWidth,int outputHeight,long retainedSnapshot) {
        return draw(outputWidth,outputHeight,retainedSnapshot,0);
    }
    /** Movie overlays must belong to the exact selected immutable composition. */
    public Integer draw(int outputWidth,int outputHeight,long retainedSnapshot,long movie) {
        return draw(outputWidth,outputHeight,retainedSnapshot,movie,null);
    }
    public Integer draw(int outputWidth,int outputHeight,long retainedSnapshot,long movie,
            java.util.function.BooleanSupplier target) {
        outputUnchanged=false;
        outputPaddedEyeBlit=false;
        if(outputWidth<=0||outputHeight<=0) throw new IllegalArgumentException("Invalid stereo output extent");
        // prepare() advances at most one completed image per consumer tick.
        // A second poll here would retire another fresh image without drawing it.
        if(!ordered)poll();
        if(selected==null) return null;
        // A known movie overlay is never a complete game image after Close.
        if(selected.composition==null ? movie!=0 : selected.composition.movie!=movie)return null;
        if(retainedSnapshot!=0&&retainedSnapshot==selected.sequence) {
            outputUnchanged=true;
            if(measureTiming) outputReuses++;
            return selected.id;
        }
        if(target!=null&&!target.getAsBoolean())return null;
        int[] old=new int[1];GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,old,0);
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,selected.fbo);
        try {
            int copy=profile==null ? 0 : profile.begin(GlTransferProfile.EYE_COPY,selected.sequence);
            copyBegin=measureTiming ? System.nanoTime() : 0;
            try {
                outputPaddedEyeBlit=movie==0&&blitPaddedEyes(outputWidth,outputHeight);
                if(!outputPaddedEyeBlit) {
                    if(eyeCopy==null)eyeCopy=new StereoCopy(linearOutput);
                    eyeCopy.draw(selected.texture,width,height,visibleHeight,selected.flip,outputWidth,outputHeight,movie!=0);
                }
            }
            finally {if(profile!=null) profile.end(copy);}
            if(measureTiming) outputCopies++;
            return selected.id;
        } finally {GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);}
    }
    public long snapshotToken() {return selected==null ? 0 : selected.sequence;}
    public boolean outputUnchanged() {return outputUnchanged;}
    public boolean outputPaddedEyeBlit() {return outputPaddedEyeBlit;}
    public long[] outputCounts() {return new long[]{outputCopies,outputReuses,inputCopies,completedSnapshots};}
    public long[] identityCounts() {return identities==null ? new long[4] : identities.counts();}
    public boolean earlyIdentity() {return selected!=null&&selected.early;}
    /** Exact selected lease events, never inferred from the latest mapping or another image. */
    public long[] frameEvents(Integer id) {
        Slot slot=selected;
        if(!measureTiming||slot==null||id==null||!id.equals(slot.id)||slot.lease==null)return null;
        BorrowedPresentFrames.Frame frame=slot.lease;
        int[] epoch=slot.epoch==null ? new int[4] : slot.epoch;
        return new long[]{frame.sequence,frame.offeredAt,frame.takeBegin,frame.takeEnd,
            slot.capturedAt,slot.identifiedAt,slot.readyAt,copyBegin,
            slot.composition==null ? 0 : slot.composition.composition,
            epoch[0]&0xffffffffL,epoch[1]&0xffffffffL,epoch[2]&0xffffffffL,epoch[3]&0xffffffffL,slot.early ? 1 : 0,frame.windowId&0xffffffffL,frame.pixmapId&0xffffffffL,frame.presentSerial&0xffffffffL};
    }
    /** Owned-copy events; there is no XPresent lease or composition identity on this path. */
    public long[] copiedFrameEvents(Integer id) {
        Slot slot=selected;
        if(!measureTiming||slot==null||id==null||!id.equals(slot.id)||slot.lease!=null)return null;
        return new long[]{slot.sequence,slot.capturedAt,slot.identifiedAt,slot.readyAt,copyBegin};
    }
    /** Diagnostic timestamps belong to this exact immutable image, not a newer producer. */
    public long[] timing(Integer id) {
        if(!measureTiming||selected==null||id==null||!id.equals(selected.id)||selected.readyAt==0) return null;
        return new long[]{selected.capturedAt,selected.readyAt};
    }
    private static Integer decodeAt(ByteBuffer mapped,int offset) {
        ByteBuffer row=mapped.duplicate();row.position(offset);row.limit(offset+MARKER_BYTES);
        return FramePoses.decode(row.slice());
    }
    private void retire() {
        for(Slot slot:slots) {
            if(slot.fence!=0) GLES30.glDeleteSync(slot.fence);
            if(slot.pbo!=0) GLES30.glDeleteBuffers(1,new int[]{slot.pbo},0);
            if(slot.fbo!=0) GLES30.glDeleteFramebuffers(1,new int[]{slot.fbo},0);
            if(leaseOwner==null&&slot.texture!=0) GLES30.glDeleteTextures(1,new int[]{slot.texture},0);
            releaseLease(slot);
            slot.fence=0;slot.texture=slot.fbo=slot.pbo=0;slot.id=null;slot.identity=null;
        }
        selected=null;outputUnchanged=false;
        if(identities!=null)identities.invalidate();
    }
    public void invalidate() {retire();width=height=visibleHeight=0;pending=false;}
    public void close() {retire();if(eyeCopy!=null)eyeCopy.close();eyeCopy=null;GLES30.glDeleteFramebuffers(1,sourceFbo,0);}
}
