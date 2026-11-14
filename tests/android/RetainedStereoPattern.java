package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Owned GPU pixels with a bounded source pause. Never manufactures tracking. */
final class RetainedStereoPattern implements XrPresenter.Source {
    int width,height,draws,updates,heldDraws,recoveredDraws,trackingSamples,validSamples;
    Integer inputId,renderedId;
    boolean located,closed;
    long first,lastUpdate,snapshot;
    private int texture,buffer,sourceId;
    private final ByteBuffer marker=ByteBuffer.allocateDirect(FramePoses.PIXELS*4);
    private final ByteBuffer left=ByteBuffer.allocateDirect(4),right=ByteBuffer.allocateDirect(4);
    @Override public void configure(int w,int h) {
        if(w*2<FramePoses.PIXELS||h<4)throw new IllegalArgumentException("Pattern extent too small");
        width=w;height=h;
    }
    @Override public void linearOutput(boolean value) {}
    @Override public void onSurfaceCreated(GL10 gl,EGLConfig config) {
        int[] ids=new int[1];GLES30.glGenTextures(1,ids,0);texture=ids[0];
        GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
        GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,width*2,height);
        GLES30.glGenFramebuffers(1,ids,0);buffer=ids[0];
        int[] previous=new int[1];GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,previous,0);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,buffer);
        GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture,0);
        if(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
            throw new IllegalStateException("Pattern GPU attachment incomplete");
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,previous[0]);
    }
    @Override public void onSurfaceChanged(GL10 gl,int w,int h) {}
    @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,
            float hz,int id,XrInput inputs,StereoViews views) {
        inputId=id;located=(flags&3)==3&&views!=null;trackingSamples++;if(located)validSamples++;
    }
    @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int id,XrInput inputs) {
        tracking(head,flags,ipd,fovX,fovY,hz,id,inputs,null);
    }
    @Override public boolean hasStereoFrame(){return located;}
    @Override public Integer renderedFrameId(){return renderedId;}
    @Override public long renderedSnapshot(){return renderedId==null?0:snapshot;}
    @Override public void onDrawFrame(GL10 gl){drawAt(System.nanoTime());}
    // Explicit times below are only used by the isolated non-XR GPU fixture.
    void drawAt(long now) {
        if(!located||inputId==null)throw new IllegalStateException("No valid source pose identity");
        if(first==0)first=now;
        boolean held=now-first>=200_000_000L&&now-first<850_000_000L;
        boolean recovery=now-first>=850_000_000L;
        int[] read=new int[1],draw=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,read,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,draw,0);
        GLES30.glDisable(GLES30.GL_DEPTH_TEST);GLES30.glDisable(GLES30.GL_BLEND);
        if(!held||snapshot==0) {
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,buffer);
            GLES30.glEnable(GLES30.GL_SCISSOR_TEST);
            GLES30.glScissor(0,0,width,height);GLES30.glClearColor(recovery?0:1,0,recovery?1:0,1);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glScissor(width,0,width,height);GLES30.glClearColor(recovery?1:0,1,0,1);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            sourceId=inputId;int[] words={FramePoses.MAGIC,sourceId,~sourceId};
            for(int i=0;i<FramePoses.PIXELS;i++) {
                float bit=(words[i/32]&(1<<(i%32)))==0?0:1;
                GLES30.glScissor(i,0,1,1);GLES30.glClearColor(bit,bit,bit,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            }
            updates++;snapshot++;lastUpdate=now;
        } else heldDraws++;
        GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,buffer);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,draw[0]);
        GLES30.glBlitFramebuffer(0,0,width*2,height,0,0,width*2,height,GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,draw[0]);
        marker.clear();GLES30.glReadPixels(0,0,FramePoses.PIXELS,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,marker);
        Integer decoded=FramePoses.decode(marker);
        left.clear();right.clear();
        GLES30.glReadPixels(width/2,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,left);
        GLES30.glReadPixels(width+width/2,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,right);
        int[] expected=recovery?new int[]{0,0,255,255,255,255,0,255}:new int[]{255,0,0,255,0,255,0,255};
        for(int i=0;i<4;i++)if((left.get(i)&255)!=expected[i]||(right.get(i)&255)!=expected[i+4])
            throw new IllegalStateException("Original stereo source pixels changed");
        if(decoded==null||decoded!=sourceId)throw new IllegalStateException("GPU snapshot identity changed");
        renderedId=decoded;draws++;if(recovery)recoveredDraws++;
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,read[0]);
        GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,draw[0]);
        int error=GLES30.glGetError();if(error!=0)throw new IllegalStateException("Pattern GL error "+error);
    }
    @Override public void close(){
        if(texture!=0)GLES30.glDeleteTextures(1,new int[]{texture},0);
        if(buffer!=0)GLES30.glDeleteFramebuffers(1,new int[]{buffer},0);
        texture=buffer=0;closed=true;
    }
}
