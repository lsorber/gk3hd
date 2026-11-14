package com.winlator;

import android.app.Activity;
import android.opengl.GLES30;
import android.os.Bundle;
import android.util.Log;
import android.widget.FrameLayout;
import com.winlator.core.GPUHelper;
import java.nio.ByteBuffer;
import org.gk3hd.standalone.NativeSurfaceView;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** Actual surface destruction/recreation, independent shared reader, four bytes.
 * No game, synthetic tracking, vendor compositor or host GPU is involved. */
public final class SurfaceLifecycleActivity extends Activity {
    private NativeSurfaceView view;
    private FrameLayout parent;
    private int texture,created,resized;
    private volatile boolean readerPassed,done;
    private static void check(boolean value,String reason) {if(!value) throw new AssertionError(reason);}
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);parent=new FrameLayout(this);setContentView(parent);
        view=new NativeSurfaceView(this);
        view.setRenderer(new android.opengl.GLSurfaceView.Renderer() {
            public void onSurfaceCreated(GL10 gl,EGLConfig config) {
                try {
                    check(++created==1,"Root context was recreated");GPUHelper.setGlobalEGLContext();
                    int[] ids=new int[1];GLES30.glGenTextures(1,ids,0);texture=ids[0];
                    GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
                    ByteBuffer pixel=ByteBuffer.allocateDirect(4);pixel.put(new byte[]{37,89,(byte)173,(byte)255}).flip();
                    GLES30.glTexImage2D(GLES30.GL_TEXTURE_2D,0,GLES30.GL_RGBA8,1,1,0,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
                    GLES30.glFinish();verify();
                } catch(Throwable error) {fail(error);}
            }
            public void onSurfaceChanged(GL10 gl,int width,int height) {
                if(done) return;
                try {
                    if(++resized<=3) runOnUiThread(()-> {
                        view.onPause();
                        parent.removeView(view);
                        new Thread(()-> {
                            long shared=0;
                            try {
                                shared=GPUHelper.createOffscreenEGLContext(true);
                                check(shared!=0&&GLES30.glGetString(GLES30.GL_VENDOR)!=null,"Shared context unavailable after surface loss");
                                verify();readerPassed=true;
                            } catch(Throwable error) {fail(error);}
                            finally {if(shared!=0) GPUHelper.destroyOffscreenEGLContext(shared);}
                            if(!done) runOnUiThread(()-> {view.onResume();parent.addView(view);});
                        },"GK3HDSharedReader").start();
                    });
                    else {
                        check(readerPassed&&created==1,"Resume lost the shared group");verify();done=true;
                        Log.i("GK3HDXR","Surface lifecycle fixture passed: three pause/loss/resume cycles preserve shared pixels; root_contexts="+created);
                        runOnUiThread(SurfaceLifecycleActivity.this::finish);
                    }
                } catch(Throwable error) {fail(error);}
            }
            public void onDrawFrame(GL10 gl) {GLES30.glClearColor(0,0,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);}
        });
        parent.addView(view);
        new android.os.Handler(getMainLooper()).postDelayed(()->{if(!done) fail(new IllegalStateException("Surface lifecycle timed out"));},10000);
    }
    private void verify() {
        check(GLES30.glIsTexture(texture),"Shared texture was lost");int[] fbo=new int[1];
        GLES30.glGenFramebuffers(1,fbo,0);GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,fbo[0]);
        try {
            GLES30.glFramebufferTexture2D(GLES30.GL_FRAMEBUFFER,GLES30.GL_COLOR_ATTACHMENT0,GLES30.GL_TEXTURE_2D,texture,0);
            check(GLES30.glCheckFramebufferStatus(GLES30.GL_FRAMEBUFFER)==GLES30.GL_FRAMEBUFFER_COMPLETE,"Shared texture incomplete");
            ByteBuffer pixel=ByteBuffer.allocateDirect(4);GLES30.glReadPixels(0,0,1,1,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,pixel);
            check((pixel.get(0)&255)==37&&(pixel.get(1)&255)==89&&(pixel.get(2)&255)==173&&(pixel.get(3)&255)==255,"Shared pixels changed");
            check(GLES30.glGetError()==GLES30.GL_NO_ERROR,"Shared context GL error");
        } finally {GLES30.glBindFramebuffer(GLES30.GL_FRAMEBUFFER,0);GLES30.glDeleteFramebuffers(1,fbo,0);}
    }
    private void fail(Throwable error) {done=true;Log.e("GK3HDXR","Surface lifecycle fixture failed",error);runOnUiThread(this::finish);}
    @Override protected void onDestroy() {if(view!=null) view.close();super.onDestroy();}
}
