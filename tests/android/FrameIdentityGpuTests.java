package org.gk3hd.standalone;

import android.opengl.GLES30;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import java.nio.ByteBuffer;

/** Real shared-context lease retention and exact pixels; not headset acceptance. */
public final class FrameIdentityGpuTests {
    private static int checks;
    private static void check(boolean okay,String text){checks++;if(!okay)throw new AssertionError(text);}
    private static ImageIdentity.Snapshot packet(int[] serials,int[] poses,int[] movies,int latest) {
        ByteBuffer bytes=ByteBuffer.allocate(320).order(java.nio.ByteOrder.LITTLE_ENDIAN);
        bytes.put(new byte[]{'G','P','M','P','0','0','0','2'});
        bytes.putInt(2).putInt(320).putInt(640).putInt(17).putInt(2).putInt(latest);
        bytes.putInt(1).putInt(2).putInt(3).putInt(4);bytes.position(64);
        for(int i=0;i<2;i++)bytes.putInt(i).putInt(serials[i]).putInt(poses[i]).putInt(movies[i]);
        return ImageIdentity.decode((ByteBuffer)bytes.position(0));
    }
    private static ByteBuffer image(int pose,int serial,boolean flip) {
        ByteBuffer bytes=ByteBuffer.allocateDirect(640*17*4);
        int[] values={pose,1,2,3,4,serial};
        for(int y=0;y<17;y++)for(int x=0;x<640;x++) {
            int row=flip ? y : 16-y;
            if(row==16&&x<576) {
                int bit=x%96,value=values[x/96];int[] words={FramePoses.MAGIC,value,~value};
                byte c=(byte)((words[bit/32]&(1<<(bit%32)))!=0 ? 255 : 0);
                bytes.put(c).put(c).put(c).put((byte)255);
            } else bytes.put((byte)(x<320 ? 40+row : 0)).put((byte)(x>=320 ? 80+row : 0))
                .put((byte)(64+(pose&127))).put((byte)255);
        }
        return (ByteBuffer)bytes.flip();
    }
    public static int run() {
        run(true);runCopies();
        System.out.println(checks+" actual GPU immutable lease/copy, identity, movie, pixel and retirement checks passed");
        return checks;
    }
    private static void rejectMovieAsWorld(AsyncStereoTransfer transfer) {
        long snapshot=transfer.snapshotToken();
        long writes=transfer.outputCounts()[0];
        check(transfer.draw(640,16,0,0,()->{
            throw new AssertionError("Retired movie selected a game output target");
        })==null,"Retired movie became a game frame");
        check(transfer.draw(640,16,snapshot,0)==null&&!transfer.outputUnchanged(),
            "Retired movie was reused as a game frame");
        check(transfer.outputCounts()[0]==writes,"Retired movie wrote game pixels");
    }
    private static void runCopies() {
        int[] textures=new int[2],fbo=new int[1],oldRead=new int[1],oldDraw=new int[1],oldTexture=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,oldRead,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,oldDraw,0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,oldTexture,0);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,fbo,0);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,640,16);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
        ImageIdentity.Snapshot[] snapshot={null};
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true);
        transfer.identities(new FrameIdentity(()->snapshot[0]));
        try {
            for(int i=0;i<4;i++) {
                int id=0x31fa0000+(i==1 ? 0 : i),serial=i+1,movie=i<2 ? 7+i : 0;
                boolean flip=(i&1)!=0;
                snapshot[0]=packet(new int[]{serial,0},new int[]{id,0},new int[]{movie,0},serial);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,640,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id,serial,flip));
                long previous=transfer.snapshotToken();
                check(transfer.prepare(640,17,16,true),"Private-copy queue unexpectedly full");
                transfer.capture(textures[0],!flip);
                check(!transfer.earlyIdentity()&&transfer.snapshotToken()==previous,"Private copy was selected before its GPU completion");
                // Later CPU publications and overwriting the producer must not
                // relabel or modify the already queued private copy.
                snapshot[0]=packet(new int[]{serial+10,0},new int[]{id+10,0},new int[]{99,0},serial+10);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,640,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id+10,serial+10,flip));
                long until=System.nanoTime()+2_000_000_000L;Integer found;
                do {
                    transfer.prepare(640,17,16,false);found=transfer.draw(640,16,0,movie);Thread.yield();
                }while((found==null||found!=id||transfer.snapshotToken()==previous)&&System.nanoTime()<until);
                check(found!=null&&found==id&&!transfer.earlyIdentity(),"Completed private copy lost its exact original identity");
                check(transfer.identityCounts()[0]==i+1,"Copied image escaped GPU identity verification");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
                ByteBuffer pixels=ByteBuffer.allocateDirect(640*16*4);
                GLES30.glReadPixels(0,0,640,16,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
                for(int y=0;y<16;y++)for(int x=0;x<640;x++) {
                    int row=15-y,offset=(y*640+x)*4;
                    check((pixels.get(offset)&255)==(x<320 ? 40+row : 0)&&
                        (pixels.get(offset+1)&255)==(x>=320 ? 80+row : 0)&&
                        (pixels.get(offset+2)&255)==64+(id&127)&&(pixels.get(offset+3)&255)==255,
                        "Private copy changed original pixels, alpha or orientation");
                }
                check(transfer.draw(640,16,0,99)==null,"Copied pixels inherited another movie's overlay");
                if(movie!=0) {
                    check(transfer.draw(640,16,0,movie)==id,"Verified copied movie overlay was rejected");
                    rejectMovieAsWorld(transfer);
                }
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Private-copy metadata GL error");
            }
        }finally {
            transfer.close();
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,oldRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,oldDraw[0]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,oldTexture[0]);
            GLES30.glDeleteTextures(2,textures,0);GLES30.glDeleteFramebuffers(1,fbo,0);
        }
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
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,640,16);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[2],0);
        Object owner=new Object(),window=new Object();BorrowedPresentFrames.enable(owner,ordered,true);
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true,null,owner,ordered);
        boolean[] reusable={true,true};Object[] images={new Object(),new Object()};
        ImageIdentity.Snapshot[] snapshot={null};
        transfer.identities(new FrameIdentity(()->snapshot[0]));
        int[] serials=new int[2],poses=new int[2],movies=new int[2];
        try {
            check(transfer.draw(640,16)==null,"Empty lease published pixels");
            for(int i=0;i<8;i++) {
                final int input=i%2;int id=0x2afb0000+(i==1?0:i);boolean flip=(i&1)!=0;
                check(reusable[input],"Producer overwritten while selected or pending");
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select leased producer");
                serials[input]=i+1;poses[input]=id;
                movies[input]=i<2 ? i+7 : 0;
                snapshot[0]=packet(serials,poses,movies,i+1);
                ByteBuffer image=image(id,i+1,flip);
                if(i==1)image.put(((flip?7:9)*640+32)*4,(byte)215);
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[input]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,640,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image);
                reusable[input]=false;
                check(BorrowedPresentFrames.offer(owner,window,images[input],textures[input],640,17,!flip,0,0,0,()->reusable[input]=true),"Lease offer failed");
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot select leased consumer");
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
                long oldToken=transfer.snapshotToken();
                check(transfer.prepare(640,17,16,true),"Leased metadata queue unexpectedly full");
                BorrowedPresentFrames.Frame frame=BorrowedPresentFrames.take(owner,window,640,17);
                check(frame!=null,"No leased source acquired");
                transfer.capture(frame);
                if(i>=2)check(transfer.snapshotToken()!=oldToken&&transfer.earlyIdentity(),
                    "Verified acquired backing did not select immediately");
                long until=System.nanoTime()+2_000_000_000L;Integer found=null;
                do {
                    // Ordered completion advances once per prepare/draw tick.
                    transfer.prepare(640,17,16,false);
                    found=transfer.draw(640,16,oldToken,movies[input]);BorrowedPresentFrames.poll(owner);Thread.yield();
                }while((found==null||found!=id||transfer.snapshotToken()==oldToken||transfer.identityCounts()[0]!=i+1||
                    (i>0&&!reusable[1-input]))&&System.nanoTime()<until);
                check(found!=null&&found==id&&transfer.snapshotToken()!=oldToken,"Lease ID/sequence did not advance");
                check(!reusable[input],"Selected immutable source was made reusable");
                check(i==0||reusable[1-input],"Old source never retired after replacement");
                long[] timing=transfer.timing(found);
                check(timing!=null&&timing[0]>0&&timing[1]>=timing[0],"Lease metadata timing invalid");
                check(transfer.outputCounts()[2]==0,"Leased metadata issued an intermediate full-image copy");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
                ByteBuffer pixels=ByteBuffer.allocateDirect(640*16*4);
                GLES30.glReadPixels(0,0,640,16,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
                for(int y=0;y<16;y++)for(int x=0;x<640;x++) {
                    int row=15-y,offset=(y*640+x)*4;
                    int red=i==1&&x==32&&row==7?215:(x<320?40+row:0);
                    check((pixels.get(offset)&255)==red&&(pixels.get(offset+1)&255)==(x>=320?80+row:0)&&
                        (pixels.get(offset+2)&255)==64+(id&127)&&(pixels.get(offset+3)&255)==255,
                        "Lease pixels/orientation/alpha mismatch at image="+i+" x="+x+" y="+y);
                }
                check(transfer.identityCounts()[0]==i+1,"Early-selected pixels escaped independent GPU verification");
                long[] events=transfer.frameEvents(found);
                check(events!=null&&events[0]==frame.sequence&&events[1]>0&&events[2]>=events[1]&&events[3]>=events[2]&&
                    events[4]>=events[3]&&events[5]>=events[4]&&events[6]>=events[4]&&events[7]>=events[5]&&events[8]==i+1,
                    "Frame event times/identity did not belong to the exact acquired backing");
                long token=transfer.snapshotToken();
                check(transfer.draw(640,16,token,movies[input])==id&&transfer.outputUnchanged(),"Exact retained lease issued another output write");
                check(transfer.draw(640,16,0,movies[input])==id&&!transfer.outputUnchanged(),"Reconstructed lease marked unchanged");
                check(transfer.draw(640,16,0,movies[input]+19)==null,"An ordinary or retired movie image became an overlay");
                if(movies[input]!=0) {
                    check(transfer.draw(640,16,0,movies[input])==id,"Current movie overlay was rejected");
                    rejectMovieAsWorld(transfer);
                }
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
    }
}
