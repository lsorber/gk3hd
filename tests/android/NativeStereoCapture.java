package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.io.File;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;

/** Read one owned packed stereo target on its GL thread after timing ends. */
final class NativeStereoCapture {
    private NativeStereoCapture() {}

    static void write(File directory,String token,int eyeWidth,int height) throws Exception {
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Missing capture token");
        new FixtureEyeExtent(eyeWidth,height);
        int width=eyeWidth*2;
        Path destination=new File(directory,"native-stereo-"+token+".png").toPath();
        Path pending=destination.resolveSibling(destination.getFileName()+".pending");
        if(Files.exists(destination)||Files.exists(pending))throw new IllegalStateException("Preserve preceding stereo capture");
        int[] names={GLES30.GL_DRAW_FRAMEBUFFER_BINDING,GLES30.GL_READ_FRAMEBUFFER_BINDING,
            GLES30.GL_PIXEL_PACK_BUFFER_BINDING,GLES30.GL_PACK_ALIGNMENT,GLES30.GL_PACK_ROW_LENGTH,
            GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_SKIP_ROWS};
        int[] old=new int[names.length];
        for(int i=0;i<names.length;i++)GLES30.glGetIntegerv(names[i],old,i);
        if(old[0]==0||GLES30.glGetError()!=GLES30.GL_NO_ERROR)
            throw new IllegalStateException("Stereo capture requires an owned draw target and clean GL state");
        ByteBuffer pixels=ByteBuffer.allocateDirect(Math.multiplyExact(Math.multiplyExact(width,height),4));
        try {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);
            for(int i=3;i<names.length;i++)GLES30.glPixelStorei(names[i],i==3?4:0);
            GLES30.glReadPixels(0,0,width,height,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
            if(GLES30.glGetError()!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Native stereo readback failed");
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[1]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[2]);
            for(int i=3;i<names.length;i++)GLES30.glPixelStorei(names[i],old[i]);
        }
        try(OutputStream output=Files.newOutputStream(pending,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
            RgbaPng.write(output,pixels,width,height);
        }
        Files.move(pending,destination,StandardCopyOption.ATOMIC_MOVE);
    }
}
