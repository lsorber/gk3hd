package org.gk3hd.standalone;

import android.content.Context;
import android.opengl.GLES30;
import android.util.Log;
import java.nio.ByteBuffer;
import java.util.HashSet;

/** Opt-in real Windows-Vulkan -> X-server -> Android-GLES pixel fixture. */
public final class StereoSourceTests {
    private static final HashSet<Integer> ids=new HashSet<>();
    private static final int[] phaseFrames=new int[4],phaseBlue={99,137,188,225};
    private static int lastPhase=-1;
    private static boolean passed;
    public static void diagnose(int texture,int width,int height) {
        int[] previous=new int[1],fbo=new int[1];GLES30.glGetIntegerv(GLES30.GL_READ_FRAMEBUFFER_BINDING,previous,0);
        GLES30.glGenFramebuffers(1,fbo,0);GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,fbo[0]);
        try {
            GLES30.glFramebufferTexture2D(GLES30.GL_READ_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture,0);
            StringBuilder text=new StringBuilder("Stereo pixel diagnostic");
            for(int row:new int[]{0,height-1}) {
                ByteBuffer bytes=ByteBuffer.allocateDirect(FramePoses.PIXELS*4);
                GLES30.glReadPixels(0,row,FramePoses.PIXELS,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,bytes);
                text.append(" row=").append(row).append(" id=").append(FramePoses.decode(bytes)).append(" rgba=");
                for(int i=0;i<6;i++) {for(int c=0;c<4;c++) text.append(bytes.get(i*4+c)&255).append(',');text.append('/');}
            }
            ByteBuffer center=ByteBuffer.allocateDirect(4);
            GLES30.glReadPixels(width/4,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,center);
            text.append(" center=");for(int c=0;c<4;c++) text.append(center.get(c)&255).append(',');
            text.append(" error=").append(GLES30.glGetError());Log.i("GK3HDXR",text.toString());
        } finally {GLES30.glBindFramebuffer(GLES30.GL_READ_FRAMEBUFFER,previous[0]);GLES30.glDeleteFramebuffers(1,fbo,0);}
    }
    public static void verify(Context context,int id,int width,int height) throws Exception {
        boolean lifecycle=((android.app.Activity)context).getIntent().getIntExtra("gk3hd_test_transport_cycles",1)==4;
        if(ids.size()>=(lifecycle ? 256 : 20)||ids.contains(id)) return;
        int phase=0;
        if(lifecycle) {
            ByteBuffer center=ByteBuffer.allocateDirect(4);
            GLES30.glReadPixels(width/2,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,center);
            phase=-1;
            for(int candidate=0;candidate<phaseBlue.length;candidate++)
                if(Math.abs(phaseBlue[candidate]-(center.get(2)&255))<=2) phase=candidate;
            if(phase<0||phase<lastPhase) throw new IllegalStateException("Unknown or regressing stereo lifecycle phase");
        }
        for(int eye=0;eye<2;eye++) for(int point=0;point<3;point++) {
            int x=eye*width+width/(point==0 ? 2 : 8),y=point==0 ? height/2 : (point==1 ? height/8 : height*7/8);
            ByteBuffer pixel=ByteBuffer.allocateDirect(4);
            GLES30.glReadPixels(x,y,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
            for(int channel=0;channel<3;channel++) {
                int expected=channel==(point==0 ? 2 : eye) ? (point==0&&lifecycle ? phaseBlue[phase] : 137) : 0,actual=pixel.get(channel)&255;
                if(Math.abs(expected-actual)>2) throw new IllegalStateException("Stereo source pixel mismatch: eye="+eye+
                    " point="+point+" channel="+channel+" expected="+expected+" actual="+actual);
            }
        }
        if(GLES30.glGetError()!=GLES30.GL_NO_ERROR) throw new IllegalStateException("Stereo source GL error");
        ids.add(id);
        phaseFrames[phase]++;lastPhase=phase;
        boolean complete=ids.size()>=20;
        if(lifecycle) for(int count:phaseFrames) complete&=count>=3;
        if(complete&&!passed) {
            passed=true;
            try(java.io.PrintWriter out=new java.io.PrintWriter(new java.io.File(context.getFilesDir(),"stereo-source-fixture.json"))) {
                org.json.JSONObject result=new org.json.JSONObject().put("distinct_frames_verified",ids.size())
                    .put("token",((android.app.Activity)context).getIntent().getStringExtra("gk3hd_fixture_token"))
                    .put("cycles",lifecycle ? 4 : 1).put("phase_frames",new org.json.JSONArray(phaseFrames))
                    .put("scope","synthetic projection+quad transport, not gameplay or head tracking");
                out.println(result);
            }
            Log.i("GK3HDXR","Stereo source fixture passed: "+ids.size()+" distinct Windows-Vulkan frames, "+
                (lifecycle ? "all four lifecycle phases, " : "")+"both eyes, sRGB and quad overlay");
        }
    }
}
