package org.gk3hd.standalone;

import java.util.Arrays;

/** Raw native action samples, not a second mapping of the game's actions. */
public final class OpenXrControllerSample {
    private OpenXrControllerSample() {}
    static int flags(int value) {
        if((value&~15)!=0)throw new IllegalArgumentException("Invalid native location flags");
        return value; // Same standard OpenXR flag order on both sides.
    }
    public static XrInput decode(float[] poses,int[] state) {
        if(poses.length!=36||state.length!=6)throw new IllegalArgumentException("Invalid native controller record");
        return new XrInput(hand(poses,state,0),hand(poses,state,1));
    }
    private static XrInput.Hand hand(float[] value,int[] state,int hand) {
        int p=hand*18,s=hand*3;
        return new XrInput.Hand(Arrays.copyOfRange(value,p,p+7),flags(state[s]),
            Arrays.copyOfRange(value,p+7,p+14),flags(state[s+1]),state[s+2],
            value[p+14],value[p+15],value[p+16],value[p+17]);
    }
}
