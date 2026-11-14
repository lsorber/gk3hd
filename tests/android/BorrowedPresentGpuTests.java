package org.gk3hd.standalone;

import android.opengl.EGL14;
import android.opengl.GLES30;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicInteger;

/** Actual shared-context GPU import/read retirement, not a headset submission. */
public final class BorrowedPresentGpuTests {
    private static int checks;
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);checks++;}
    public static void run() {
        EGLDisplay display=EGL14.eglGetCurrentDisplay();EGLContext consumer=EGL14.eglGetCurrentContext();
        EGLSurface draw=EGL14.eglGetCurrentSurface(EGL14.EGL_DRAW),read=EGL14.eglGetCurrentSurface(EGL14.EGL_READ);
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,0x40,EGL14.EGL_SURFACE_TYPE,
            EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"No borrowed producer config");
        EGLContext producer=EGL14.eglCreateContext(display,configs[0],consumer,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
        check(producer!=EGL14.EGL_NO_CONTEXT&&surface!=EGL14.EGL_NO_SURFACE,"No borrowed producer context");
        int[] textures=new int[2],fbo=new int[1],oldRead=new int[1],oldDraw=new int[1],oldTexture=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,oldRead,0);GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,oldDraw,0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,oldTexture,0);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,fbo,0);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,128,16);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
        check(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"No borrowed output target");
        BorrowedPresentFrames.Queue queue=new BorrowedPresentFrames.Queue(BorrowedPresentFrames.GL,3);
        AsyncStereoTransfer snapshots=new AsyncStereoTransfer(true);
        Object window=new Object();AtomicInteger idle=new AtomicInteger();
        try {
            for(int index=0;index<16;index++) {
                int id=0x48621000+index;boolean flip=(index&1)!=0;
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select borrowed producer");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,AsyncStereoTransferTests.image(id,flip));
                check(queue.offer(window,textures,textures[0],128,17,flip,0,0,0,idle::incrementAndGet),"Borrowed source not offered");
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot select borrowed consumer");
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
                BorrowedPresentFrames.Frame frame=queue.take(window,128,17);
                check(frame!=null&&frame.texture==textures[0],"Wrong source lease");
                check(snapshots.prepare(128,17,16,true),"Borrowed snapshot unavailable");
                snapshots.capture(frame.texture,frame.flip);queue.release(frame);
                check(idle.get()==index,"Pixmap reusable before its GPU read completes");
                Integer found=null;long until=System.nanoTime()+2_000_000_000L;
                while((found==null||found!=id||idle.get()!=index+1)&&System.nanoTime()<until) {
                    queue.poll();found=snapshots.draw(128,16);Thread.yield();
                }
                check(found!=null&&found==id&&idle.get()==index+1,"Borrowed image or GPU retirement failed");
                // Reuse is now legal. The immutable snapshot must survive it.
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot reuse borrowed producer");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,AsyncStereoTransferTests.image(id+64,flip));
                GLES30.glFlush();
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot inspect borrowed snapshot");
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo[0]);
                check(snapshots.draw(128,16)==id,"Producer reuse changed snapshot identity");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
                ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                check((pixel.get(0)&255)==47&&(pixel.get(1)&255)==0&&(pixel.get(2)&255)==64+(id&127),"Borrowed left eye pixels/orientation changed");
                GLES30.glReadPixels(96,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                check((pixel.get(0)&255)==0&&(pixel.get(1)&255)==87&&(pixel.get(2)&255)==64+(id&127),"Borrowed right eye pixels/orientation changed");
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Borrowed GPU error");
            }
        } finally {
            check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot restore borrowed-test context");
            queue.close();snapshots.close();GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,oldRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,oldDraw[0]);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,oldTexture[0]);
            GLES30.glDeleteTextures(2,textures,0);GLES30.glDeleteFramebuffers(1,fbo,0);
            EGL14.eglDestroySurface(display,surface);EGL14.eglDestroyContext(display,producer);
        }
        System.out.println(checks+" actual shared-context borrowed source/snapshot/retirement checks passed");
    }
}
