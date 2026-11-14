package org.gk3hd.standalone;

import android.opengl.EGL14;
import android.opengl.EGLContext;
import android.opengl.GLES30;

/** Copy visible eyes at integer pixel centers, excluding metadata and padding.
 * Some Adreno blits lose row precision at non-power-of-two eye heights. Keep
 * this as one GPU draw with no CPU pixels, extra image, or completion wait.
 */
public final class StereoCopy implements AutoCloseable {
    private final EGLContext context=EGL14.eglGetCurrentContext();
    private final boolean linearOutput;
    private int program,vao,sampler,sourceImage,sourceSize,firstRow,outputSize,flipped;
    private static final int[] ENABLES={GLES30.GL_BLEND,GLES30.GL_CULL_FACE,GLES30.GL_DEPTH_TEST,
        GLES30.GL_STENCIL_TEST,GLES30.GL_SCISSOR_TEST,GLES30.GL_RASTERIZER_DISCARD,GLES30.GL_DITHER,
        GLES30.GL_SAMPLE_ALPHA_TO_COVERAGE,GLES30.GL_SAMPLE_COVERAGE};
    public StereoCopy() {this(false);}
    /** An sRGB compositor attachment expects linear shader values. Input
     * snapshots remain encoded RGBA8, including their untouched identity row.
     */
    public StereoCopy(boolean linearOutput) {this.linearOutput=linearOutput;}
    private static int shader(int type,String source) {
        int object=GLES30.glCreateShader(type);GLES30.glShaderSource(object,source);GLES30.glCompileShader(object);
        int[] status=new int[1];GLES30.glGetShaderiv(object,GLES30.GL_COMPILE_STATUS,status,0);
        if(status[0]==0){String log=GLES30.glGetShaderInfoLog(object);GLES30.glDeleteShader(object);throw new IllegalStateException("Exact copy shader: "+log);}return object;
    }
    private void initialize() {
        int vertex=shader(GLES30.GL_VERTEX_SHADER,"#version 300 es\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.0-1.0,0,1);}");
        int fragment;
        String conversion=linearOutput ? "color.rgb=mix(pow((color.rgb+0.055)/1.055,vec3(2.4)),color.rgb/12.92,lessThanEqual(color.rgb,vec3(0.04045)));" : "";
        try {
            fragment=shader(GLES30.GL_FRAGMENT_SHADER,
                "#version 300 es\nprecision highp float;precision highp int;\n"+
                "uniform highp sampler2D sourceImage;uniform ivec2 sourceSize;uniform int firstRow;\n"+
                "uniform ivec2 outputSize;uniform int flipped;out vec4 color;\n"+
                "void main() {\n"+
                "    ivec2 p = ivec2(gl_FragCoord.xy);\n"+
                "    ivec2 q = p;\n"+
                "    if (any(notEqual(sourceSize, outputSize)))\n"+
                "        q = ((p * 2 + 1) * sourceSize) / (outputSize * 2);\n"+
                "    q.y = flipped != 0 ? sourceSize.y - 1 - q.y : firstRow + q.y;\n"+
                "    color = texelFetch(sourceImage, q, 0);\n"+
                conversion+"\n}\n");
        }
        catch(RuntimeException failure){GLES30.glDeleteShader(vertex);throw failure;}
        int candidate=GLES30.glCreateProgram();GLES30.glAttachShader(candidate,vertex);GLES30.glAttachShader(candidate,fragment);GLES30.glLinkProgram(candidate);GLES30.glDeleteShader(vertex);GLES30.glDeleteShader(fragment);
        int[] status=new int[1];GLES30.glGetProgramiv(candidate,GLES30.GL_LINK_STATUS,status,0);
        if(status[0]==0){String log=GLES30.glGetProgramInfoLog(candidate);GLES30.glDeleteProgram(candidate);throw new IllegalStateException("Exact copy link: "+log);}program=candidate;
        int[] array=new int[1];GLES30.glGenVertexArrays(1,array,0);vao=array[0];GLES30.glGenSamplers(1,array,0);sampler=array[0];
        GLES30.glSamplerParameteri(sampler,GLES30.GL_TEXTURE_MIN_FILTER,GLES30.GL_NEAREST);
        GLES30.glSamplerParameteri(sampler,GLES30.GL_TEXTURE_MAG_FILTER,GLES30.GL_NEAREST);
        sourceImage=GLES30.glGetUniformLocation(program,"sourceImage");sourceSize=GLES30.glGetUniformLocation(program,"sourceSize");firstRow=GLES30.glGetUniformLocation(program,"firstRow");outputSize=GLES30.glGetUniformLocation(program,"outputSize");flipped=GLES30.glGetUniformLocation(program,"flipped");
    }
    public void draw(int texture,int width,int height,int visibleHeight,boolean flip,int outputWidth,int outputHeight) {
        draw(texture,width,height,visibleHeight,flip,outputWidth,outputHeight,false);
    }
    /** Only explicitly owned transparent guest layers may blend over a native movie. */
    public void draw(int texture,int width,int height,int visibleHeight,boolean flip,int outputWidth,int outputHeight,boolean overlay) {
        if(texture==0||width<1||height<2||outputWidth<1||outputHeight<1||
            visibleHeight<1||visibleHeight>=height||
            width>32768||height>32768||outputWidth>32768||outputHeight>32768)
            throw new IllegalArgumentException("Exact copy dimensions outside integer range");
        if(!context.equals(EGL14.eglGetCurrentContext()))throw new IllegalStateException("Exact copy requires its owning GL context");
        if(program==0)initialize();
        int[] old=new int[5],viewport=new int[4];boolean[] masks=new boolean[4],enabled=new boolean[ENABLES.length];
        int[] blend=new int[6];
        if(overlay) {
            int[] names={GLES30.GL_BLEND_SRC_RGB,GLES30.GL_BLEND_DST_RGB,GLES30.GL_BLEND_SRC_ALPHA,GLES30.GL_BLEND_DST_ALPHA,GLES30.GL_BLEND_EQUATION_RGB,GLES30.GL_BLEND_EQUATION_ALPHA};
            for(int i=0;i<names.length;i++)GLES30.glGetIntegerv(names[i],blend,i);
        }
        GLES30.glGetIntegerv(GLES30.GL_CURRENT_PROGRAM,old,0);GLES30.glGetIntegerv(GLES30.GL_VERTEX_ARRAY_BINDING,old,1);
        GLES30.glGetIntegerv(GLES30.GL_ACTIVE_TEXTURE,old,2);GLES30.glGetIntegerv(GLES30.GL_VIEWPORT,viewport,0);GLES30.glGetBooleanv(GLES30.GL_COLOR_WRITEMASK,masks,0);
        GLES30.glActiveTexture(GLES30.GL_TEXTURE0);GLES30.glGetIntegerv(GLES30.GL_TEXTURE_BINDING_2D,old,3);GLES30.glGetIntegerv(GLES30.GL_SAMPLER_BINDING,old,4);
        for(int i=0;i<ENABLES.length;i++){enabled[i]=GLES30.glIsEnabled(ENABLES[i]);GLES30.glDisable(ENABLES[i]);}
        try {
            if(overlay){GLES30.glEnable(GLES30.GL_BLEND);GLES30.glBlendEquation(GLES30.GL_FUNC_ADD);GLES30.glBlendFunc(GLES30.GL_ONE,GLES30.GL_ONE_MINUS_SRC_ALPHA);}
            GLES30.glColorMask(true,true,true,true);GLES30.glViewport(0,0,outputWidth,outputHeight);GLES30.glUseProgram(program);GLES30.glBindVertexArray(vao);GLES30.glBindSampler(0,sampler);GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,texture);
            GLES30.glUniform1i(sourceImage,0);GLES30.glUniform2i(sourceSize,width,visibleHeight);GLES30.glUniform1i(firstRow,height-visibleHeight);GLES30.glUniform2i(outputSize,outputWidth,outputHeight);GLES30.glUniform1i(flipped,flip?1:0);GLES30.glDrawArrays(GLES30.GL_TRIANGLES,0,3);
        } finally {
            if(overlay){GLES30.glBlendFuncSeparate(blend[0],blend[1],blend[2],blend[3]);GLES30.glBlendEquationSeparate(blend[4],blend[5]);}
            GLES30.glBindTexture(GLES30.GL_TEXTURE_2D,old[3]);GLES30.glBindSampler(0,old[4]);GLES30.glActiveTexture(old[2]);GLES30.glBindVertexArray(old[1]);GLES30.glUseProgram(old[0]);GLES30.glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);GLES30.glColorMask(masks[0],masks[1],masks[2],masks[3]);
            for(int i=0;i<ENABLES.length;i++)if(enabled[i])GLES30.glEnable(ENABLES[i]);else GLES30.glDisable(ENABLES[i]);
        }
    }
    @Override public void close() {
        if(context.equals(EGL14.eglGetCurrentContext())){if(program!=0)GLES30.glDeleteProgram(program);if(vao!=0)GLES30.glDeleteVertexArrays(1,new int[]{vao},0);if(sampler!=0)GLES30.glDeleteSamplers(1,new int[]{sampler},0);}program=vao=sampler=0;
    }
}
