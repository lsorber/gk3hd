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
import org.json.JSONObject;

/** Finite offscreen GPU ownership fixture. Opens no game or XR session. */
public final class WithdrawnPresentGpuActivity extends Activity {
    private String token;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh probe token required");
        new Thread(this::runGpu,"GK3HDWithdrawnGpu").start();
    }
    private void runGpu() {
        EGLDisplay display=EGL14.EGL_NO_DISPLAY;EGLContext context=EGL14.EGL_NO_CONTEXT;EGLSurface surface=EGL14.EGL_NO_SURFACE;
        JSONObject result=new JSONObject();boolean retired=true;
        try {
            display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
            if(!EGL14.eglInitialize(display,new int[2],0,new int[2],1))throw new IllegalStateException("GPU display unavailable");
            EGLConfig[] config=new EGLConfig[1];int[] count=new int[1];
            int[] attributes={EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_RENDERABLE_TYPE,0x40,
                EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE};
            if(!EGL14.eglChooseConfig(display,attributes,0,config,0,1,count,0)||count[0]!=1)throw new IllegalStateException("No GLES3 configuration");
            context=EGL14.eglCreateContext(display,config[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
            surface=EGL14.eglCreatePbufferSurface(display,config[0],new int[]{EGL14.EGL_WIDTH,128,EGL14.EGL_HEIGHT,16,EGL14.EGL_NONE},0);
            if(context==EGL14.EGL_NO_CONTEXT||surface==EGL14.EGL_NO_SURFACE||!EGL14.eglMakeCurrent(display,surface,surface,context))
                throw new IllegalStateException("Cannot own offscreen GLES context");
            WithdrawnPresentGpuTests.run();result.put("passed",true);
        } catch(Exception|AssertionError failure) {
            try{result.put("passed",false).put("failure",failure.toString());}catch(Exception ignored){}
        } finally {
            if(display!=EGL14.EGL_NO_DISPLAY) {
                retired=EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
                if(surface!=EGL14.EGL_NO_SURFACE)retired=EGL14.eglDestroySurface(display,surface)&&retired;
                if(context!=EGL14.EGL_NO_CONTEXT)retired=EGL14.eglDestroyContext(display,context)&&retired;
            }
            try {
                result.put("token",token).put("egl_retired",retired).put("scope","Actual offscreen GPU ownership/pixels and source withdrawal/recovery. No game, XR, physical tracking or performance acceptance.");
                File out=new File(getFilesDir(),"withdrawn-gpu-"+token+".json");
                if(!out.createNewFile())throw new IllegalStateException("Preserve probe evidence");
                java.nio.file.Files.write(out.toPath(),result.toString().getBytes(StandardCharsets.UTF_8));
            } catch(Exception failure){android.util.Log.e("GK3HDWithdrawnGpu","Export failed",failure);}
            runOnUiThread(this::finish);
        }
    }
}
