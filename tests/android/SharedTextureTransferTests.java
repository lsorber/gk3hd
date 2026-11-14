package org.gk3hd.standalone;

import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES30;
import com.winlator.renderer.Texture;
import com.winlator.xserver.Drawable;
import java.nio.ByteBuffer;

/** Actual upstream texture publication, two GL contexts and exact eye pixels. */
public final class SharedTextureTransferTests {
    private static void check(boolean okay,String message) {if(!okay) throw new AssertionError(message);}
    private static ByteBuffer image(int id) {
        ByteBuffer pixels=ByteBuffer.allocateDirect(128*17*4);
        int[] words={FramePoses.MAGIC,id,~id};
        for(int y=0;y<17;y++) for(int x=0;x<128;x++) {
            if(y==0&&x<96) {
                byte value=(byte)((words[x/32]&(1<<(x%32)))!=0 ? 255 : 0);
                pixels.put(value).put(value).put(value).put((byte)255);
            } else pixels.put((byte)(x<64 ? 40+y : 0)).put((byte)(x>=64 ? 80+y : 0))
                .put((byte)(64+(id&127))).put((byte)255);
        }
        pixels.flip();return pixels;
    }
    public static void run() {
        EGLDisplay display=EGL14.eglGetCurrentDisplay();
        EGLContext consumer=EGL14.eglGetCurrentContext();
        EGLSurface draw=EGL14.eglGetCurrentSurface(EGL14.EGL_DRAW),read=EGL14.eglGetCurrentSurface(EGL14.EGL_READ);
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,0x40,EGL14.EGL_SURFACE_TYPE,
            EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"No texture handoff config");
        EGLContext producer=EGL14.eglCreateContext(display,configs[0],consumer,
            new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,1,EGL14.EGL_HEIGHT,1,EGL14.EGL_NONE},0);
        check(producer!=EGL14.EGL_NO_CONTEXT&&surface!=EGL14.EGL_NO_SURFACE,"No texture handoff context");
        int[] previousRead=new int[1],previousDraw=new int[1],fbos=new int[2],producerRead=new int[1],target=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,previousRead,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,previousDraw,0);
        Drawable sourceDrawable=new Drawable(0,128,17,null),destination=new Drawable(0,128,17,null);
        Texture source=sourceDrawable.getTexture(),texture=destination.getTexture();
        source.setFormat(GLES30.GL_RGBA);texture.setFormat(GLES30.GL_RGBA);
        source.updateFromDrawable();texture.updateFromDrawable();
        destination.setData(null);
        check(!texture.beginXrRead(),"Unfenced cross-context image accepted");
        destination.setData(ByteBuffer.allocateDirect(128*17*4));
        // A one-shot CPU-backed image is already ordered in this context. It
        // must not wait forever for a future GPU producer publication.
        check(texture.beginXrRead(),"CPU upload incorrectly waits for another producer");texture.endXrRead();
        destination.setData(null);
        GLES30.glGenFramebuffers(2,fbos,0);GLES30.glGenTextures(1,target,0);
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,target[0]);
        GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,16,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbos[0]);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,target[0],0);
        StereoTransfer sync=new StereoTransfer();
        try {
            for(boolean fromReadBuffer:new boolean[]{false,true}) for(int frame=1;frame<=8;frame++) {
                int id=0x12345000+frame;
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select texture producer");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,source.getTextureId());
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id));
                if(fromReadBuffer) {
                    // Framebuffer names, unlike textures/fences, are local to
                    // their context. Allocate the read FBO on its producer.
                    if(producerRead[0]==0) GLES30.glGenFramebuffers(1,producerRead,0);
                    GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,producerRead[0]);
                    GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,source.getTextureId(),0);
                    texture.copyFromReadBuffer((short)128,(short)17);
                } else texture.copyFromSource(source);
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot select texture consumer");
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbos[0]);
                check(texture.beginXrRead(),"Fenced texture publication unavailable");
                try {
                    check(sync.draw(texture.getTextureId(),128,17,16,false,128,16,true)==id,"Shared texture ID mismatch");
                    // The cached-ID path still blits from shared storage.
                    check(sync.draw(texture.getTextureId(),128,17,16,false,128,16,false)==id,"Repeated texture ID mismatch");
                } finally {texture.endXrRead();}
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select texture overwrite producer");
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,source.getTextureId());
                GLES30.glTexSubImage2D(GLES30.GL_TEXTURE_2D,0,0,0,128,17,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,image(id+64));
                texture.copyFromSource(source);
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot inspect texture consumer output");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbos[0]);
                ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                GLES30.glReadPixels(32,8,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                check((pixel.get(2)&255)==64+(id&127),"Producer overwrite changed copied eye pixels");
                // Backing can switch GPU -> CPU -> GPU without changing the
                // texture object. Upload only after acquiring the same fence.
                destination.setData(image(id+32));texture.setNeedsUpdate(true);
                check(texture.beginXrRead(),"CPU backing transition stalled");
                try {
                    texture.updateFromDrawable();
                    check(sync.draw(texture.getTextureId(),128,17,16,false,128,16,true)==id+32,"CPU backing transition lost its image");
                } finally {texture.endXrRead();}
                destination.setData(null);
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Shared texture transfer GPU error");
            }
            // Repeated copies and size changes must preserve the new extent
            // and all channels, including the far corner rather than only ID.
            for(int[] size:new int[][]{{96,9},{96,9},{128,17},{128,17}}) {
                check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot select resized copy producer");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,producerRead[0]);
                texture.copyFromReadBuffer((short)size[0],(short)size[1]);
                check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot inspect resized copy");
                check(texture.beginXrRead(),"Resized publication unavailable");
                try {
                    GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbos[1]);
                    // The producer redefines shared storage when dimensions change.
                    // Quest retains the previous read extent if the same attachment
                    // is merely repeated. Refresh this diagnostic attachment before
                    // checking the far corner, without a CPU/GPU completion wait.
                    GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                        GLES30.GL_TEXTURE_2D,0,0);
                    GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                        GLES30.GL_TEXTURE_2D,texture.getTextureId(),0);
                    check(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,
                        "Resized copy incomplete");
                    ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                    GLES30.glReadPixels(size[0]-1,size[1]-1,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                    boolean correct=(pixel.get(0)&255)==0&&(pixel.get(1)&255)==80+size[1]-1&&
                        (pixel.get(2)&255)==64+((0x12345000+8+64)&127)&&(pixel.get(3)&255)==255;
                    if(!correct) {
                        String copied=rgba(pixel);int copyError=GLES30.glGetError();
                        ByteBuffer original=ByteBuffer.allocateDirect(4);int[] attachment=new int[1];
                        check(EGL14.eglMakeCurrent(display,surface,surface,producer),"Cannot inspect failed copy producer");
                        try {
                            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,producerRead[0]);
                            GLES30.glGetFramebufferAttachmentParameteriv(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                                GLES30.GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME,attachment,0);
                            GLES30.glReadPixels(size[0]-1,size[1]-1,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,original);
                        } finally {check(EGL14.eglMakeCurrent(display,draw,read,consumer),"Cannot restore failed copy consumer");}
                        throw new AssertionError("Repeated/resized copy lost pixels at "+size[0]+"x"+size[1]+": "+
                            copied+" source="+rgba(original)+" attachment="+attachment[0]+" sourceTexture="+source.getTextureId()+
                            " destinationTexture="+texture.getTextureId()+" copyError="+copyError);
                    }
                } finally {texture.endXrRead();}
                // Exercise the actual metadata-reader/shader-copy path too. A
                // correct direct readback alone does not qualify the consumer.
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbos[0]);
                check(texture.beginXrRead(),"Resized shader publication unavailable");
                try {
                    check(sync.draw(texture.getTextureId(),size[0],size[1],size[1]-1,false,
                        size[0],size[1]-1,true)==0x12345000+8+64,"Resized shader copy lost metadata");
                    GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbos[0]);
                    ByteBuffer pixel=ByteBuffer.allocateDirect(4);
                    GLES30.glReadPixels(size[0]-1,size[1]-2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                    check((pixel.get(0)&255)==0&&(pixel.get(1)&255)==80+size[1]-1&&
                        (pixel.get(2)&255)==64+((0x12345000+8+64)&127)&&(pixel.get(3)&255)==255,
                        "Resized shader copy lost corner pixels");
                } finally {texture.endXrRead();}
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Repeated/resized copy GPU error");
            }
        } finally {
            EGL14.eglMakeCurrent(display,surface,surface,producer);
            GLES30.glDeleteFramebuffers(1,producerRead,0);
            EGL14.eglMakeCurrent(display,draw,read,consumer);sync.close();source.destroy();texture.destroy();
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,previousRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,previousDraw[0]);
            GLES30.glDeleteFramebuffers(2,fbos,0);GLES30.glDeleteTextures(1,target,0);
            EGL14.eglDestroySurface(display,surface);EGL14.eglDestroyContext(display,producer);
        }
    }
    private static String rgba(ByteBuffer pixel) {
        return (pixel.get(0)&255)+","+(pixel.get(1)&255)+","+(pixel.get(2)&255)+","+(pixel.get(3)&255);
    }
}
