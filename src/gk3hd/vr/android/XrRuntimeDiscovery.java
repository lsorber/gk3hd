package org.gk3hd.standalone;

import android.content.Context;

/** Capability-only discovery, before requesting vendor tracking permissions. */
public final class XrRuntimeDiscovery {
    private XrRuntimeDiscovery() {}
    public static XrRuntimeSelection.Backend discover(Context context) {
        int support=NativeOpenXr.capabilities(context.getApplicationContext());
        boolean pimax=false;
        if(support==0) {
            try {
                // Inspect availability without initializing a vendor service.
                Class.forName("com.pimax.pxrapi.PxrApi",false,context.getClassLoader());
                pimax=true;
            }catch(ClassNotFoundException absent) { /* No vendor fallback. */ }
        }
        return XrRuntimeSelection.choose(support,pimax);
    }
}
