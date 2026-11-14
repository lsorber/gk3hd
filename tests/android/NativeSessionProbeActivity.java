package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.GLES30;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded actual OpenXR presentation, with a procedural source and real poses. */
public final class NativeSessionProbeActivity extends Activity {
    private NativeSurfaceView view;
    private OpenXrPresenter presenter;
    private final Pattern source=new Pattern();
    private String token;
    private String failure;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh probe token required");
        getIntent().putExtra("gk3hd_xr_presenter","openxr");
        getIntent().putExtra("gk3hd_test_presenter_timing",true);
        getIntent().putExtra("gk3hd_observation_token",token);
        new android.os.Handler(getMainLooper()).postDelayed(this::finish,8000L);
        try {
            view=new NativeSurfaceView(this) {
                @Override protected void onRenderFailure(Throwable error) {
                    failure=error.toString();
                    if(presenter!=null)presenter.destroy();
                    runOnUiThread(NativeSessionProbeActivity.this::finish);
                }
            };
            presenter=new OpenXrPresenter(this,view,source);
            view.setRenderer(presenter);setContentView(view);
        } catch(Exception|LinkageError error) {
            failure=error.toString();finish();
        }
    }
    @Override protected void onResume() {
        super.onResume();
        if(presenter!=null)presenter.resume();
        if(view!=null)view.onResume();
    }
    @Override protected void onPause() {
        if(presenter!=null)presenter.pause();
        if(view!=null)view.onPause();
        super.onPause();
    }
    @Override protected void onDestroy() {
        if(presenter!=null)presenter.destroy();
        if(view!=null)view.close();
        try {
            JSONObject data=new JSONObject().put("token",token)
                .put("scope","Actual native presenter with a procedural stereo pattern and runtime poses. No game, simulated input, physical scanout or motion-to-photon acceptance.")
                .put("eye_width",source.width).put("eye_height",source.height)
                .put("tracking_samples",source.samples).put("draws",source.draws)
                .put("valid_location_samples",source.validSamples)
                .put("left_aim_valid_samples",source.leftValid)
                .put("right_aim_valid_samples",source.rightValid)
                .put("last_hz",source.hz).put("source_closed",source.closed)
                .put("source_pixels",new JSONArray(source.pixels))
                .put("failure",failure==null?JSONObject.NULL:failure);
            File output=new File(getFilesDir(),"native-session-"+token+".json");
            if(!output.createNewFile())throw new IllegalStateException("Preserve earlier session evidence");
            try(FileOutputStream out=new FileOutputStream(output)) {
                out.write(data.toString().getBytes(StandardCharsets.UTF_8));
            }
        } catch(Exception error) {android.util.Log.e("GK3HDSessionProbe","Export failed",error);}
        super.onDestroy();
    }

    private static final class Pattern implements XrPresenter.Source {
        int width,height,samples,validSamples,leftValid,rightValid,draws;
        float hz;
        boolean located,closed;
        Integer inputId,renderedId;
        int[] pixels=new int[0];
        @Override public void configure(int w,int h) {width=w;height=h;}
        @Override public void linearOutput(boolean value) {
            if(!value)throw new IllegalArgumentException("This fixture expects the native linear compositor target");
        }
        @Override public void onSurfaceCreated(GL10 gl,EGLConfig config) {}
        @Override public void onSurfaceChanged(GL10 gl,int w,int h) {}
        @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,
                float rate,int id,XrInput inputs,StereoViews views) {
            samples++;inputId=id;hz=rate;located=(flags&3)==3&&views!=null;
            if(located)validSamples++;
            if((inputs.left.flags&3)==3)leftValid++;
            if((inputs.right.flags&3)==3)rightValid++;
        }
        @Override public void tracking(float[] head,int flags,float ipd,float fovX,float fovY,
                float rate,int id,XrInput inputs) {
            tracking(head,flags,ipd,fovX,fovY,rate,id,inputs,null);
        }
        @Override public boolean hasStereoFrame() {return located;}
        @Override public Integer renderedFrameId() {return renderedId;}
        @Override public void onDrawFrame(GL10 gl) {
            GLES30.glViewport(0,0,width*2,height);
            GLES30.glDisable(GLES30.GL_DEPTH_TEST);GLES30.glDisable(GLES30.GL_BLEND);
            GLES30.glEnable(GLES30.GL_SCISSOR_TEST);
            GLES30.glScissor(0,0,width,height);GLES30.glClearColor(1,0,0,1);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glScissor(width,0,width,height);GLES30.glClearColor(0,1,0,1);
            GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glDisable(GLES30.GL_SCISSOR_TEST);
            if(draws==0) {
                ByteBuffer left=ByteBuffer.allocateDirect(4),right=ByteBuffer.allocateDirect(4);
                GLES30.glReadPixels(width/2,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,left);
                GLES30.glReadPixels(width+width/2,height/2,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,right);
                pixels=new int[8];
                for(int i=0;i<4;i++){pixels[i]=left.get(i)&255;pixels[i+4]=right.get(i)&255;}
            }
            int error=GLES30.glGetError();
            if(error!=GLES30.GL_NO_ERROR)throw new IllegalStateException("Pattern GL error "+error);
            renderedId=inputId;draws++;
        }
        @Override public void close() {closed=true;}
    }
}
