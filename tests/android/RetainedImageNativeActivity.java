package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Bounded real-runtime presentation of an owned GPU image across a source pause. */
public final class RetainedImageNativeActivity extends Activity {
    private final RetainedStereoPattern source=new RetainedStereoPattern();
    private NativeSurfaceView view;
    private XrPresenter presenter;
    private String token,backend,failure;
    private int starts,resumes,pauses,stops,focusChanges,surfaces,renderCallbacks;
    private void lifecycle(String event){android.util.Log.i("GK3HDRetainedNative",event);}
    @Override public void onCreate(Bundle state){
        super.onCreate(state);token=getIntent().getStringExtra("token");backend=getIntent().getStringExtra("backend");
        if(token==null||!token.matches("[a-f0-9]{32}")||!("pimax".equals(backend)||"openxr".equals(backend)))
            throw new IllegalArgumentException("Fresh native probe identity required");
        getIntent().putExtra("gk3hd_xr_presenter",backend).putExtra("gk3hd_test_presenter_timing",true).putExtra("gk3hd_observation_token",token);
        new android.os.Handler(getMainLooper()).postDelayed(this::finish,12000);
        try{
            view=new NativeSurfaceView(this){
                @Override protected void onRenderFailure(Throwable error){failure=error.toString();runOnUiThread(RetainedImageNativeActivity.this::finish);}
                @Override public void surfaceCreated(android.view.SurfaceHolder holder){surfaces++;lifecycle("surfaceCreated");super.surfaceCreated(holder);}
            };
            presenter="pimax".equals(backend)?new PimaxPresenter(this,view,source):new OpenXrPresenter(this,view,source);
            view.setRenderer(new android.opengl.GLSurfaceView.Renderer(){
                @Override public void onSurfaceCreated(javax.microedition.khronos.opengles.GL10 gl,javax.microedition.khronos.egl.EGLConfig config){lifecycle("graphicsCreated");presenter.onSurfaceCreated(gl,config);}
                @Override public void onSurfaceChanged(javax.microedition.khronos.opengles.GL10 gl,int width,int height){presenter.onSurfaceChanged(gl,width,height);}
                @Override public void onDrawFrame(javax.microedition.khronos.opengles.GL10 gl){renderCallbacks++;presenter.onDrawFrame(gl);}
            });setContentView(view);lifecycle("created");
        }catch(Exception|LinkageError error){failure=error.toString();finish();}
    }
    private void resumeGraphics(){presenter.resume();presenter.inputFocused(hasWindowFocus());view.onResume();}
    private void pauseGraphics(){presenter.pause();view.onPause();}
    @Override public void onWindowFocusChanged(boolean focused){super.onWindowFocusChanged(focused);focusChanges++;lifecycle("focus="+focused);if(presenter!=null)presenter.inputFocused(focused);}
    @Override protected void onStart(){super.onStart();starts++;lifecycle("start");if(presenter!=null&&presenter.rendersWhileVisible())resumeGraphics();}
    @Override protected void onResume(){
        super.onResume();resumes++;lifecycle("resume");if(presenter!=null&&!presenter.rendersWhileVisible())resumeGraphics();
    }
    @Override protected void onPause(){pauses++;lifecycle("pause");if(presenter!=null&&!presenter.rendersWhileVisible())pauseGraphics();super.onPause();}
    @Override protected void onStop(){stops++;lifecycle("stop");if(presenter!=null&&presenter.rendersWhileVisible())pauseGraphics();super.onStop();}
    @Override protected void onDestroy(){
        if(presenter!=null)presenter.destroy();if(view!=null)view.close();
        try{
            JSONObject result=new JSONObject().put("token",token).put("backend",backend)
                .put("scope","Actual native runtime, real tracking and owned procedural GPU pixels. No game, synthetic tracking injection, physical scanout or MTP acceptance.")
                .put("tracking_samples",source.trackingSamples).put("valid_samples",source.validSamples)
                .put("draws",source.draws).put("source_updates",source.updates).put("held_draws",source.heldDraws)
                .put("recovered_draws",source.recoveredDraws).put("source_closed",source.closed)
                .put("starts",starts).put("resumes",resumes).put("pauses",pauses).put("stops",stops)
                .put("focus_changes",focusChanges).put("surfaces",surfaces).put("render_callbacks",renderCallbacks)
                .put("failure",failure==null?JSONObject.NULL:failure);
            File out=new File(getFilesDir(),"retained-native-"+token+".json");if(!out.createNewFile())throw new IllegalStateException("Preserve native evidence");
            java.nio.file.Files.write(out.toPath(),result.toString().getBytes(StandardCharsets.UTF_8));
        }catch(Exception error){android.util.Log.e("GK3HDRetainedNative","Export failed",error);}
        super.onDestroy();
    }
}
