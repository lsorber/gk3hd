package org.gk3hd.standalone;

import android.opengl.GLES30;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import org.json.JSONObject;

/** Correctness-only continuous consumer images, never a performance observer. */
public final class StartupFrameStrip implements AutoCloseable {
    private static final int EYE=128, BYTES=EYE*2*EYE*4, LIMIT=768;
    private static final long WINDOW=6_000_000_000L;
    private final File directory;
    private final String token;
    private final OutputStream pixels,records;
    private final ByteBuffer buffer=ByteBuffer.allocateDirect(BYTES);
    private final byte[] bytes=new byte[BYTES];
    private int texture,fbo,count;
    private long first,lastSnapshot;
    private boolean complete,closed;

    public StartupFrameStrip(File directory,String token) throws Exception {
        if(token==null||!token.matches("[0-9a-f]{32}"))throw new IllegalArgumentException("Missing strip session identity");
        this.directory=directory;this.token=token;
        pixels=new BufferedOutputStream(Files.newOutputStream(new File(directory,"startup-strip-"+token+".rgba").toPath(),StandardOpenOption.CREATE_NEW));
        try {records=new BufferedOutputStream(Files.newOutputStream(new File(directory,"startup-strip-"+token+".jsonl").toPath(),StandardOpenOption.CREATE_NEW));}
        catch(Exception failure){pixels.close();throw failure;}
    }
    public boolean complete(){return complete;}

    public void capture(int source,int sourceEye,int pose,long snapshot,long sampled,long received) throws Exception {
        if(closed||source<=0||sourceEye<=0||snapshot<=0||sampled<=0||received<sampled)
            throw new IllegalStateException("Invalid strip image identity");
        if(complete||snapshot==lastSnapshot)return;
        if(count==LIMIT)throw new IllegalStateException("Startup strip image bound exceeded");
        if(first==0)first=received;
        int[] read=new int[1],draw=new int[1],binding=new int[1],pack=new int[5];
        int[] names={GLES30.GL_PIXEL_PACK_BUFFER_BINDING,GLES30.GL_PACK_ALIGNMENT,GLES30.GL_PACK_ROW_LENGTH,GLES30.GL_PACK_SKIP_ROWS,GLES30.GL_PACK_SKIP_PIXELS};
        GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,read,0);
        GLES30.glGetIntegerv(GLES30.GL_DRAW_FRAMEBUFFER_BINDING,draw,0);
        GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,binding,0);
        for(int i=0;i<names.length;i++)GLES30.glGetIntegerv(names[i],pack,i);
        boolean scissor=GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST);
        long started=System.nanoTime();
        try {
            if(texture==0) {
                int[] object=new int[1];GLES30.glGenTextures(1,object,0);texture=object[0];
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
                GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,EYE*2,EYE,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
                GLES30.glGenFramebuffers(1,object,0);fbo=object[0];
                GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo);
                GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture,0);
                if(GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)!=GLES30.GL_FRAMEBUFFER_COMPLETE)
                    throw new IllegalStateException("Startup strip framebuffer incomplete");
            }
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbo);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,source);
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            GLES30.glBlitFramebuffer(0,0,sourceEye*2,sourceEye,0,0,EYE*2,EYE,GLES30.GL_COLOR_BUFFER_BIT,GLES30.GL_NEAREST);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);
            GLES30.glPixelStorei(GLES30.GL_PACK_ALIGNMENT,1);
            GLES30.glPixelStorei(GLES30.GL_PACK_ROW_LENGTH,0);
            GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_ROWS,0);
            GLES30.glPixelStorei(GLES30.GL_PACK_SKIP_PIXELS,0);
            buffer.clear();GLES30.glReadPixels(0,0,EYE*2,EYE,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,buffer);
            int error=GLES30.glGetError();if(error!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Startup strip GPU error: "+error);
            buffer.rewind();buffer.get(bytes);pixels.write(bytes);
            JSONObject row=new JSONObject().put("index",count).put("token",token).put("pose",pose&0xffffffffL)
                .put("snapshot",snapshot).put("sampled_ns",sampled).put("received_ns",received)
                .put("read_begin_ns",started).put("read_end_ns",System.nanoTime()).put("offset",(long)count*BYTES);
            records.write((row.toString()+"\n").getBytes(StandardCharsets.UTF_8));count++;lastSnapshot=snapshot;
            if(received-first>=WINDOW) {
                pixels.flush();records.flush();complete=true;
                JSONObject result=new JSONObject().put("token",token).put("complete",true).put("count",count)
                    .put("width",EYE*2).put("height",EYE).put("format","RGBA8-bottom-up")
                    .put("first_received_ns",first).put("last_received_ns",received).put("bytes",(long)count*BYTES)
                    .put("scope","Every distinct matched consumer image in this observed opening-room window; synchronous reduced readbacks perturb timing; no headset presentation or performance acceptance");
                FixtureReport.write(new File(directory,"startup-strip-"+token+".json"),result.toString());
            }
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,read[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,draw[0]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,binding[0]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,pack[0]);
            for(int i=1;i<names.length;i++)GLES30.glPixelStorei(names[i],pack[i]);
            if(scissor)GLES30.glEnable(GLES30.GL_SCISSOR_TEST);
        }
    }
    @Override public void close() throws Exception {
        if(closed)return;closed=true;
        try {pixels.close();}finally {records.close();
            if(fbo!=0)GLES30.glDeleteFramebuffers(1,new int[]{fbo},0);
            if(texture!=0)GLES30.glDeleteTextures(1,new int[]{texture},0);
        }
    }
}
