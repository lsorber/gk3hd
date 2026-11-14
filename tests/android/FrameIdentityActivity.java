package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;

/** Bounded real-GPU source transfer test. No Wine, game data or fabricated tracking. */
public final class FrameIdentityActivity extends Activity {
    private String token;
    private String mode;
    private volatile boolean complete;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh test token required");
        mode=getIntent().getStringExtra("mode");if(mode==null)mode="identity";
        if(!mode.equals("identity")&&!mode.equals("transport")&&!mode.equals("driver")&&!mode.equals("audio")&&!mode.equals("allocation"))throw new IllegalArgumentException("Unknown native fixture mode");
        android.widget.TextView view=new android.widget.TextView(this);
        view.setText("Checking GK3HD native components");setContentView(view);
        new Thread(this::run,"GK3HDIdentityGPU").start();
        new android.os.Handler(getMainLooper()).postDelayed(()-> {if(!complete)finish();},15_000);
    }
    private void run() {
        org.json.JSONObject result=new org.json.JSONObject();
        EGLDisplay display=mode.equals("driver")||mode.equals("audio")||mode.equals("allocation") ? EGL14.EGL_NO_DISPLAY : EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLSurface surface=EGL14.EGL_NO_SURFACE;EGLContext context=EGL14.EGL_NO_CONTEXT;
        try {
            if(mode.equals("driver")) {
                result=NativeDriverProbe.run(this,token);
            } else if(mode.equals("audio")) {
                AudioWriteCancellationTests.run();result.put("token",token).put("mode",mode).put("passed",true);
            } else if(mode.equals("allocation")) {
                GpuAllocationCompatTests.run(this);result.put("token",token).put("mode",mode).put("passed",true)
                    .put("legacy_allocation_policy",GpuAllocationCompat.legacyAllocationPolicy());
            } else {
                if(!EGL14.eglInitialize(display,new int[2],0,new int[2],1))throw new IllegalStateException("Cannot initialize EGL");
                EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
                if(!EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,0x40,
                    EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,
                    EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE},0,configs,0,1,count,0)||count[0]!=1)
                    throw new IllegalStateException("Cannot choose offscreen ES3 config");
                surface=EGL14.eglCreatePbufferSurface(display,configs[0],new int[]{EGL14.EGL_WIDTH,16,EGL14.EGL_HEIGHT,16,EGL14.EGL_NONE},0);
                context=EGL14.eglCreateContext(display,configs[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
                if(surface==EGL14.EGL_NO_SURFACE||context==EGL14.EGL_NO_CONTEXT||!EGL14.eglMakeCurrent(display,surface,surface,context))
                    throw new IllegalStateException("Cannot activate offscreen ES3 context");
                result.put("token",token);result.put("mode",mode);
                if(mode.equals("transport"))StereoTransferTests.run();
                else {
                    result.put("checks",FrameIdentityGpuTests.run());
                    result.put("copy_checked_bytes",StereoCopyTests.run());
                    result.put("color_checks",StereoColorTests.run());
                }
                result.put("passed",true);
            }
        } catch(Exception|AssertionError failure) {
            try {result.put("token",token);result.put("passed",false);result.put("error",failure.toString());}
            catch(org.json.JSONException impossible) {throw new IllegalStateException(impossible);}
        } finally {
            if(display!=EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
                if(context!=EGL14.EGL_NO_CONTEXT)EGL14.eglDestroyContext(display,context);
                if(surface!=EGL14.EGL_NO_SURFACE)EGL14.eglDestroySurface(display,surface);
                EGL14.eglTerminate(display);
            }
        }
        try {
            File output=new File(getFilesDir(),"frame-identity-"+token+".json");
            if(output.exists())throw new IllegalStateException("Preserve earlier test evidence");
            FixtureReport.write(output,result.toString());
        } catch(Exception failure) {android.util.Log.e("GK3HDIdentityTest","Cannot preserve test result",failure);}
        complete=true;runOnUiThread(this::finish);
    }
}
