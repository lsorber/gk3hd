package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.GLES30;
import android.opengl.GLES31;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import org.json.JSONObject;

/** Debug-only, post-measurement comparison of one retained image and its output.
 * Uses the existing selected lease on the owning GL thread. No new acquisition,
 * copied-image substitution, completion override or producer-release shortcut.
 */
public final class SelectedImagePixels {
    private static final int GL_BGRA8_EXT=0x93A1;
    private SelectedImagePixels() { }
    private static Object field(Object object,String name) throws Exception {
        Field field=object.getClass().getDeclaredField(name);
        field.setAccessible(true);return field.get(object);
    }
    private static int integer(Object object,String name) throws Exception {
        return ((Integer)field(object,name)).intValue();
    }
    private static void require(boolean okay,String reason) {
        if(!okay)throw new IllegalStateException(reason);
    }
    private static void write(Activity activity,String leaf,ByteBuffer bytes) throws Exception {
        File target=new File(activity.getFilesDir(),leaf);
        require(!target.exists(),"Preserve the preceding selected-image evidence");
        bytes.position(0);
        try(FileOutputStream out=new FileOutputStream(target)) {
            java.nio.channels.FileChannel channel=out.getChannel();
            while(bytes.hasRemaining())require(channel.write(bytes)>0,"Incomplete pixel export");
        }
        bytes.position(0);
    }
    private static ByteBuffer read(int width,int row,int rows) {
        ByteBuffer bytes=ByteBuffer.allocateDirect(width*rows*4).order(ByteOrder.LITTLE_ENDIAN);
        GLES30.glReadPixels(0,row,width,rows,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,bytes);
        require(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Selected-image readback failed");
        return bytes;
    }
    public static void capture(Activity activity,XrPresenter.Source source,int outputFbo,int eyeWidth,int eyeHeight) throws Exception {
        require(com.winlator.BuildConfig.DEBUG,"Selected-image pixels require the private debug fixture");
        new FixtureEyeExtent(eyeWidth,eyeHeight);
        long snapshot=source.renderedSnapshot();Integer pose=source.renderedFrameId();
        Object transfer=field(source,"asyncTransfer"),selected=field(transfer,"selected");
        require(selected!=null&&snapshot>0&&pose!=null,"No exact selected image");
        BorrowedPresentFrames.Frame lease=(BorrowedPresentFrames.Frame)field(selected,"lease");
        require(lease!=null,"Selected source must still hold its producer lease");
        int width=integer(transfer,"width"),height=integer(transfer,"height");
        int visible=integer(transfer,"visibleHeight"),texture=integer(selected,"texture");
        boolean flip=((Boolean)field(selected,"flip")).booleanValue();
        require(width==eyeWidth*2&&visible==eyeHeight&&height>visible&&texture==lease.texture,
            "Selected source/output dimensions or lease changed");
        require(((Long)field(selected,"sequence")).longValue()==snapshot&&pose.equals(field(selected,"id")),
            "Selected source does not identify the drawn output");
        ImageIdentity.Resolved composition=(ImageIdentity.Resolved)field(selected,"composition");
        require(composition!=null&&composition.pose==pose.intValue(),"Missing exact composition identity");
        if(activity.getIntent().getBooleanExtra("gk3hd_test_compare_padded_blit",false)) {
            require(height==visible+4&&visible>2048&&flip&&composition.movie==0&&
                !source.renderedWithPaddedEyeBlit()&&!((Boolean)field(transfer,"linearOutput")).booleanValue(),
                "Compare a flipped, padded, encoded game image against the shader");
            JSONObject comparison=comparePaddedBlit(outputFbo,texture,width,visible);
            require(field(transfer,"selected")==selected&&field(selected,"lease")==lease&&
                source.renderedSnapshot()==snapshot&&pose.equals(source.renderedFrameId()),
                "Selected lease changed during the blit comparison");
            String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
            require(token!=null&&token.matches("[a-f0-9]{32}"),"Missing diagnostic owner token");
            comparison.put("token",token).put("snapshot",snapshot).put("pose_id",pose.longValue()&0xffffffffL)
                .put("composition",composition.composition).put("present_serial",lease.presentSerial&0xffffffffL)
                .put("lease_sequence",lease.sequence).put("same_selected_lease",true).put("post_measurement_only",true);
            write(activity,"padded-blit-"+token+".json",ByteBuffer.wrap(comparison.toString(2)
                .getBytes(java.nio.charset.StandardCharsets.UTF_8)));
            return;
        }
        final int rows=128;
        int sourceRow=flip ? visible-rows : height-visible;
        int[] names={GLES30.GL_READ_FRAMEBUFFER_BINDING,GLES30.GL_DRAW_FRAMEBUFFER_BINDING,
            GLES30.GL_PIXEL_PACK_BUFFER_BINDING,GLES30.GL_PACK_ALIGNMENT,GLES30.GL_PACK_ROW_LENGTH,
            GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_SKIP_ROWS};
        int[] old=new int[names.length],temporary={0};
        for(int i=0;i<names.length;i++)GLES30.glGetIntegerv(names[i],old,i);
        require(old[0]==outputFbo&&old[1]==outputFbo,"Unexpected output framebuffer at capture boundary");
        require(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Preexisting GL error at diagnostic entry");
        ByteBuffer output,input;
        try {
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);
            for(int i=3;i<names.length;i++)GLES30.glPixelStorei(names[i],i==3 ? 4 : 0);
            output=read(width,0,rows);
            GLES30.glGenFramebuffers(1,temporary,0);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,temporary[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,texture,0);
            require(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,
                "Selected producer image is not readable");
            input=read(width,sourceRow,rows);
            require(field(transfer,"selected")==selected&&field(selected,"lease")==lease&&
                source.renderedSnapshot()==snapshot&&pose.equals(source.renderedFrameId()),
                "Image identity/lease changed during paired readback");
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[2]);
            for(int i=3;i<names.length;i++)GLES30.glPixelStorei(names[i],old[i]);
            if(temporary[0]!=0)GLES30.glDeleteFramebuffers(1,temporary,0);
        }
        // Preserve raw source orientation. Compare the exact integer-pixel
        // mapping used by StereoCopy, without fitting or filtering any pixels.
        long rgbDifferent=0,rgbaDifferent=0,sourceBlack=0,outputBlack=0;
        for(int y=0;y<rows;y++)for(int x=0;x<width;x++) {
            int s=input.getInt(((flip ? rows-1-y : y)*width+x)*4);
            int o=output.getInt((y*width+x)*4);
            if(s!=o)rgbaDifferent++;
            if((s&0xffffff)!=(o&0xffffff))rgbDifferent++;
            if((s&0xffffff)==0)sourceBlack++;
            if((o&0xffffff)==0)outputBlack++;
        }
        String token=activity.getIntent().getStringExtra("gk3hd_observation_token");
        require(token!=null&&token.matches("[a-f0-9]{32}"),"Missing diagnostic owner token");
        String stem="selected-image-"+token;
        write(activity,stem+"-source.rgba",input);write(activity,stem+"-output.rgba",output);
        JSONObject report=new JSONObject().put("token",token).put("snapshot",snapshot)
            .put("pose_id",pose.longValue()&0xffffffffL).put("composition",composition.composition)
            .put("lease_sequence",lease.sequence).put("window",lease.windowId&0xffffffffL)
            .put("pixmap",lease.pixmapId&0xffffffffL).put("present_serial",lease.presentSerial&0xffffffffL)
            .put("source_width",width).put("source_height",height).put("visible_height",visible)
            .put("source_first_row",sourceRow).put("output_first_row",0).put("rows",rows)
            .put("source_flipped",flip).put("rgb_different_pixels",rgbDifferent)
            .put("rgba_different_pixels",rgbaDifferent).put("source_black_pixels",sourceBlack)
            .put("output_black_pixels",outputBlack).put("post_measurement_only",true)
            .put("same_selected_lease_through_reads",true);
        write(activity,stem+".json",ByteBuffer.wrap(report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }

    private static JSONObject comparePaddedBlit(int outputFbo,int source,int width,int height) throws Exception {
        int[] parameters={GLES30.GL_READ_FRAMEBUFFER_BINDING,GLES30.GL_DRAW_FRAMEBUFFER_BINDING,
            GLES30.GL_TEXTURE_BINDING_2D,GLES30.GL_PIXEL_PACK_BUFFER_BINDING,GLES30.GL_PACK_ALIGNMENT,
            GLES30.GL_PACK_ROW_LENGTH,GLES30.GL_PACK_SKIP_PIXELS,GLES30.GL_PACK_SKIP_ROWS};
        int[] old=new int[parameters.length],fbos=new int[2],scratch={0};
        for(int i=0;i<parameters.length;i++)GLES30.glGetIntegerv(parameters[i],old,i);
        require(old[0]==outputFbo&&old[1]==outputFbo&&!GLES30.glIsEnabled(GLES30.GL_SCISSOR_TEST)&&
            GLES30.glGetError()==GLES30.GL_NO_ERROR,"Invalid shader reference boundary");
        int[] format={0};
        int error;
        long different=0,firstDifference=-1,pixels=0,asymmetric=0;
        try {
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,source);
            GLES31.glGetTexLevelParameteriv(GLES30.GL_TEXTURE_2D,0,GLES31.GL_TEXTURE_INTERNAL_FORMAT,format,0);
            require(GLES30.glGetError()==GLES30.GL_NO_ERROR&&format[0]==GL_BGRA8_EXT,
                "Expected actual BGRA8 game import, got 0x"+Integer.toHexString(format[0]));
            GLES30.glGenTextures(1,scratch,0);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,scratch[0]);
            GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,width,height,0,
                GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,null);
            GLES30.glGenFramebuffers(2,fbos,0);
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbos[0]);
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,source,0);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,fbos[1]);
            GLES30.glFramebufferTexture2D(GLES30.GL_DRAW_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,
                GLES30.GL_TEXTURE_2D,scratch[0],0);
            require(GLES30.glCheckFramebufferStatus(GLES30.GL_READ_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE&&
                GLES30.glCheckFramebufferStatus(GLES30.GL_DRAW_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE&&
                GLES30.glGetError()==GLES30.GL_NO_ERROR,"Cannot bind the exact import and scratch target");
            AsyncStereoTransfer.blitFlippedRows(width,height);
            error=GLES30.glGetError();
            if(error==GLES30.GL_NO_ERROR) {
                GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,0);
                for(int i=4;i<parameters.length;i++)GLES30.glPixelStorei(parameters[i],i==4 ? 4 : 0);
                int rows=128;
                ByteBuffer shader=ByteBuffer.allocateDirect(width*rows*4).order(ByteOrder.LITTLE_ENDIAN);
                ByteBuffer blit=ByteBuffer.allocateDirect(width*rows*4).order(ByteOrder.LITTLE_ENDIAN);
                for(int y=0;y<height;y+=rows) {
                    int count=Math.min(rows,height-y);
                    GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,outputFbo);
                    GLES30.glReadPixels(0,y,width,count,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,shader);
                    GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbos[1]);
                    GLES30.glReadPixels(0,y,width,count,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,blit);
                    require(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Blit comparison readback failed");
                    for(int i=0;i<width*count;i++) {
                        int expected=shader.getInt(i*4);
                        if((expected&255)!=((expected>>>16)&255))asymmetric++;
                        if(expected!=blit.getInt(i*4)) {
                            if(different==0)firstDifference=pixels+i;
                            different++;
                        }
                    }
                    pixels+=(long)width*count;
                }
            }
        } finally {
            GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,old[0]);
            GLES30.glBindFramebuffer(GLES30.GL_DRAW_FRAMEBUFFER,old[1]);
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,old[2]);
            GLES30.glBindBuffer(GLES30.GL_PIXEL_PACK_BUFFER,old[3]);
            for(int i=4;i<parameters.length;i++)GLES30.glPixelStorei(parameters[i],old[i]);
            GLES30.glDeleteFramebuffers(2,fbos,0);
            GLES30.glDeleteTextures(1,scratch,0);
        }
        return new JSONObject().put("source_format",format[0]).put("width",width).put("height",height)
            .put("gl_error",error).put("pixels_compared",pixels).put("different_pixels",different)
            .put("first_different_pixel",firstDifference).put("red_blue_asymmetric_pixels",asymmetric);
    }
}
