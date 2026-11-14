package org.gk3hd.standalone;

import android.app.Activity;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES30;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Local synthetic identities with actual GPU pixels. Never opens an XR runtime. */
public final class RetainedImageGpuActivity extends Activity {
    private final RetainedStereoPattern source=new RetainedStereoPattern();
    private final FramePoses<String> poses=new FramePoses<>();
    private String token;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh GPU probe token required");
        setContentView(new android.view.View(this));new Thread(this::offscreen,"GK3HDRetainedGpu").start();
    }
    private void offscreen(){
        EGLDisplay display=EGL14.EGL_NO_DISPLAY;EGLContext context=EGL14.EGL_NO_CONTEXT;EGLSurface surface=EGL14.EGL_NO_SURFACE;
        JSONObject result=new JSONObject();boolean retired=true;
        try{
            display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
            if(display==EGL14.EGL_NO_DISPLAY||!EGL14.eglInitialize(display,new int[2],0,new int[2],1))throw new IllegalStateException("GPU display unavailable");
            EGLConfig[] config=new EGLConfig[1];int[] count=new int[1];
            int[] attributes={EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_RENDERABLE_TYPE,0x40,
                EGL14.EGL_RED_SIZE,8,EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE};
            if(!EGL14.eglChooseConfig(display,attributes,0,config,0,1,count,0)||count[0]!=1)throw new IllegalStateException("No GLES3 pixel-buffer configuration");
            context=EGL14.eglCreateContext(display,config[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,3,EGL14.EGL_NONE},0);
            surface=EGL14.eglCreatePbufferSurface(display,config[0],new int[]{EGL14.EGL_WIDTH,128,EGL14.EGL_HEIGHT,48,EGL14.EGL_NONE},0);
            if(context==EGL14.EGL_NO_CONTEXT||surface==EGL14.EGL_NO_SURFACE||!EGL14.eglMakeCurrent(display,surface,surface,context))throw new IllegalStateException("Cannot own offscreen GLES context");
            source.configure(64,48);source.onSurfaceCreated(null,null);render(result);GLES30.glFinish();
        }catch(Exception|AssertionError failure){try{result.put("passed",false).put("failure",failure.toString());}catch(Exception ignored){}}
        finally{
            if(display!=EGL14.EGL_NO_DISPLAY){
                retired=EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
                if(surface!=EGL14.EGL_NO_SURFACE)retired=EGL14.eglDestroySurface(display,surface)&&retired;
                if(context!=EGL14.EGL_NO_CONTEXT)retired=EGL14.eglDestroyContext(display,context)&&retired;
                retired=EGL14.eglTerminate(display)&&retired;
            }
            try{result.put("token",token).put("egl_retired",retired).put("scope","Real offscreen GLES pixels/immutable identity and synthetic local pose history. No native XR, physical tracking injection, performance or MTP claim.");
                File out=new File(getFilesDir(),"retained-gpu-"+token+".json");if(!out.createNewFile())throw new IllegalStateException("Preserve GPU evidence");
                java.nio.file.Files.write(out.toPath(),result.toString().getBytes(StandardCharsets.UTF_8));
            }catch(Exception failure){android.util.Log.e("GK3HDRetainedGpu","Export failed",failure);}
            runOnUiThread(this::finish);
        }
    }
    private void render(JSONObject result){
        int[] texture=new int[3],target=new int[3];
        try{
            poses.focused(true);GLES30.glGenTextures(3,texture,0);GLES30.glGenFramebuffers(3,target,0);
            for(int i=0;i<3;i++){
                GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture[i]);GLES30.glTexStorage2D(GLES30.GL_TEXTURE_2D,1,GLES30.GL_RGBA8,128,48);
                GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,target[i]);
                GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture[i],0);
            }
            long base=1_000_000_000L;int held=0,withdrawn=0,recovered=0;String last=null;long previousSnapshot=0;
            for(int tick=0;tick<360;tick++){
                long now=base+tick*4_000_000L;int id=0x12340000+tick;
                poses.remember(id,"pose-"+id,3,now);source.inputId=id;source.located=true;
                GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,target[tick%3]);source.drawAt(now);
                String matched=poses.matchImage(source.renderedFrameId(),source.renderedSnapshot(),now);
                if(matched==null)throw new IllegalStateException("Known GPU image lost its original pose");
                if(source.renderedSnapshot()==previousSnapshot){held++;if(!matched.equals(last))throw new IllegalStateException("Held image relabelled");}
                if(now-source.lastUpdate>250_000_000L){withdrawn++;if(poses.inputsCurrent(now))throw new IllegalStateException("Stale image accepted game input");}
                if(now-base>=850_000_000L){recovered++;if(!poses.inputsCurrent(now))throw new IllegalStateException("Fresh GPU image did not recover inputs");}
                last=matched;previousSnapshot=source.renderedSnapshot();
            }
            if(held<100||withdrawn<50||recovered<100)throw new IllegalStateException("GPU pause/recovery coverage incomplete");
            result.put("passed",true).put("gpu_images_checked",source.draws).put("held_copies",held).put("stale_input_withdrawals",withdrawn).put("fresh_recovery_copies",recovered);
        }catch(Exception|AssertionError failure){try{result.put("passed",false).put("failure",failure.toString());}catch(Exception ignored){}}
        finally{
            source.close();GLES30.glDeleteTextures(3,texture,0);GLES30.glDeleteFramebuffers(3,target,0);
        }
    }
}
