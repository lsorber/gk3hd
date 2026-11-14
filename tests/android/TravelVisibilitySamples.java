package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.GLES30;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

/** Deliberately intrusive source-visibility checks, never performance evidence. */
public final class TravelVisibilitySamples {
    private final File output;
    private final int width,height;
    private final ByteBuffer pixels;
    private long lastAt,lastSnapshot;
    private int lastScene=-1,count;
    public TravelVisibilitySamples(Activity activity,int width,int height) throws Exception {
        String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
        if(token==null||!token.matches("[a-f0-9]{32}")||width<2||width>8192||width%2!=0||height<4)
            throw new IllegalArgumentException("Owned bounded visibility fixture required");
        this.width=width;this.height=height;pixels=ByteBuffer.allocateDirect(width*4);
        output=new File(activity.getFilesDir(),"travel-visibility-"+token+".jsonl");
        if(!output.createNewFile())throw new IllegalStateException("Preserve preceding visibility evidence");
        append(new JSONObject().put("token",token).put("width",width).put("height",height)
            .put("scope","Simulated-viewer source visibility during full-stick travel; intrusive readback, not FPS or headset delivery"));
    }
    private void append(JSONObject row) throws Exception {
        try(FileOutputStream file=new FileOutputStream(output,true)) {
            file.write((row.toString()+"\n").getBytes(StandardCharsets.UTF_8));file.getFD().sync();
        }
    }
    public void sample(int scene,JSONObject camera,int fbo,int pose,long snapshot,long sampled,long received) throws Exception {
        if(scene==lastScene&&(snapshot==lastSnapshot||received-lastAt<500_000_000L))return;
        if(++count>128)throw new IllegalStateException("Visibility sample bound exceeded");
        int[] names={GLES30.GL_READ_FRAMEBUFFER_BINDING,GLES30.GL_PIXEL_PACK_BUFFER_BINDING,
            GLES30.GL_PACK_ALIGNMENT,GLES30.GL_PACK_ROW_LENGTH,GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_SKIP_ROWS};
        int[] old=new int[names.length],maximum=new int[2],nonblack=new int[2];
        for(int i=0;i<names.length;i++)GLES30.glGetIntegerv(names[i],old,i);
        int error=GLES30.glGetError();
        if(error!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Prior GL error at visibility boundary: "+error);
        try {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo);GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);
            for(int i=2;i<names.length;i++)GLES30.glPixelStorei(names[i],i==2?1:0);
            for(int y:new int[]{height/4,height/2,height*3/4}) {
                pixels.clear();GLES30.glReadPixels(0,y,width,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixels);
                for(int x=0;x<width;x++) {
                    int value=0;for(int c=0;c<3;c++)value=Math.max(value,pixels.get(x*4+c)&255);
                    int eye=x/(width/2);maximum[eye]=Math.max(maximum[eye],value);
                    if(value>3)nonblack[eye]++;
                }
            }
            error=GLES30.glGetError();
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[1]);
            for(int i=2;i<names.length;i++)GLES30.glPixelStorei(names[i],old[i]);
        }
        append(new JSONObject().put("scene_index",scene).put("pose_id",pose&0xffffffffL).put("snapshot",snapshot)
            .put("sampled_ns",sampled).put("received_ns",received).put("readback_end_ns",System.nanoTime())
            .put("camera_observation",camera).put("max_rgb",new JSONArray(maximum)).put("nonblack_pixels",new JSONArray(nonblack))
            .put("rows_per_eye",3).put("gl_error",error));
        if(error!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Visibility readback failed: "+error);
        lastAt=received;lastSnapshot=snapshot;lastScene=scene;
    }
    public void endScene(int scene,JSONObject camera,long now) throws Exception {
        append(new JSONObject().put("end_scene",scene).put("observed_ns",now).put("camera_observation",camera));
    }
}
