package org.gk3hd.standalone;

import android.app.Activity;
import android.graphics.Bitmap;
import android.opengl.GLES30;
import android.util.Log;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.io.File;

/** One post-submit source capture; it never changes tracking or controller input. */
public final class NativeGameObserver {
    private static boolean captured;
    public static void observe(Activity activity,int eyeWidth,int eyeHeight,int id,long started) throws Exception {
        if(captured||System.nanoTime()-started<25_000_000_000L) return;
        captured=true;
        String tag=activity.getIntent().getStringExtra("gk3hd_capture_tag");
        if(tag==null||!tag.matches("[a-z0-9-]{1,32}")) throw new IllegalArgumentException("Explicit bounded observation tag required");
        int width=eyeWidth*2,height=eyeHeight;
        ByteBuffer bytes=ByteBuffer.allocateDirect(width*height*4).order(ByteOrder.LITTLE_ENDIAN);
        GLES30.glReadPixels(0,0,width,height,GLES30.GL_RGBA,GLES30.GL_UNSIGNED_BYTE,bytes);
        int[] pixels=new int[width*height];long[] visible={0,0};long different=0;
        for(int y=0;y<height;y++) for(int x=0;x<width;x++) {
            int p=bytes.getInt((y*width+x)*4);
            pixels[(height-1-y)*width+x]=(p&0xff00ff00)|((p&0xff)<<16)|((p>>>16)&255);
            if((p&0xffffff)!=0) visible[x/eyeWidth]++;
            if(x<eyeWidth&&(p&0xffffff)!=(bytes.getInt((y*width+x+eyeWidth)*4)&0xffffff)) different++;
        }
        Bitmap bitmap=Bitmap.createBitmap(pixels,width,height,Bitmap.Config.ARGB_8888);
        try(java.io.FileOutputStream out=new java.io.FileOutputStream(new File(activity.getFilesDir(),"native-stereo-"+tag+".png"))) {
            bitmap.compress(Bitmap.CompressFormat.PNG,100,out);
        } finally {bitmap.recycle();}
        try(java.io.PrintWriter out=new java.io.PrintWriter(new File(activity.getFilesDir(),"native-stereo-"+tag+".json"))) {
            out.println("{\"frame_id\":"+id+",\"width\":"+width+",\"height\":"+height+
                ",\"left_visible\":"+visible[0]+",\"right_visible\":"+visible[1]+",\"eye_differences\":"+different+"}");
        }
        Log.i("GK3HDXR","Native post-submit source captured, not through-lens acceptance: left="+visible[0]+
            " right="+visible[1]+" differences="+different+" id="+id);
    }
}
