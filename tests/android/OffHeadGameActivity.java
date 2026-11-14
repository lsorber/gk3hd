package com.winlator;

import android.os.Bundle;
import org.gk3hd.standalone.NativeGameFlow;

/** Debug-source-set only. Real game + simulated viewer, no headset compositor. */
public final class OffHeadGameActivity extends StandaloneGameActivity {
    @Override protected org.gk3hd.standalone.XrRuntimeSelection.Backend graphicsRuntime() {
        // Retain the ordinary device's graphics profile even though this
        // fixture substitutes its presenter and controller input.
        // An independently observed profile may be declared explicitly to
        // isolate native runtime loading from this non-presenting fixture.
        String declared=getIntent().getStringExtra("gk3hd_test_graphics_runtime");
        if(declared!=null)
            return org.gk3hd.standalone.XrRuntimeSelection.Backend.valueOf(declared);
        return org.gk3hd.standalone.XrRuntimeDiscovery.discover(this);
    }
    @Override public void finish() {
        android.util.Log.i("GK3HDXR","Off-head Activity finish requested",new Throwable("Fixture finish origin"));
        super.finish();
    }
    @Override protected void onDestroy() {
        android.util.Log.i("GK3HDXR","Off-head Activity destroy identity="+System.identityHashCode(this)+
            " changing="+isChangingConfigurations()+" finishing="+isFinishing());
        super.onDestroy();OffHeadDisplayService.gameClosed(this);
    }
    @Override public void onCreate(Bundle state) {
        android.util.Log.i("GK3HDXR","Off-head Activity create identity="+System.identityHashCode(this)+
            " restored="+(state!=null));
        android.util.Log.i("GK3HDXR","Off-head source task display="+OffHeadDisplayService.activityDisplay(this));
        if(getIntent().hasExtra("gk3hd_private_display_id")) {
            int actual=OffHeadDisplayService.activityDisplay(this);
            android.util.Log.i("GK3HDXR","Private source task display="+actual+" contextDisplay="+getWindowManager().getDefaultDisplay().getDisplayId());
            if(getIntent().getIntExtra("gk3hd_private_display_id",-1)!=actual)
                throw new IllegalArgumentException("Private source Activity launched on another display");
        }
        String fixture=getIntent().getStringExtra("gk3hd_fixture_token");
        if(fixture==null) fixture=java.util.UUID.randomUUID().toString().replace("-","");
        if(!fixture.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("Invalid fixture token");
        getIntent().putExtra("gk3hd_fixture_token",fixture);
        String scenario=getIntent().getStringExtra("gk3hd_scenario");
        if(scenario==null) scenario="world";
        if(!scenario.equals("world")&&!scenario.equals("inventory")&&!scenario.equals("benchmark")&&!scenario.equals("navigation")&&!scenario.equals("save"))
            throw new IllegalArgumentException("Unknown off-head test scenario");
        getIntent().putExtra("gk3hd_scenario",scenario);
        getIntent().putExtra("gk3hd_test_snapshot_timing",true);
        boolean benchmark=scenario.equals("benchmark");
        int soakSeconds=getIntent().getIntExtra("gk3hd_test_exploration_soak_seconds",0);
        new org.gk3hd.standalone.ExplorationSoak(soakSeconds);
        if(soakSeconds!=0&&(!benchmark||!getIntent().getBooleanExtra("gk3hd_test_world_motion",false)))
            throw new IllegalArgumentException("Exploration soak requires a bounded moving world fixture");
        boolean correctnessOnly=getIntent().getBooleanExtra("gk3hd_test_correctness_only",false);
        boolean selectedPixels=getIntent().getBooleanExtra("gk3hd_test_selected_image_pixels",false);
        if(getIntent().getBooleanExtra("gk3hd_test_compare_padded_blit",false)&&!selectedPixels)
            throw new IllegalArgumentException("Padded blit comparison requires the selected-image probe");
        if(selectedPixels&&!correctnessOnly)
            throw new IllegalArgumentException("Selected-image reads require a correctness-only journey");
        if(correctnessOnly&&(!benchmark||!(getIntent().getBooleanExtra("gk3hd_validate_gpu",false)||selectedPixels)))
            throw new IllegalArgumentException("Correctness-only movement requires explicit GPU validation or image reads");
        boolean save=scenario.equals("save");
        boolean exceptions=getIntent().getBooleanExtra("gk3hd_test_seh",false);
        boolean processes=getIntent().getBooleanExtra("gk3hd_test_process",false);
        if(exceptions||processes)
            getOverrideEnvVars().put("WINEDEBUG","-all"+(exceptions ? ",+seh" : "")+
                (processes ? ",+process" : ""));
        if(getIntent().getBooleanExtra("gk3hd_test_perf_map",false)) {
            if(!benchmark) throw new IllegalArgumentException("JIT mapping is confined to the bounded diagnostic benchmark");
            getOverrideEnvVars().put("BOX64_DYNAREC_PERFMAP","1");
        }
        if(getIntent().getBooleanExtra("gk3hd_test_cpu_stability",false))
            getOverrideEnvVars().putAll(com.winlator.box64.Box64PresetManager.getEnvVars(this,com.winlator.box64.Box64Preset.STABILITY));
        String cpuFlags=getIntent().getStringExtra("gk3hd_test_cpu_flags");
        if(cpuFlags!=null) {
            if(cpuFlags.isEmpty()||cpuFlags.length()>256) throw new IllegalArgumentException("Unbounded test CPU flags");
            java.util.HashSet<String> seen=new java.util.HashSet<>();
            for(String flag:cpuFlags.split(",",-1)) {
                String[] pair=flag.split("=",-1);
                if(pair.length!=2||!pair[0].matches("SAFEFLAGS|FASTNAN|FASTROUND|X87DOUBLE|BIGBLOCK|STRONGMEM|FORWARD|CALLRET|WAIT|NATIVEFLAGS|WEAKBARRIER")||
                   !pair[1].matches("[0-9]{1,4}")||!seen.add(pair[0])||
                   Integer.parseInt(pair[1])>(pair[0].equals("FORWARD") ? 1024 : 3))
                    throw new IllegalArgumentException("Unsupported test CPU flag");
                getOverrideEnvVars().put("BOX64_DYNAREC_"+pair[0],pair[1]);
            }
            android.util.Log.i("GK3HDXR","Diagnostic CPU overrides="+cpuFlags);
        }
        if(save||benchmark) {
            String token=getIntent().getStringExtra("gk3hd_observation_token");
            if(token==null)token=java.util.UUID.randomUUID().toString().replace("-","");
            if(!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Invalid observation token");
            getIntent().putExtra("gk3hd_observation_token",token);
            getOverrideEnvVars().put("GK3HD_STANDALONE_OBSERVE",token);
            if(getIntent().getBooleanExtra("gk3hd_test_stacks",false))
                getOverrideEnvVars().put("GK3HD_STANDALONE_STACKS","1");
            if(getIntent().getBooleanExtra("gk3hd_test_trace_fast",false))
                getOverrideEnvVars().put("GK3HD_XR_TRACE_FAST","1");
            if(getIntent().getBooleanExtra("gk3hd_test_trace_panel",false))
                getOverrideEnvVars().put("GK3HD_XR_TRACE_PANEL","1");
            if(benchmark) getIntent().putExtra("gk3hd_flow_mode","benchmark");
            else if(!getIntent().hasExtra("gk3hd_flow_mode")) getIntent().putExtra("gk3hd_flow_mode","save");
        }
        int eye=getIntent().getIntExtra("gk3hd_test_eye",2060);
        org.gk3hd.standalone.FixtureEyeExtent extent=new org.gk3hd.standalone.FixtureEyeExtent(
            eye,getIntent().getIntExtra("gk3hd_test_eye_height",eye));
        if(extent.width!=extent.height&&!benchmark)
            throw new IllegalArgumentException("Rectangular targets require the bounded benchmark journey");
        int consumerHz=getIntent().getIntExtra("gk3hd_test_consumer_hz",90);
        boolean fasterService=benchmark&&consumerHz==180&&
            getIntent().getIntExtra("gk3hd_test_draw_hz",consumerHz)==90;
        // Extent admission is independent of cadence and headset model.
        if(consumerHz!=30&&consumerHz!=90&&consumerHz!=120&&!fasterService)
            throw new IllegalArgumentException("Unsupported bounded performance control");
        String gpuMode=getIntent().getStringExtra("gk3hd_test_gpu_mode");
        if(gpuMode==null) gpuMode="auto";
        if(!gpuMode.equals("auto")&&!gpuMode.equals("sysmem")&&!gpuMode.equals("gmem"))
            throw new IllegalArgumentException("Unknown test GPU render mode");
        if(!gpuMode.equals("auto")) getOverrideEnvVars().put("TU_DEBUG","noconform,"+gpuMode);
        String presentMode=getIntent().getStringExtra("gk3hd_test_present_mode");
        if(presentMode!=null) {
            if(!presentMode.equals("fifo")&&!presentMode.equals("immediate")&&!presentMode.equals("mailbox"))
                throw new IllegalArgumentException("Unknown transport present mode");
            if(!presentMode.equals("fifo")) getOverrideEnvVars().put("GK3HD_WXR_PRESENT_MODE",presentMode);
            getOverrideEnvVars().put("MESA_VK_WSI_PRESENT_MODE",presentMode);
            android.util.Log.i("GK3HDXR","Diagnostic transport present mode="+presentMode);
        }
        String driverVersion=getIntent().getStringExtra("gk3hd_test_turnip");
        if(driverVersion!=null) {
            if(!driverVersion.equals("25.0.0")&&!driverVersion.equals("26.0.3"))
                throw new IllegalArgumentException("Unsupported private-driver control");
            // Explicit lab-only comparison with Winlator's published components.
            // Never replace the installed driver or system Vulkan.
            boolean older=driverVersion.equals("25.0.0");
            long expectedSize=older ? 11511360 : 15225528;
            String expectedHash=older ? "ea21ccfa1346c22e8f384d0334984b89d6b82024972abd68e558612a7f984969" :
                "15ad188ba8183e96bd6bee469fe8acfa588e6ad1dd5102081036946e9a6355c7";
            java.io.File directory=new java.io.File(getFilesDir(),"gk3hd-driver-control/"+driverVersion);
            java.io.File driver=new java.io.File(directory,"libvulkan_freedreno.so");
            try {
                if(!driver.isFile()||driver.length()!=expectedSize||
                   !org.gk3hd.standalone.StandaloneBundle.hash(driver).equals(expectedHash))
                    throw new IllegalStateException("Stage the exact upstream Turnip "+driverVersion+" control first");
                org.json.JSONObject icd=new org.json.JSONObject().put("file_format_version","1.0.1")
                    .put("ICD",new org.json.JSONObject().put("api_version",older ? "1.1.246" : "1.4.318")
                        .put("library_arch","64").put("library_path",driver.getCanonicalPath()));
                java.io.File manifest=new java.io.File(directory,"icd.json");
                java.nio.file.Files.write(manifest.toPath(),icd.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                getOverrideEnvVars().put("VK_ICD_FILENAMES",manifest.getCanonicalPath());
                android.util.Log.i("GK3HDXR","Diagnostic private Turnip "+driverVersion+" control enabled");
            } catch(Exception error) {throw new IllegalStateException("Cannot select the bounded private-driver control",error);}
        }
        if(getIntent().getBooleanExtra("gk3hd_test_direct_encoded",false)) getOverrideEnvVars().put("GK3HD_XR_DIRECT_ENCODED","1");
        // Projection readbacks are independent of the presenter's final-eye
        // screenshots. Keep their GPU stalls and file writes out of ordinary
        // controller journeys unless input-image inspection is requested.
        if(getIntent().getBooleanExtra("gk3hd_test_capture_projection",false)) {
            // The opening-room smoke is a finite correctness journey, not a
            // timing sample. Its first projections are exactly what we inspect.
            if(benchmark&&!correctnessOnly&&!getIntent().getBooleanExtra("gk3hd_test_startup_smoke",false))
                throw new IllegalArgumentException("Projection readbacks are not a performance benchmark");
            getOverrideEnvVars().put("GK3HD_XR_CAPTURE_EYES","1");
        }
        if(getIntent().getBooleanExtra("gk3hd_validate_gpu",false)) {
            if(benchmark&&!correctnessOnly) throw new IllegalArgumentException("Validation is not a performance benchmark");
            if(correctnessOnly) android.util.Log.i("GK3HDXR",
                "CORRECTNESS-ONLY: moving fixture requests GPU validation; timing is not performance qualification");
            java.io.File layers=new java.io.File(getFilesDir(),"gk3hd-validation");
            if(!new java.io.File(layers,"libVkLayer_khronos_validation.so").isFile())
                throw new IllegalStateException("Stage the optional lab GPU validation layer first");
            getOverrideEnvVars().put("VK_LAYER_PATH",layers.getAbsolutePath());
            getOverrideEnvVars().put("VK_LAYER_SETTINGS_PATH",layers.getAbsolutePath());
            getOverrideEnvVars().put("VK_INSTANCE_LAYERS","VK_LAYER_KHRONOS_validation");
            getOverrideEnvVars().put("LD_LIBRARY_PATH",layers.getAbsolutePath()+":"+
                new java.io.File(getFilesDir(),"rootfs/lib").getAbsolutePath());
        }
        // SIDNEY includes two retail chapter/script transitions before its
        // controller journey. Keep its finite guest budget below the host's
        // cleanup deadline, without terminating before the final native Quit.
        boolean sidney=getIntent().getBooleanExtra("gk3hd_test_sidney_journey",false);
        getIntent().putExtra("gk3hd_launch_game",true)
            .putExtra("gk3hd_game_seconds",sidney ? 105 : save ? 90 : benchmark ? 105 : scenario.equals("inventory") ? 48 : 40).putExtra("gk3hd_desktop_control",false)
            .putExtra("gk3hd_duration_seconds",save ? 110 : benchmark ? 110 : scenario.equals("inventory") ? 63 : 55)
            .putExtra("gk3hd_capture_guest",!benchmark&&(!save||getIntent().getBooleanExtra("gk3hd_test_capture_game",false)))
            .putExtra("gk3hd_capture_tag","offhead-game05").putExtra("gk3hd_capture_interval_ms",5000);
        if(getIntent().getBooleanExtra("gk3hd_test_transport_only",false)) {
            getOverrideEnvVars().remove("GK3HD_XR_CAPTURE_EYES");
            getOverrideEnvVars().put("GK3HD_TRANSPORT_TOKEN",fixture);
            if(!scenario.equals("world")) throw new IllegalArgumentException("Transport fixture must not start game automation");
            com.winlator.container.Container container=new com.winlator.container.ContainerManager(this)
                .getContainerById(getIntent().getIntExtra("container_id",0));
            if(container==null) throw new IllegalArgumentException("Select an owned fixture container");
            java.io.File executable=new java.io.File(container.getRootDir(),".wine/drive_c/gk3hd-vr/gk3hd-vulkan-quad-tests.exe");
            if(!executable.isFile()||executable.length()>4*1024*1024)
                throw new IllegalArgumentException("Stage the bounded transport fixture first");
            int cycles=getIntent().getIntExtra("gk3hd_test_transport_cycles",4);
            if(cycles!=1&&cycles!=4) throw new IllegalArgumentException("Transport fixture requires one or four sessions");
            getIntent().putExtra("gk3hd_launch_game",false).putExtra("gk3hd_capture_guest",false)
                .putExtra("gk3hd_duration_seconds",65).putExtra("gk3hd_test_stereo_source",true)
                .putExtra("gk3hd_test_transport_cycles",cycles)
                .putExtra("exec_path",executable.getPath()+(cycles==4 ? " --stereo-lifecycle" : " --stereo-transport"));
        }
        if(getIntent().getBooleanExtra("gk3hd_test_fence_contract",false)) {
            if(!scenario.equals("world")||getIntent().getBooleanExtra("gk3hd_test_transport_only",false))
                throw new IllegalArgumentException("Fence fixture must not start game/transport automation");
            com.winlator.container.Container container=new com.winlator.container.ContainerManager(this)
                .getContainerById(getIntent().getIntExtra("container_id",0));
            if(container==null)throw new IllegalArgumentException("Select the owned fixture container");
            java.io.File executable=new java.io.File(container.getRootDir(),".wine/drive_c/gk3hd-vr/gk3hd-fence-contract.exe");
            if(!executable.isFile()||executable.length()>1024*1024)
                throw new IllegalArgumentException("Stage the bounded fence fixture first");
            getOverrideEnvVars().remove("GK3HD_XR_CAPTURE_EYES");
            getOverrideEnvVars().put("GK3HD_FENCE_TOKEN",fixture);
            getIntent().putExtra("gk3hd_launch_game",false).putExtra("gk3hd_capture_guest",false)
                .putExtra("gk3hd_duration_seconds",45).putExtra("gk3hd_native_vulkan",true)
                .putExtra("exec_path",executable.getPath());
        }
        if(getIntent().getBooleanExtra("gk3hd_test_host_retirement",false)) {
            if(!benchmark)throw new IllegalArgumentException("Host retirement requires the bounded benchmark fixture");
            getOverrideEnvVars().remove("GK3HD_STANDALONE_OBSERVE");
            // The host, rather than the helper's diagnostic deadline, ends this
            // owned game. Verify child retirement before stopping app services.
            getIntent().putExtra("gk3hd_game_seconds",0).putExtra("gk3hd_duration_seconds",20);
        }
        int extraSeconds=soakSeconds+NativeGameFlow.titleIntroAllowance(getIntent());
        if(getIntent().getBooleanExtra("gk3hd_test_long_travel",false)) {
            if(!benchmark||!getIntent().getBooleanExtra("gk3hd_test_restore_cycles",false))
                throw new IllegalArgumentException("Long travel requires the bounded multi-Restore fixture");
            extraSeconds+=24;
        }
        if(extraSeconds>0) {
            // Diagnostic observation requires a finite supervisor lifetime.
            // Keep its deadline inside the Activity, service and host bounds.
            getIntent().putExtra("gk3hd_game_seconds",105+extraSeconds)
                .putExtra("gk3hd_duration_seconds",110+extraSeconds);
        }
        super.onCreate(state);
        // The host retires itself if graphics initialization fails. Preserve
        // that original failure instead of dereferencing its absent view.
        if(isFinishing())return;
        if(getIntent().getBooleanExtra("gk3hd_test_offscreen",false)) {
            if(!benchmark&&!save)throw new IllegalArgumentException("Offscreen workbench requires a bounded game flow");
            try {getXServerView().getClass().getMethod("startTestOffscreen").invoke(getXServerView());}
            catch(Exception failure){throw new IllegalStateException("Build the isolated offscreen test APK first",failure);}
        }
        boolean retireWindow=getIntent().getBooleanExtra("gk3hd_test_retire_android_window",false);
        if(retireWindow) {
            if(!benchmark||!getIntent().getBooleanExtra("gk3hd_test_offscreen",false)||
               (getApplicationInfo().flags&android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)==0)
                throw new IllegalArgumentException("Window retirement requires the private bounded offscreen benchmark");
            android.view.WindowManager.LayoutParams attributes=getWindow().getAttributes();
            attributes.alpha=0.0f;getWindow().setAttributes(attributes);
            getXServerView().setVisibility(android.view.View.INVISIBLE);
        }
        android.util.Log.i("GK3HDXR","Owned off-head Android window retire="+retireWindow+
            " alpha="+getWindow().getAttributes().alpha+" viewVisibility="+getXServerView().getVisibility());
        OffHeadDisplayService.gameStarted(this);
    }
}
