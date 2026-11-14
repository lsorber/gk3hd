package org.gk3hd.standalone;

import android.app.Activity;
import android.content.Context;
import java.util.Arrays;

/** Android loader/GLES binding. No headset vendor API or synthetic tracking. */
final class NativeOpenXr {
    static final int FRAME_STATE_SIZE=8;
    // Non-frame results returned in state[0], matching PackedSession::EndReason.
    static final int SESSION_EXIT=-1, SESSION_LOST=-2, INSTANCE_LOST=-3;
    static {System.loadLibrary("gk3hd_openxr");}
    static native int capabilities(Context context);
    static native long create(Activity activity,int eyeWidth,int eyeHeight);
    static native void dimensions(long host,int[] size);
    static native void attach(long host);
    static native void detach(long host);
    static native boolean next(long host,float[] poses,long[] state);
    /** Return the writable framebuffer, or zero on swapchain wait timeout. */
    static native int acquire(long host);
    static native void controllers(long host,float[] values,int[] state);
    static native boolean end(long host,long renderedSerial);
    static native boolean repeat(long host,long renderedSerial);
    static native void close(long host);

    static final class SessionLost extends IllegalStateException {
        private static final long serialVersionUID=1L;
        SessionLost() {super("The headset stopped the OpenXR session. Open GK3HD VR again.");}
    }
    static final class InstanceLost extends IllegalStateException {
        private static final long serialVersionUID=1L;
        InstanceLost() {super("The headset's OpenXR runtime disconnected. Open GK3HD VR again.");}
    }

    static final class Frame {
        final long serial,time,period,epoch,reusableSerial;
        final int flags;
        final boolean shouldRender,focused;
        final float[] head;
        final StereoViews views;
        final float ipd,fovX,fovY;
        Frame(float[] poses,long[] state) {
            serial=state[0];time=state[1];period=state[2];
            epoch=state[6];reusableSerial=state[7];
            // OpenXR and the guest wire both use Ovalid,Pvalid,Otracked,Ptracked.
            flags=(int)state[3];
            if((flags&~15)!=0)throw new IllegalArgumentException("Invalid native head location flags");
            shouldRender=state[4]!=0;focused=state[5]!=0;
            head=Arrays.copyOfRange(poses,0,7);
            if((flags&3)==3) {
                float[] left=Arrays.copyOfRange(poses,7,14),right=Arrays.copyOfRange(poses,18,25);
                float[] lf=Arrays.copyOfRange(poses,14,18),rf=Arrays.copyOfRange(poses,25,29);
                views=new StereoViews(left,lf,right,rf);
                double distance=0;for(int i=0;i<3;i++)distance+=(right[i]-left[i])*(right[i]-left[i]);
                ipd=(float)Math.sqrt(distance);
                fovX=Math.max(lf[1]-lf[0],rf[1]-rf[0]);
                fovY=Math.max(lf[2]-lf[3],rf[2]-rf[3]);
            } else {
                // Neutral finite values only accompany unavailable flags. They
                // are never remembered or submitted as tracked image views.
                head[6]=1;views=null;ipd=.064f;fovX=(float)Math.PI/2;fovY=(float)Math.PI/2;
            }
        }
    }
}
