package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicInteger;

/** Actual GPU ownership after source withdrawal, without another publication. */
public final class WithdrawnPresentGpuTests {
    private static int checks;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static void pixels(int target,int id) {
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,target);
        ByteBuffer pixel=ByteBuffer.allocateDirect(4);
        GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
        check((pixel.get(0)&255)==47&&(pixel.get(1)&255)==0&&(pixel.get(2)&255)==64+(id&127),"Left-eye pixels changed");
        GLES30.glReadPixels(96,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
        check((pixel.get(0)&255)==0&&(pixel.get(1)&255)==87&&(pixel.get(2)&255)==64+(id&127),"Right-eye pixels changed");
    }
    public static void run() {
        Object owner=new Object(),window=new Object();AtomicInteger idle=new AtomicInteger(),destroyed=new AtomicInteger();
        int[] output=new int[1],target=new int[1],old=new int[2];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,old,0);GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,old,1);
        GLES30.glGenTextures(1,output,0);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,output[0]);
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,128,16);
        GLES30.glGenFramebuffers(1,target,0);GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,target[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,output[0],0);
        check(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Missing output target");
        BorrowedPresentFrames.enable(owner,true);
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true,null,owner,true);
        try {
            for(int cycle=0;cycle<4;cycle++) {
                int[] sources=new int[3];GLES30.glGenTextures(3,sources,0);
                int id=0x48621000+cycle;boolean flip=(cycle&1)!=0;
                for(int index=0;index<3;index++) {
                    GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,sources[index]);
                    GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,AsyncStereoTransferTests.image(id+index,flip));
                    check(BorrowedPresentFrames.offer(owner,window,sources,sources[index],128,17,flip,0,0,0,idle::incrementAndGet),"Could not offer source");
                }
                check(transfer.prepare(128,17,16,true),"Could not prepare source");
                BorrowedPresentFrames.Frame frame=BorrowedPresentFrames.take(owner,window,128,17);check(frame!=null,"Source missing");
                transfer.capture(frame);Integer found=null;long deadline=System.nanoTime()+2_000_000_000L;
                while((found==null||found!=id)&&System.nanoTime()<deadline) {
                    transfer.prepare(128,17,16,false);GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,target[0]);
                    found=transfer.draw(128,16);Thread.yield();
                }
                check(found!=null&&found==id,"Source identity missing");pixels(target[0],id);
                int before=idle.get();BorrowedPresentFrames.poll(owner);
                check(idle.get()==before&&BorrowedPresentFrames.counts(owner)[3]==3,"The old poll-only path unexpectedly released selected/pending images");
                boolean backingWithdrawal=(cycle&1)!=0;
                if(backingWithdrawal)check(BorrowedPresentFrames.deferDestroy(owner,sources,()->{GLES30.glDeleteTextures(3,sources,0);destroyed.incrementAndGet();}),"Backing withdrawal missing");
                check(BorrowedPresentFrames.discardUnavailable(owner,identity->backingWithdrawal),"Acquired withdrawn source not reported");
                check(idle.get()==before,"Withdrawal fabricated GPU completion");
                transfer.invalidate();
                check(transfer.snapshotToken()==0&&transfer.draw(128,16)==null,"Retired source was still drawable");
                deadline=System.nanoTime()+2_000_000_000L;
                while(BorrowedPresentFrames.counts(owner)[3]!=0&&System.nanoTime()<deadline){BorrowedPresentFrames.poll(owner);Thread.yield();}
                check(idle.get()==before+3&&BorrowedPresentFrames.counts(owner)[3]==0,"Withdrawn sources require another publication to retire");
                if(!backingWithdrawal)GLES30.glDeleteTextures(3,sources,0);
                check(destroyed.get()==(cycle+1)/2,"Backing destruction ownership changed");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Withdrawal/recovery GPU error");
            }
        } finally {
            transfer.close();BorrowedPresentFrames.close(owner);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glDeleteTextures(1,output,0);GLES30.glDeleteFramebuffers(1,target,0);
        }
        System.out.println(checks+" actual GPU source-withdrawal, immutable pixels and recovery checks passed");
    }
}
