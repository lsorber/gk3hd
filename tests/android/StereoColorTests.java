package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;

/** Actual GPU transfer functions, including a deliberately wrong-color control. */
public final class StereoColorTests {
    private static void check(boolean value,String text) {if(!value)throw new AssertionError(text);}
    private static int linear(int value) {
        double encoded=value/255.0;
        return (int)Math.round(255*(encoded<=.04045 ? encoded/12.92 : Math.pow((encoded+.055)/1.055,2.4)));
    }
    public static int run() {
        int[] old=new int[4],textures=new int[2],target=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,old,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,old,1);
        GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,old,2);
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,old,3);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,target,0);
        int checks=0;
        ByteBuffer input=ByteBuffer.allocateDirect(256*2*4),output=ByteBuffer.allocateDirect(256*4);
        // Row zero represents transport metadata and must not be copied.
        for(int x=0;x<256;x++)input.putInt(0);
        for(int x=0;x<256;x++)input.put((byte)x).put((byte)(255-x)).put((byte)(x^85)).put((byte)x);
        input.flip();
        try(StereoCopy encoded=new StereoCopy();StereoCopy compositor=new StereoCopy(true)) {
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,256,2,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,input);
            for(int format:new int[]{GLES30.GL_RGBA8,GLES30.GL_SRGB8_ALPHA8}) {
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,format,256,1,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
                GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,target[0]);
                GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
                check(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Color target incomplete");
                for(boolean conversion:new boolean[]{false,true}) {
                    (conversion ? compositor : encoded).draw(textures[0],256,2,1,false,256,1);
                    output.clear();GLES30.glReadPixels(0,0,256,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,output);
                    int wrongMidtones=0;
                    for(int x=0;x<256;x++)for(int c=0;c<4;c++) {
                        int value=c==0||c==3 ? x : c==1 ? 255-x : x^85;
                        int actual=output.get(x*4+c)&255;
                        if(c<3&&format==GLES30.GL_SRGB8_ALPHA8&&!conversion) {
                            if(Math.abs(actual-value)>8)wrongMidtones++;
                        } else {
                            int expected=c<3&&conversion&&format==GLES30.GL_RGBA8 ? linear(value) : value;
                            int tolerance=c==3||!conversion ? 0 : 1;
                            check(Math.abs(actual-expected)<=tolerance,"Wrong compositor color format="+format+" conversion="+conversion+" x="+x+" channel="+c+" expected="+expected+" actual="+actual);
                            checks++;
                        }
                    }
                    if(format==GLES30.GL_SRGB8_ALPHA8&&!conversion)
                        check(wrongMidtones>500,"Negative control did not expose double color encoding");
                    check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Color copy GL error");
                }
            }
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glActiveTexture(GLES30.GL_TEXTURE0);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,old[3]);
            GLES30.glActiveTexture(old[2]);GLES30.glDeleteFramebuffers(1,target,0);GLES30.glDeleteTextures(2,textures,0);
        }
        return checks;
    }
}
