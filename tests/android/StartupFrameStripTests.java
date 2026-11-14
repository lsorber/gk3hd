package org.gk3hd.standalone;

import android.content.Context;
import android.opengl.GLES30;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONObject;

/** Real GLES pixels and hostile pack/scissor state before the game starts. */
public final class StartupFrameStripTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void run(Context context) {
        try {
            String token=java.util.UUID.randomUUID().toString().replace("-","");
            File root=new File(context.getCacheDir(),"startup-strip-fixture-"+token);
            check(root.mkdir(),"Fixture directory already exists");
            int[] texture=new int[1],framebuffer=new int[1],pbo=new int[1];
            GLES30.glGenTextures(1,texture,0);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,512,256,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glGenFramebuffers(1,framebuffer,0);GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,framebuffer[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture[0],0);
            check(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Fixture target incomplete");
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);GLES30.glColorMask(true,true,true,true);
            GLES30.glClearColor(1,0,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glEnable(GLES30.GL_SCISSOR_TEST);GLES30.glScissor(256,128,256,128);
            GLES30.glClearColor(0,1,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glGenBuffers(1,pbo,0);GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,pbo[0]);
            GLES30.glBufferData(GLES30.GL_PIXEL_PACK_BUFFER,1024,null,GLES30.GL_STREAM_READ);
            GLES30.glPixelStorei(GLES30.GL_PACK_ROW_LENGTH,300);GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_ROWS,2);
            GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_PIXELS,3);GLES30.glPixelStorei(GLES30.GL_PACK_ALIGNMENT,8);
            try(StartupFrameStrip strip=new StartupFrameStrip(root,token)) {
                long now=System.nanoTime();strip.capture(framebuffer[0],256,123,1,now-10,now);
                strip.capture(framebuffer[0],256,123,1,now-10,now+1); // Same image is not appended twice.
                strip.capture(framebuffer[0],256,124,2,now+6_000_000_000L-10,now+6_000_000_000L);
                check(strip.complete(),"Bounded window did not complete");
            }
            int[] actual=new int[1];GLES30.glGetIntegerv(GLES30.GL_PIXEL_PACK_BUFFER_BINDING,actual,0);check(actual[0]==pbo[0],"Pack buffer lost");
            int[] names={GLES30.GL_PACK_ROW_LENGTH,GLES30.GL_PACK_SKIP_ROWS,GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_ALIGNMENT};
            int[] expected={300,2,3,8};
            for(int i=0;i<names.length;i++){GLES30.glGetIntegerv(names[i],actual,0);check(actual[0]==expected[i],"Pack state lost");}
            check(GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST),"Scissor state lost");
            byte[] bytes=Files.readAllBytes(new File(root,"startup-strip-"+token+".rgba").toPath());
            check(bytes.length==2*256*128*4,"Strip image count changed");
            for(int frame=0;frame<2;frame++)for(int y=0;y<128;y++)for(int x=0;x<256;x++) {
                int p=((frame*128+y)*256+x)*4;boolean green=x>=128&&y>=64;
                check((bytes[p]&255)==(green?0:255)&&(bytes[p+1]&255)==(green?255:0)&&bytes[p+2]==0&&(bytes[p+3]&255)==255,"Wrong eye, orientation or crop pixels");
            }
            JSONObject result=new JSONObject(new String(Files.readAllBytes(new File(root,"startup-strip-"+token+".json").toPath()),java.nio.charset.StandardCharsets.UTF_8));
            check(result.getInt("count")==2&&result.getBoolean("complete"),"Strip completion disagrees with bytes");
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);GLES30.glPixelStorei(GLES30.GL_PACK_ROW_LENGTH,0);
            GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_ROWS,0);GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_PIXELS,0);GLES30.glPixelStorei(GLES30.GL_PACK_ALIGNMENT,4);
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,0);
            GLES30.glDeleteBuffers(1,pbo,0);GLES30.glDeleteFramebuffers(1,framebuffer,0);GLES30.glDeleteTextures(1,texture,0);
            check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Strip fixture GPU error");
            FixtureReport.write(new File(context.getFilesDir(),"startup-strip-gpu-check-"+token+".json"),result.put("full_pixel_check",true).toString());
        }catch(Exception failure){throw new IllegalStateException("Startup strip fixture failed",failure);}
    }
}
