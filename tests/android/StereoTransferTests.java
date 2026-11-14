package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.nio.ByteBuffer;

/** Explicit off-head GLES fixture. Its synthetic pixels/IDs never enter the game. */
public final class StereoTransferTests {
    private static void check(boolean value,String text) {if(!value) throw new AssertionError(text);}
    public static void run() {
        int[] textures=new int[2],target=new int[1],previousRead=new int[1],previousDraw=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,previousRead,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,previousDraw,0);
        GLES30.glGenTextures(2,textures,0);GLES30.glGenFramebuffers(1,target,0);
        StereoTransfer transfer=new StereoTransfer();
        try {
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[1]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,16,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,target[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,textures[1],0);
            check(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Fixture target incomplete");
            for(int height:new int[]{17,20}) for(boolean flip:new boolean[]{false,true}) for(int id:new int[]{0,256,0x87654321,-1}) {
                ByteBuffer source=ByteBuffer.allocateDirect(128*height*4);
                int[] words={FramePoses.MAGIC,id,~id};
                for(int y=0;y<height;y++) for(int x=0;x<128;x++) {
                    int row=flip ? y : height-1-y;
                    if(row==height-1&&x<96) {
                        byte b=(byte)((words[x/32]&(1<<(x%32)))!=0 ? 255 : 0);
                        source.put(b).put(b).put(b).put((byte)255);
                    } else if(row>=16)source.put((byte)255).put((byte)0).put((byte)255).put((byte)239);
                    else source.put((byte)(x<64 ? row+40 : 0)).put((byte)(x>=64 ? row+80 : 0)).put((byte)(row+120)).put((byte)255);
                }
                source.flip();GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,height,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,source);
                Integer found=transfer.draw(textures[0],128,height,16,!flip,128,16);
                check(found!=null&&found==id,"GLES metadata ID mismatch");
                check(transfer.draw(textures[0],128,height,16,!flip,128,16,false)==id,
                    "Unchanged image must retain its checked frame ID");
                check(transfer.isFlipY()==flip,"Metadata must correct a missing/wrong orientation hint");
                GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,target[0]);
                ByteBuffer result=ByteBuffer.allocateDirect(128*16*4);
                GLES30.glReadPixels(0,0,128,16,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,result);
                for(int y=0;y<16;y++) for(int x=0;x<128;x++) {
                    int row=15-y,offset=(y*128+x)*4;
                    check((result.get(offset)&255)==(x<64 ? row+40 : 0)&&
                        (result.get(offset+1)&255)==(x>=64 ? row+80 : 0)&&
                        (result.get(offset+2)&255)==row+120,"Eye swap, orientation error or metadata in visible pixels");
                }
                check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"GLES transfer error");
            }
            // Missing/corrupt marker must not overwrite a valid output texture.
            ByteBuffer zeros=ByteBuffer.allocateDirect(128*17*4);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,textures[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,128,17,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,zeros);
            check(transfer.draw(textures[0],128,17,16,false,128,16)==null,"Unmarked desktop accepted");
            TexturePublicationTests.run();
            DrawableStorageTests.run();
            AsyncStereoTransferTests.run();
            android.util.Log.i("GK3HDXR","Owned-copy GPU pixels, identity, timing and retention checks passed");
            SharedTextureTransferTests.run();
        } finally {
            transfer.close();GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,previousRead[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,previousDraw[0]);
            GLES30.glDeleteFramebuffers(1,target,0);GLES30.glDeleteTextures(2,textures,0);
        }
    }
}
