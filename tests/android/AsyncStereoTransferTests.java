package org.gk3hd.standalone;

import android.opengl.GLES30;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import java.nio.ByteBuffer;

/** Bounded real-GPU snapshots, exact IDs and immutable pixels, not headset input. */
public final class AsyncStereoTransferTests {
    private static void check(boolean okay,String text) {if(!okay) throw new AssertionError(text);}
    static ByteBuffer image(int id,boolean flip) {
        ByteBuffer pixels=ByteBuffer.allocateDirect(128*17*4);
        int[] words={FramePoses.MAGIC,id,~id};
        for(int y=0;y<17;y++) for(int x=0;x<128;x++) {
            int row=flip ? y : 16-y;
            if(row==16&&x<96) {
                byte b=(byte)((words[x/32]&(1<<(x%32)))!=0 ? 255 : 0);
                pixels.put(b).put(b).put(b).put((byte)255);
            } else pixels.put((byte)(x<64 ? 40+row : 0)).put((byte)(x>=64 ? 80+row : 0))
                .put((byte)(64+(id&127))).put((byte)255);
        }
        pixels.flip();return pixels;
    }
    public static void run() {
        int[] textures=new int[2],fbo=new int[1],oldRead=new int[1],oldDraw=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,oldRead,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,oldDraw,0);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,fbo,0);
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true);
        try {
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,16,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
            check(transfer.draw(128,16)==null,"Uninitialized snapshot accepted");
            check(transfer.timing(0)==null,"Uninitialized timing accepted");
            check(transfer.copiedFrameEvents(0)==null,"Uninitialized copy events accepted");
            for(boolean flip:new boolean[]{false,true}) for(int id:new int[]{0,256,0x87654321,-1}) {
                check(transfer.prepare(128,17,16,true),"Snapshot queue unexpectedly full");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MIN_FILTER,GLES30.GL_NEAREST);
                GLES30.glTexParameteri(GLES30.GL_TEXTURE_2D,GLES30.GL_TEXTURE_MAG_FILTER,GLES30.GL_NEAREST);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id,flip));
                GLES30.glEnable(GLES30.GL_SCISSOR_TEST);GLES30.glScissor(3,4,5,6);
                GLES30.glPixelStorei(GLES30.GL_PACK_ROW_LENGTH,128);
                GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_ROWS,2);
                transfer.capture(textures[0],!flip);
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Snapshot capture GPU error");
                int[] restored=new int[1];GLES30.glGetIntegerv(GLES30.GL_PACK_SKIP_ROWS,restored,0);
                check(GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST)&&restored[0]==2,"Snapshot changed caller clipping/packing state");
                GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
                GLES30.glPixelStorei(GLES30.GL_PACK_ROW_LENGTH,0);GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_ROWS,0);
                // Overwrite the producer immediately. A returned old ID must
                // never refer to this newer image, even with several in flight.
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id^0x7f,flip));
                long deadline=System.nanoTime()+2_000_000_000L;
                Integer found=null;
                do {found=transfer.draw(128,16);Thread.yield();}
                while((found==null||found!=id)&&System.nanoTime()<deadline);
                check(found!=null&&found==id,"Async snapshot ID mismatch");
                long[] timing=transfer.timing(found);
                check(timing!=null&&timing[0]>0&&timing[1]>=timing[0]&&timing[1]<=System.nanoTime(),"Snapshot timing is not monotonic");
                check(transfer.timing(id^0x7f)==null,"Timing attributed to a different frame ID");
                long[] events=transfer.copiedFrameEvents(found);
                check(events!=null&&events[0]==transfer.snapshotToken()&&events[1]==timing[0]&&
                    events[3]==timing[1]&&events[2]>=events[3]&&events[4]>=events[2],
                    "Owned-copy events do not describe the selected completed image");
                check(transfer.copiedFrameEvents(id^0x7f)==null,"Copy events attributed to another image");
                check(transfer.frameEvents(found)==null,"Owned copy invented an XPresent lease");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
                ByteBuffer pixels=ByteBuffer.allocateDirect(128*16*4);
                GLES30.glReadPixels(0,0,128,16,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
                for(int y=0;y<16;y++) for(int x=0;x<128;x++) {
                    int row=15-y,offset=(y*128+x)*4;
                    check((pixels.get(offset)&255)==(x<64 ? 40+row : 0)&&
                        (pixels.get(offset+1)&255)==(x>=64 ? 80+row : 0)&&
                        (pixels.get(offset+2)&255)==64+(id&127),"Async ID/pixel mismatch or orientation error");
                }
                check(transfer.draw(128,16)==id,"Repeated immutable snapshot changed ID");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Async GPU transfer error");
            }
            transfer.invalidate();check(transfer.draw(128,16)==null,"Retired producer still published");
            check(transfer.timing(0)==null,"Retired snapshot retained timing");
            check(transfer.copiedFrameEvents(0)==null,"Retired snapshot retained copy events");
            check(transfer.snapshotToken()==0,"Retired snapshot retained output identity");
            check(transfer.prepare(128,17,16,true),"Resize did not retire pending frames");
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
            GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,ByteBuffer.allocateDirect(128*17*4));
            transfer.capture(textures[0],false);GLES30.glFinish();
            check(transfer.draw(128,16)==null,"Unmarked desktop accepted asynchronously");
            sharedContext(transfer,textures[0]);
            retainedOutput(transfer,textures[0],fbo[0]);
            GpuHandoff.awaitOutput();
            check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Completed output fence produced a GL error");
            try {
                GpuHandoff.requireOutputReady(GLES30.GL_TIMEOUT_EXPIRED);
                throw new AssertionError("Timed-out output was accepted for submission");
            } catch(RendererRecovery.StereoTimeout expected) {
                check(expected.getMessage().startsWith("Stereo output"),"Output timeout was misidentified");
            }
            try {
                GpuHandoff.requireOutputReady(GLES30.GL_WAIT_FAILED);
                throw new AssertionError("Failed output fence was accepted for submission");
            } catch(IllegalStateException expected) {
                check(!(expected instanceof RendererRecovery.StereoTimeout),"Output wait error was reported as a timeout");
            }
            stalledMetadata(textures[0],false);
            stalledMetadata(textures[0],true);
            try {transfer.prepare(8192,8192,8191,true);throw new AssertionError("Unbounded stereo storage accepted");}
            catch(IllegalArgumentException expected) { }
        } finally {
            transfer.close();GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,oldRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,oldDraw[0]);
            GLES30.glDeleteTextures(2,textures,0);GLES30.glDeleteFramebuffers(1,fbo,0);
        }
    }
    private static void stalledMetadata(int texture,boolean leased) {
        Object owner=leased ? new Object() : null;
        Object window=new Object();
        if(leased)BorrowedPresentFrames.enable(owner,true);
        long[] now={0};
        boolean[] hold={true},reusable={false};
        AsyncStereoTransfer transfer=new AsyncStereoTransfer(true,null,owner,leased,false,()->now[0],fence-> {
            int status=GLES30.glClientWaitSync(fence,0,0);
            check(status==GLES30.GL_ALREADY_SIGNALED||status==GLES30.GL_CONDITION_SATISFIED,
                "The test must hold an already-completed real GPU fence");
            return hold[0] ? GLES30.GL_TIMEOUT_EXPIRED : status;
        });
        try {
            int id=0x3456789a;
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
            GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id,false));
            check(transfer.prepare(128,17,16,true),"No metadata transfer slot");
            if(leased) {
                check(BorrowedPresentFrames.offer(owner,window,window,texture,128,17,false,0,0,0,()->reusable[0]=true),
                    "Could not stage the leased image");
                transfer.capture(BorrowedPresentFrames.take(owner,window,128,17));
            } else transfer.capture(texture,false);
            GLES30.glFinish();
            now[0]=4_999_999_999L;
            transfer.prepare(128,17,16,false);
            check(transfer.snapshotToken()==0&&!reusable[0],"Pending metadata was treated as completed");
            now[0]++;
            try {
                transfer.prepare(128,17,16,false);
                throw new AssertionError("Pending metadata bypassed its deadline");
            } catch(RendererRecovery.StereoTimeout expected) {
                check(expected.getMessage().startsWith("Stereo metadata readback"),"Wrong failure source");
            }
            check(transfer.snapshotToken()==0&&transfer.outputCounts()[3]==0&&!reusable[0],
                "A timeout made unfinished metadata or its image reusable");
            // If no poll occurred while paused, a signalled fence is still
            // valid after a long elapsed time. It carries the original ID.
            now[0]=10_000_000_000L;hold[0]=false;
            transfer.prepare(128,17,16,false);
            check(transfer.draw(128,16)==id&&transfer.outputCounts()[3]==1&&!reusable[0],
                "An already signalled fence was discarded after the deadline");
        } finally {
            transfer.close();
            if(leased) {
                GLES30.glFinish();
                BorrowedPresentFrames.poll(owner);
                BorrowedPresentFrames.close(owner);
            }
        }
        check(!leased||reusable[0],"The GPU-safe close did not retire the retained image");
    }

    private static void retainedOutput(AsyncStereoTransfer transfer,int texture,int output) {
        transfer.invalidate();long previous=0;
        // Two different images may use the same sampled pose. A pose/frame ID
        // alone must never suppress the second GPU copy into a retained target.
        for(int variant=0;variant<2;variant++) {
            int id=0x12345678;
            ByteBuffer pixels=image(id,false);
            if(variant==1) for(int y=1;y<16;y++) for(int x=0;x<128;x++) {
                int offset=(y*128+x)*4+2;pixels.put(offset,(byte)((pixels.get(offset)&255)^127));
            }
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
            GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
            check(transfer.prepare(128,17,16,true),"Retained output snapshot unavailable");
            transfer.capture(texture,false);
            long deadline=System.nanoTime()+2_000_000_000L;
            Integer found;
            do {found=transfer.draw(128,16,previous);Thread.yield();}
            while((found==null||transfer.snapshotToken()==previous)&&System.nanoTime()<deadline);
            check(found!=null&&found==id&&transfer.snapshotToken()!=previous,"New image reused the old immutable identity");
            check(!transfer.outputUnchanged(),"New pixels were reported as an unchanged output");
            previous=transfer.snapshotToken();
            long[] beforeReuse=transfer.outputCounts();
            check(previous!=0&&transfer.draw(128,16,previous)==id,"Retained immutable output was unavailable");
            check(transfer.outputUnchanged(),"Exact retained output did not report its skipped write");
            long[] afterReuse=transfer.outputCounts();
            check(afterReuse[0]==beforeReuse[0]&&afterReuse[1]==beforeReuse[1]+1,"Retained output was copied again");
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,output);
            ByteBuffer pixel=ByteBuffer.allocateDirect(4);
            GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
            int expected=64+(id&127);if(variant==1) expected^=127;
            check((pixel.get(2)&255)==expected,"Retained output confused pixels sharing a pose ID");
            // A separate output is not entitled to reuse the first target's
            // token. Zero forces reconstruction after a clear or target change.
            GLES30.glClearColor(0,0,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            check(transfer.draw(128,16,0)==id,"Output target could not be reconstructed");
            check(!transfer.outputUnchanged(),"Reconstructed target was reported as unchanged");
            GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
            check((pixel.get(2)&255)==expected,"Cleared output retained stale contents");
            check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Retained output GPU error");
        }
    }
    private static void sharedContext(AsyncStereoTransfer transfer,int texture) {
        EGLDisplay display=EGL14.eglGetCurrentDisplay();
        EGLContext consumer=EGL14.eglGetCurrentContext();
        EGLSurface draw=EGL14.eglGetCurrentSurface(EGL14.EGL_DRAW),read=EGL14.eglGetCurrentSurface(EGL14.EGL_READ);
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,0x40,EGL14.EGL_SURFACE_TYPE,
            EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"No shared-context GPU config");
        EGLContext producer=EGL14.eglCreateContext(display,configs[0],consumer,
            new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
        check(producer!=EGL14.EGL_NO_CONTEXT&&surface!=EGL14.EGL_NO_SURFACE,"No shared producer context");
        GpuHandoff handoff=new GpuHandoff();
        try {
            check(!handoff.beginRead(),"Unfenced initial producer accepted");
            transfer.invalidate();
            for(int frame=1;frame<=16;frame++) {
                int id=0x76543200+frame;
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select shared producer");
                handoff.beforeWrite();
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id,false));
                handoff.afterWrite();
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot restore consumer");
                check(handoff.beginRead(),"Fenced producer unavailable");
                try {check(transfer.prepare(128,17,16,true),"Shared snapshot unavailable");transfer.capture(texture,false);}
                finally {handoff.afterRead();}
                // Queue a producer overwrite while the GPU snapshot is still
                // in flight. The handoff must order it after the consumer read.
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select overwrite producer");
                handoff.beforeWrite();
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id+64,false));
                handoff.afterWrite();
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Producer handoff GPU error");
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot restore overwritten consumer");
                long deadline=System.nanoTime()+2_000_000_000L;Integer found;
                do {found=transfer.draw(128,16);Thread.yield();}
                while((found==null||found!=id)&&System.nanoTime()<deadline);
                check(found!=null&&found==id,"Shared producer overwrote the captured frame ID");
                int[] output=new int[1];GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,output,0);
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,output[0]);
                ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                check((pixel.get(2)&255)==64+(id&127),"Shared producer overwrote captured eye pixels");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Consumer handoff GPU error");
            }
        } finally {
            EGL14.eglMakeCurrent(display,draw,read,consumer);handoff.close();
            EGL14.eglDestroySurface(display,surface);EGL14.eglDestroyContext(display,producer);
        }
    }
}
