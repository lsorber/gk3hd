package org.gk3hd.standalone;

import android.graphics.SurfaceTexture;
import android.opengl.EGL14;
import android.opengl.EGLContext;
import android.opengl.GLES11Ext;
import android.opengl.GLES30;
import android.os.Handler;
import android.view.Surface;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.concurrent.atomic.AtomicInteger;

/** Decoder Surface to calibrated stereo cinema. All methods belong to its EGL thread. */
public final class NativeMovieLayer implements AutoCloseable {
    private final EGLContext context=EGL14.eglGetCurrentContext();
    private final AtomicInteger arrivals=new AtomicInteger();
    private final float[] transform=new float[16],vertices=new float[16];
    private final FloatBuffer upload=ByteBuffer.allocateDirect(64).order(ByteOrder.nativeOrder()).asFloatBuffer();
    private SurfaceTexture texture;
    private Surface surface;
    private int image,program,vao,buffer,seen;
    private boolean available;
    private long timestamp;
    private static final int[] ENABLES={GLES30.GL_BLEND,GLES30.GL_CULL_FACE,GLES30.GL_DEPTH_TEST,
        GLES30.GL_STENCIL_TEST,GLES30.GL_SCISSOR_TEST,GLES30.GL_RASTERIZER_DISCARD,GLES30.GL_DITHER,
        GLES30.GL_SAMPLE_ALPHA_TO_COVERAGE,GLES30.GL_SAMPLE_COVERAGE};
    public NativeMovieLayer(Handler callbackHandler) {
        requireContext();
        int[] old=new int[3],name=new int[1];
        GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,old,0);GLES30.glActiveTexture(GLES30.GL_TEXTURE0);
        GLES30.glGetIntegerv(GLES11Ext.GL_TEXTURE_BINDING_EXTERNAL_OES,old,1);
        try {
            GLES30.glGenTextures(1,name,0);image=name[0];GLES30.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,image);
            GLES30.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES30.GL_TEXTURE_MIN_FILTER,GLES30.GL_LINEAR);
            GLES30.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES30.GL_TEXTURE_MAG_FILTER,GLES30.GL_LINEAR);
            GLES30.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES30.GL_TEXTURE_WRAP_S,GLES30.GL_CLAMP_TO_EDGE);
            GLES30.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,GLES30.GL_TEXTURE_WRAP_T,GLES30.GL_CLAMP_TO_EDGE);
            texture=new SurfaceTexture(image);texture.setOnFrameAvailableListener(t->arrivals.incrementAndGet(),callbackHandler);
            surface=new Surface(texture);
            int vertex=shader(GLES30.GL_VERTEX_SHADER,"#version 300 es\nlayout(location=0) in vec4 point;uniform mat4 transform;out vec2 uv;void main(){gl_Position=point;vec2 p=vec2(gl_VertexID&1,gl_VertexID>>1);uv=(transform*vec4(p,0,1)).xy;}");
            int fragment;
            try {fragment=shader(GLES30.GL_FRAGMENT_SHADER,"#version 300 es\n#extension GL_OES_EGL_image_external_essl3 : require\nprecision highp float;uniform samplerExternalOES image;uniform bool linearOutput;in vec2 uv;out vec4 color;void main(){color=texture(image,uv);color.a=1.;if(linearOutput)color.rgb=mix(pow((color.rgb+0.055)/1.055,vec3(2.4)),color.rgb/12.92,lessThanEqual(color.rgb,vec3(0.04045)));}");}
            catch(RuntimeException error){GLES30.glDeleteShader(vertex);throw error;}
            program=GLES30.glCreateProgram();GLES30.glAttachShader(program,vertex);GLES30.glAttachShader(program,fragment);GLES30.glLinkProgram(program);GLES30.glDeleteShader(vertex);GLES30.glDeleteShader(fragment);
            int[] ok={0};GLES30.glGetProgramiv(program,GLES30.GL_LINK_STATUS,ok,0);
            if(ok[0]==0)throw new IllegalStateException("Movie shader link: "+GLES30.glGetProgramInfoLog(program));
            GLES30.glGenVertexArrays(1,name,0);vao=name[0];GLES30.glGenBuffers(1,name,0);buffer=name[0];
        }catch(RuntimeException error){close();throw error;}
        finally {GLES30.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,old[1]);GLES30.glActiveTexture(old[0]);}
    }
    public Surface surface() {requireContext();if(surface==null)throw new IllegalStateException("Movie layer closed");return surface;}
    public long timestamp() {return timestamp;}
    /** Latch once per fresh decoder notification. Keep the last picture across pause. */
    public boolean latch() {
        requireContext();if(texture==null)throw new IllegalStateException("Movie layer closed");
        int count=arrivals.get();if(count!=seen){seen=count;texture.updateTexImage();texture.getTransformMatrix(transform);timestamp=texture.getTimestamp();available=true;}
        return available;
    }
    /** Returns true once a decoded picture supplies both eye images. */
    public boolean draw(MovieCanvas canvas,float[] head,StereoViews views,int eyeWidth,int eyeHeight,boolean linearOutput) {
        requireContext();
        if(canvas==null||views==null||eyeWidth<1||eyeHeight<1||eyeWidth>8192||eyeHeight>8192)
            throw new IllegalArgumentException("Invalid native cinema target");
        if(program==0)throw new IllegalStateException("Movie layer closed");
        int[] old=new int[6],viewport=new int[4];boolean[] masks=new boolean[4],enabled=new boolean[ENABLES.length];float[] clear=new float[4];
        GLES30.glGetIntegerv(GLES30.GL_CURRENT_PROGRAM,old,0);GLES30.glGetIntegerv(GLES30.GL_VERTEX_ARRAY_BINDING,old,1);
        GLES30.glGetIntegerv(GLES30.GL_ARRAY_BUFFER_BINDING,old,2);GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,old,3);
        GLES30.glGetIntegerv(GLES30.GL_VIEWPORT,viewport,0);GLES30.glGetBooleanv(GLES30.GL_COLOR_WRITEMASK,masks,0);GLES30.glGetFloatv(GLES30.GL_COLOR_CLEAR_VALUE,clear,0);
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0);GLES30.glGetIntegerv(GLES11Ext.GL_TEXTURE_BINDING_EXTERNAL_OES,old,4);GLES30.glGetIntegerv(GLES30.GL_SAMPLER_BINDING,old,5);
        for(int i=0;i<ENABLES.length;i++){enabled[i]=GLES30.glIsEnabled(ENABLES[i]);GLES30.glDisable(ENABLES[i]);}
        try {
            if(!latch())return false;
            GLES30.glColorMask(true,true,true,true);GLES30.glClearColor(0,0,0,1);GLES30.glClear(GLES30.GL_COLOR_BUFFER_BIT);
            GLES30.glUseProgram(program);GLES30.glBindVertexArray(vao);GLES30.glBindBuffer(GLES30.GL_ARRAY_BUFFER,buffer);
            GLES30.glEnableVertexAttribArray(0);GLES30.glVertexAttribPointer(0,4,GLES30.GL_FLOAT,false,16,0);
            GLES30.glBindSampler(0,0);GLES30.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,image);
            GLES30.glUniform1i(GLES30.glGetUniformLocation(program,"image"),0);GLES30.glUniform1i(GLES30.glGetUniformLocation(program,"linearOutput"),linearOutput?1:0);
            GLES30.glUniformMatrix4fv(GLES30.glGetUniformLocation(program,"transform"),1,false,transform,0);
            for(int eye=0;eye<2;eye++) {
                canvas.vertices(head,views,eye,vertices);upload.clear();upload.put(vertices).flip();
                GLES30.glBufferData(GLES30.GL_ARRAY_BUFFER,64,upload,GLES30.GL_STREAM_DRAW);
                GLES30.glViewport(eye*eyeWidth,0,eyeWidth,eyeHeight);GLES30.glDrawArrays(GLES30.GL_TRIANGLE_STRIP,0,4);
            }
            return true;
        }finally {
            GLES30.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES,old[4]);GLES30.glBindSampler(0,old[5]);GLES30.glActiveTexture(old[3]);GLES30.glBindVertexArray(old[1]);GLES30.glBindBuffer(GLES30.GL_ARRAY_BUFFER,old[2]);GLES30.glUseProgram(old[0]);
            GLES30.glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);GLES30.glColorMask(masks[0],masks[1],masks[2],masks[3]);GLES30.glClearColor(clear[0],clear[1],clear[2],clear[3]);
            for(int i=0;i<ENABLES.length;i++)if(enabled[i])GLES30.glEnable(ENABLES[i]);else GLES30.glDisable(ENABLES[i]);
        }
    }
    private void requireContext() {
        if(context.equals(EGL14.EGL_NO_CONTEXT)||!context.equals(EGL14.eglGetCurrentContext()))throw new IllegalStateException("Movie layer requires its owning EGL context");
    }
    private static int shader(int type,String code) {
        int shader=GLES30.glCreateShader(type);GLES30.glShaderSource(shader,code);GLES30.glCompileShader(shader);
        int[] ok={0};GLES30.glGetShaderiv(shader,GLES30.GL_COMPILE_STATUS,ok,0);
        if(ok[0]==0){String log=GLES30.glGetShaderInfoLog(shader);GLES30.glDeleteShader(shader);throw new IllegalStateException("Movie shader: "+log);}return shader;
    }
    /** Call only after AndroidMoviePlayer Close/Shutdown has acknowledged release. */
    @Override public void close() {
        requireContext();
        if(surface!=null){surface.release();surface=null;}if(texture!=null){texture.release();texture=null;}
        if(image!=0)GLES30.glDeleteTextures(1,new int[]{image},0);if(program!=0)GLES30.glDeleteProgram(program);
        if(vao!=0)GLES30.glDeleteVertexArrays(1,new int[]{vao},0);if(buffer!=0)GLES30.glDeleteBuffers(1,new int[]{buffer},0);
        image=program=vao=buffer=0;available=false;
    }
}
