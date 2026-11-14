package org.gk3hd.standalone;

import android.opengl.GLES30;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import java.nio.ByteBuffer;

/** Real shared-context lease retention and exact pixels; not headset acceptance. */
public final class LeasedMetadataTests {
    private static int checks;
    private static void check(boolean okay,String text){checks++;if(!okay)throw new AssertionError(text);}
    public static void run() {
        AsyncStereoTransfer owned=new AsyncStereoTransfer();
        try {
            try {owned.prepare(5760,2884,2880,true);throw new AssertionError("Owned snapshots exceeded their allocation budget");}
            catch(IllegalArgumentException expected) {checks++;}
        } finally {owned.close();}
        for(boolean ordered:new boolean[]{false,true}) {
            AsyncStereoTransfer leased=new AsyncStereoTransfer(true,null,new Object(),ordered);
            try {
                check(leased.prepare(5760,2884,2880,true),"Existing producer images were charged as new full-size copies");
                try {leased.prepare(8193,2884,2880,true);throw new AssertionError("Leases bypassed source dimension bounds");}
                catch(IllegalArgumentException expected) {checks++;}
                check(leased.prepare(5760,2884,2880,false),"Rejected dimensions corrupted the leased configuration");
            } finally {leased.close();}
        }
        run(false);
        run(true);
    }
    private static void run(boolean ordered) {
        EGLDisplay display=EGL14.eglGetCurrentDisplay();EGLContext consumer=EGL14.eglGetCurrentContext();
        EGLSurface read=EGL14.eglGetCurrentSurface(EGL14.EGL_READ),draw=EGL14.eglGetCurrentSurface(EGL14.EGL_DRAW);
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,0x40,EGL14.EGL_SURFACE_TYPE,
            EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"No leased producer config");
        EGLContext producer=EGL14.eglCreateContext(display,configs[0],consumer,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
        check(producer!=EGL14.EGL_NO_CONTEXT&&surface!=EGL14.EGL_NO_SURFACE,"No leased producer context");
        int[] textures=new int[3],fbo=new int[1],oldRead=new int[1],oldDraw=new int[1],oldTexture=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,oldRead,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,oldDraw,0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,oldTexture,0);
        GLES30.glGenTextures(3,textures,0);GLES30.glGenFramebuffers(1,fbo,0);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[2]);
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,128,16);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[2],0);
        Object owner=new Object(),window=new Object();BorrowedPresentFrames.enable(owner,ordered);
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true,null,owner,ordered);
        java.util.ArrayList<long[]> completedMetadata=new java.util.ArrayList<>();
        transfer.observeCompletions(completedMetadata::add);
        boolean[] reusable={true,true};
        try {
            check(transfer.draw(128,16)==null,"Empty lease published pixels");
            for(int i=0;i<8;i++) {
                final int input=i%2;int id=0x2afb0000+(i==1?0:i);boolean flip=(i&1)!=0;
                check(reusable[input],"Producer overwritten while selected or pending");
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select leased producer");
                ByteBuffer image=AsyncStereoTransferTests.image(id,flip);
                if(i==1)image.put(((flip?7:9)*128+32)*4,(byte)215);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[input]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image);
                reusable[input]=false;
                check(BorrowedPresentFrames.offer(owner,window,textures,textures[input],128,17,!flip,0,0,0,()->reusable[input]=true),"Lease offer failed");
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot select leased consumer");
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
                long oldToken=transfer.snapshotToken();
                check(transfer.prepare(128,17,16,true),"Leased metadata queue unexpectedly full");
                BorrowedPresentFrames.Frame frame=BorrowedPresentFrames.take(owner,window,128,17);
                check(frame!=null,"No leased source acquired");
                transfer.capture(frame);
                // Retirement must also work after the last output, when no
                // further source acquisition or draw is requested.
                long drainDeadline=System.nanoTime()+2_000_000_000L;
                while(completedMetadata.size()==i&&System.nanoTime()<drainDeadline) {
                    transfer.pollCompletions();Thread.yield();
                }
                check(completedMetadata.size()==i+1,"Metadata-only polling did not retire the final input");
                long until=System.nanoTime()+2_000_000_000L;Integer found=null;
                do {
                    // Ordered completion advances once per prepare/draw tick.
                    transfer.prepare(128,17,16,false);
                    found=transfer.draw(128,16,oldToken);BorrowedPresentFrames.poll(owner);Thread.yield();
                }while((found==null||found!=id||transfer.snapshotToken()==oldToken||(i>0&&!reusable[1-input]))&&System.nanoTime()<until);
                check(found!=null&&found==id&&transfer.snapshotToken()!=oldToken,"Lease ID/sequence did not advance");
                check(completedMetadata.size()==i+1,"Completed leased metadata was lost or duplicated");
                long[] completion=completedMetadata.get(i);
                check(completion[0]==transfer.snapshotToken()&&completion[1]==(id&0xffffffffL)&&
                    completion[7]>0&&completion[8]>=completion[7]&&completion[10]>=completion[8]&&
                    completion[11]>=completion[10]&&completion[12]>=completion[11],
                    "Completion timing lost the actual GPU-verified image identity");
                check(!reusable[input],"Selected immutable source was made reusable");
                check(i==0||reusable[1-input],"Old source never retired after replacement");
                long[] timing=transfer.timing(found);
                check(timing!=null&&timing[0]>0&&timing[1]>=timing[0],"Lease metadata timing invalid");
                check(transfer.outputCounts()[2]==0,"Leased metadata issued an intermediate full-image copy");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
                ByteBuffer pixels=ByteBuffer.allocateDirect(128*16*4);
                GLES30.glReadPixels(0,0,128,16,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
                for(int y=0;y<16;y++)for(int x=0;x<128;x++) {
                    int row=15-y,offset=(y*128+x)*4;
                    int red=i==1&&x==32&&row==7?215:(x<64?40+row:0);
                    check((pixels.get(offset)&255)==red&&(pixels.get(offset+1)&255)==(x>=64?80+row:0)&&
                        (pixels.get(offset+2)&255)==64+(id&127)&&(pixels.get(offset+3)&255)==255,"Lease pixels/orientation/alpha mismatch");
                }
                long token=transfer.snapshotToken();
                check(transfer.draw(128,16,token)==id&&transfer.outputUnchanged(),"Exact retained lease issued another output write");
                check(transfer.draw(128,16,0)==id&&!transfer.outputUnchanged(),"Reconstructed lease marked unchanged");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Leased metadata GL error");
            }
            // Closing must release ownership through its GPU fence, not early idle.
            transfer.close();long until=System.nanoTime()+2_000_000_000L;
            while((!reusable[0]||!reusable[1])&&System.nanoTime()<until){BorrowedPresentFrames.poll(owner);Thread.yield();}
            check(reusable[0]&&reusable[1],"Leased source never retired at close");
        }finally {
            check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot restore leased test context");
            BorrowedPresentFrames.close(owner);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,oldRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,oldDraw[0]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,oldTexture[0]);
            GLES30.glDeleteTextures(3,textures,0);GLES30.glDeleteFramebuffers(1,fbo,0);
            EGL14.eglDestroySurface(display,surface);EGL14.eglDestroyContext(display,producer);
        }
        System.out.println(checks+" actual shared-context retained-lease metadata/pixel/retirement checks passed");
    }
}
