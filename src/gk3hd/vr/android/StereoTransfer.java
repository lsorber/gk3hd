package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;

/** Exact-size GPU eye copy with one small, checked metadata readback. */
public final class StereoTransfer {
    private final ByteBuffer marker=ByteBuffer.allocateDirect(FramePoses.PIXELS*4);
    private final int[] readBuffer=new int[1];
    private int lastTexture;
    private int lastWidth,lastHeight,lastVisibleHeight;
    private Integer lastId;
    private boolean resolvedFlipY;
    private final GlTransferProfile profile;
    private final boolean linearOutput;
    private StereoCopy eyeCopy;
    public StereoTransfer() {this(null);}
    public StereoTransfer(GlTransferProfile profile) {this(profile,false);}
    public StereoTransfer(GlTransferProfile profile,boolean linearOutput) {
        this.profile=profile;this.linearOutput=linearOutput;GLES30.glGenFramebuffers(1,readBuffer,0);
    }
    public Integer draw(int texture,int width,int height,int visibleHeight,boolean flipY,int outputWidth,int outputHeight) {
        return draw(texture,width,height,visibleHeight,flipY,outputWidth,outputHeight,true);
    }
    /** contentChanged is supplied under the producer drawable's render lock.
     * Re-presenting the same image retains its checked ID and orientation,
     * rather than synchronously reading GPU metadata at every display tick.
     */
    public Integer draw(int texture,int width,int height,int visibleHeight,boolean flipY,int outputWidth,int outputHeight,boolean contentChanged) {
        if(width<FramePoses.PIXELS||height<2||visibleHeight<1||visibleHeight>=height||outputWidth<=0||outputHeight<=0)
            throw new IllegalArgumentException("Invalid stereo transport extent");
        int[] previous=new int[1];GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,previous,0);
        GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,readBuffer[0]);
        try {
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,texture,0);
            if(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                throw new IllegalStateException("Stereo transport framebuffer incomplete");
            if(texture!=lastTexture||width!=lastWidth||height!=lastHeight||visibleHeight!=lastVisibleHeight) {
                lastTexture=texture;lastWidth=width;lastHeight=height;lastVisibleHeight=visibleHeight;resolvedFlipY=flipY;lastId=null;
            }
            Integer id=lastId;
            if(contentChanged||id==null) {
                id=readMarker(resolvedFlipY ? height-1 : 0);
                if(id==null) {
                    // DRI3/Present GPU copies do not carry GLX's flipY property.
                    // The checked marker identifies the actual metadata edge;
                    // never guess orientation from a missing presentation hint.
                    id=readMarker(resolvedFlipY ? 0 : height-1);
                    if(id!=null) resolvedFlipY=!resolvedFlipY;
                }
                lastId=id;
            }
            if(id!=null) {
                // Copy visible eyes only, preserving orientation. No game-image
                // pixels take a CPU round-trip and no metadata reaches the eyes.
                int copy=profile==null ? 0 : profile.begin(GlTransferProfile.SYNC_EYE_COPY,id);
                try {
                    if(eyeCopy==null)eyeCopy=new StereoCopy(linearOutput);
                    eyeCopy.draw(texture,width,height,visibleHeight,resolvedFlipY,outputWidth,outputHeight);
                }
                finally {if(profile!=null) profile.end(copy);}
            }
            return id;
        } finally {GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,previous[0]);}
    }
    private Integer readMarker(int y) {
        marker.clear();GLES30.glReadPixels(0,y,FramePoses.PIXELS,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,marker);
        return FramePoses.decode(marker);
    }
    public boolean isFlipY() {return resolvedFlipY;}
    public void close() {if(eyeCopy!=null)eyeCopy.close();eyeCopy=null;GLES30.glDeleteFramebuffers(1,readBuffer,0);}
}
