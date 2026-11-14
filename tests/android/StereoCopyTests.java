package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;

/** Explicit GPU qualification for cropped eyes, pixel centers and caller state. */
public final class StereoCopyTests {
    private static void check(boolean okay,String text) {if(!okay)throw new AssertionError(text);}
    public static long run() {
        int[] textures=new int[2],fbo=new int[1],old=new int[4],viewport=new int[4],oldBlend=new int[6];
        int[] blendNames={GLES30.GL_BLEND_SRC_RGB,GLES30.GL_BLEND_DST_RGB,GLES30.GL_BLEND_SRC_ALPHA,GLES30.GL_BLEND_DST_ALPHA,GLES30.GL_BLEND_EQUATION_RGB,GLES30.GL_BLEND_EQUATION_ALPHA};
        for(int i=0;i<blendNames.length;i++)GLES30.glGetIntegerv(blendNames[i],oldBlend,i);
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,old,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,old,1);
        GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,old,2);
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,old,3);
        GLES30.glGetIntegerv(GLES30.GL_VIEWPORT,viewport,0);
        boolean scissor=GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST);
        boolean blend=GLES30.glIsEnabled(GLES30.GL_BLEND);
        boolean[] mask=new boolean[4];GLES30.glGetBooleanv(GLES30.GL_COLOR_WRITEMASK,mask,0);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,fbo,0);
        StereoCopy copy=new StereoCopy();long checked=0;
        // Reuse bounded CPU buffers across all cases instead of accumulating
        // native direct buffers until the Android collector happens to run.
        ByteBuffer input=ByteBuffer.allocateDirect(4120*2064*4);
        ByteBuffer output=ByteBuffer.allocateDirect(4120*2060*4);
        byte[] pixels=new byte[4120*2060*4];
        try {
            for(int[] extent:new int[][]{{4120,2061,2060,4120,2060},{4120,2064,2060,4120,2060},
                {4120,2064,2060,1280,800},{2060,1032,1030,2060,1030},
                {256,132,128,1024,512},{256,132,129,256,129},
                {256,132,130,256,130},{256,132,131,256,131}}) {
                int sw=extent[0],sh=extent[1],visible=extent[2],dw=extent[3],dh=extent[4];
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,dw,dh,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
                GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo[0]);
                GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
                check(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Copy target incomplete");
                for(boolean flip:new boolean[]{false,true}) {
                    // Store the same visible image in either physical orientation.
                    // Poison every metadata/padding pixel so copying a spare row
                    // cannot accidentally match the independent visible oracle.
                    input.clear();
                    for(int y=0;y<sh;y++)for(int x=0;x<sw;x++) {
                        int logical=flip ? visible-1-y : y-(sh-visible);
                        if(logical<0||logical>=visible)
                            input.put((byte)255).put((byte)0).put((byte)255).put((byte)239);
                        else input.put((byte)((x&1)*255)).put((byte)((logical&1)*255))
                            .put((byte)(x%251)).put((byte)(x*13+logical*7));
                    }
                    input.flip();
                    GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
                    GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                    GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,sw,sh,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,input);
                    // These states would clip, blend or suppress a naive shader copy.
                    GLES30.glEnable(GLES30.GL_SCISSOR_TEST);GLES30.glEnable(GLES30.GL_BLEND);
                    GLES30.glColorMask(false,false,false,false);GLES30.glViewport(3,5,7,9);
                    GLES30.glActiveTexture(GLES30.GL_TEXTURE1);
                    copy.draw(textures[0],sw,sh,visible,flip,dw,dh);
                    check(GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST)&&GLES30.glIsEnabled(GLES30.GL_BLEND),"Copy changed caller enables");
                    int[] actual=new int[4];boolean[] writes=new boolean[4];
                    GLES30.glGetIntegerv(GLES30.GL_VIEWPORT,actual,0);
                    check(actual[0]==3&&actual[1]==5&&actual[2]==7&&actual[3]==9,"Copy changed caller viewport");
                    GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,actual,0);
                    check(actual[0]==GLES30.GL_TEXTURE1,"Copy changed active texture unit");
                    GLES30.glGetBooleanv(GLES30.GL_COLOR_WRITEMASK,writes,0);
                    check(!writes[0]&&!writes[1]&&!writes[2]&&!writes[3],"Copy changed write masks");
                    GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,actual,0);
                    check(actual[0]==fbo[0],"Copy changed output framebuffer");
                    output.clear();GLES30.glReadPixels(0,0,dw,dh,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,output);
                    output.position(0);output.get(pixels,0,dw*dh*4);
                    for(int y=0;y<dh;y++)for(int x=0;x<dw;x++) {
                        int sx=(int)(((long)x*2+1)*sw/(dw*2));
                        int sy=(int)(((long)y*2+1)*visible/(dh*2));
                        int b=(y*dw+x)*4;
                        if((byte)((sx&1)*255)!=pixels[b]||(byte)((sy&1)*255)!=pixels[b+1]||
                            (byte)(sx%251)!=pixels[b+2]||(byte)(sx*13+sy*7)!=pixels[b+3])
                            throw new AssertionError("Incorrect eye pixel at "+x+","+y+" flip="+flip+" source="+sw+"x"+sh);
                    }
                    checked+=(long)dw*dh*4;
                    check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Copy produced GL error");
                    GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
                }
            }
            ByteBuffer captions=ByteBuffer.allocateDirect(4*3*4);
            for(int y=0;y<3;y++)for(int x=0;x<4;x++) {
                int[] color=y==2 ? new int[]{255,0,255,255} :
                    x==0 ? new int[]{0,0,0,0} : x==1 ? new int[]{64,32,16,128} :
                    x==2 ? new int[]{0,0,0,255} : new int[]{255,255,255,255};
                for(int c:color)captions.put((byte)c);
            }
            captions.flip();GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,4,3,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,captions);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,4,2,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);GLES30.glColorMask(true,true,true,true);
            GLES30.glClearColor(64/255f,128/255f,191/255f,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glBlendEquationSeparate(GLES30.GL_FUNC_REVERSE_SUBTRACT,GLES30.GL_FUNC_SUBTRACT);
            GLES30.glBlendFuncSeparate(GLES30.GL_DST_COLOR,GLES30.GL_SRC_COLOR,GLES30.GL_ZERO,GLES30.GL_ONE);
            int[] beforeBlend=new int[6];for(int i=0;i<blendNames.length;i++)GLES30.glGetIntegerv(blendNames[i],beforeBlend,i);
            copy.draw(textures[0],4,3,2,true,4,2,true);
            for(int i=0;i<blendNames.length;i++){int[] actual={0};GLES30.glGetIntegerv(blendNames[i],actual,0);check(actual[0]==beforeBlend[i],"Overlay changed caller blend function/equation");}
            ByteBuffer composed=ByteBuffer.allocateDirect(4*2*4);GLES30.glReadPixels(0,0,4,2,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,composed);
            int[][] expected={{64,128,191,255},{96,96,111,255},{0,0,0,255},{255,255,255,255}};
            for(int y=0;y<2;y++)for(int x=0;x<4;x++)for(int c=0;c<4;c++)
                check(Math.abs((composed.get((y*4+x)*4+c)&255)-expected[x][c])<=1,"Movie overlay lost transparent/black/glyph coverage or copied its metadata row");
            checked+=32;
        } finally {
            copy.close();GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glActiveTexture(GLES30.GL_TEXTURE0);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,old[3]);
            GLES30.glActiveTexture(old[2]);GLES30.glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);
            GLES30.glColorMask(mask[0],mask[1],mask[2],mask[3]);
            if(scissor)GLES30.glEnable(GLES30.GL_SCISSOR_TEST);else GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            if(blend)GLES30.glEnable(GLES30.GL_BLEND);else GLES30.glDisable(GLES30.GL_BLEND);
            GLES30.glBlendFuncSeparate(oldBlend[0],oldBlend[1],oldBlend[2],oldBlend[3]);GLES30.glBlendEquationSeparate(oldBlend[4],oldBlend[5]);
            GLES30.glDeleteFramebuffers(1,fbo,0);GLES30.glDeleteTextures(2,textures,0);
        }
        return checked;
    }
}
