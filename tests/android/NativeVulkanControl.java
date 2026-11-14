package org.gk3hd.standalone;

import android.app.Activity;
import com.winlator.core.EnvVars;
import com.winlator.xenvironment.XEnvironment;
import com.winlator.xserver.XServer;

/** Explicit debug opt-in for baselines prepared with the upstream driver. */
public final class NativeVulkanControl {
    public static void prepare(Activity activity,XEnvironment environment,XServer server,EnvVars vars) throws Exception {
        String name=activity.getClass().getName();
        int duration=activity.getIntent().getIntExtra("gk3hd_duration_seconds",0);
        boolean offhead=name.equals("com.winlator.OffHeadGameActivity");
        boolean nativeHost=name.equals("com.winlator.CrystalActivity")&&duration>0&&duration<=120&&
            activity.getIntent().getBooleanExtra("gk3hd_launch_game",false);
        if(!com.winlator.BuildConfig.DEBUG||(!offhead&&!nativeHost)||
           !activity.getPackageName().equals("org.gk3hd.standalone"))
            throw new IllegalArgumentException("Native Vulkan control requires an owned bounded development fixture");
        if(activity.getIntent().hasExtra("gk3hd_test_turnip")||
           activity.getIntent().getBooleanExtra("gk3hd_validate_gpu",false))
            throw new IllegalArgumentException("Native-driver and guest Turnip/validation controls cannot be combined");
        NativeVulkan.prepare(activity,environment,server,vars);
    }
}
