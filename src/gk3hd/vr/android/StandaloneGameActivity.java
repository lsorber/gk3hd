package com.winlator;

import android.content.SharedPreferences;
import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import java.io.File;
import org.gk3hd.standalone.RendererRecovery;
import org.gk3hd.standalone.StandaloneInstallation;
import org.gk3hd.standalone.TurnipAssets;
import org.gk3hd.standalone.XrPresenter;
import org.gk3hd.standalone.XrRuntimeSelection;

/** Shared private-player launch and lifetime, independent of the headset adapter. */
public abstract class StandaloneGameActivity extends XServerDisplayActivity {
    private final com.winlator.core.Callback<String> guestDebug=line->android.util.Log.d("GK3HDGuest",line);
    private File frameMetadata;
    private String frameSession;

    public File frameMetadata() {return frameMetadata;}

    protected XrRuntimeSelection.Backend graphicsRuntime() {
        return "openxr".equals(getIntent().getStringExtra("gk3hd_xr_presenter"))
            ? XrRuntimeSelection.Backend.OPENXR : XrRuntimeSelection.Backend.PIMAX;
    }
    @Override protected boolean prepareDisplayStartup() {
        if(!getIntent().hasExtra("container_id")) throw new IllegalArgumentException("Select an existing game container");
        Container container=new ContainerManager(this).getContainerById(getIntent().getIntExtra("container_id",0));
        if(container!=null&&"1".equals(container.getExtra("gk3hdManaged"))&&StandaloneInstallation.updatePending(container.getRootDir())) {
            android.widget.Toast.makeText(this,
                "The last GK3HD VR update was interrupted. Run the installer again to recover it.",
                android.widget.Toast.LENGTH_LONG).show();
            return false;
        }
        getIntent().putExtra("gk3hd_vr",true);
        if(getIntent().getBooleanExtra("gk3hd_launch_game",false)) {
            if(container==null || !StandaloneActivity.prepared(container))
                throw new IllegalArgumentException("Prepare the private standalone player first");
            int duration=getIntent().getIntExtra("gk3hd_game_seconds",0);
            boolean desktop=getIntent().getBooleanExtra("gk3hd_desktop_control",false);
            if(duration<0 || duration>720 || desktop && duration==0)
                throw new IllegalArgumentException("Diagnostic desktop input requires a bounded game duration");
            File launcher=new File(container.getRootDir(),".wine/drive_c/gk3hd-vr/gk3hd-wine-launcher.exe");
            File metadata=new File(launcher.getParentFile(),"gk3hd-player.json");
            try {
                if(!metadata.isFile()||metadata.length()>65536) throw new IllegalArgumentException("Missing or oversized private player description");
                org.json.JSONObject description=new org.json.JSONObject(new String(java.nio.file.Files.readAllBytes(metadata.toPath()),java.nio.charset.StandardCharsets.UTF_8));
                String backend=description.optString("graphics_backend","turnip");
                String output=description.getString("output_contract");
                if(!output.equals("stereo-only")&&!output.equals("desktop-mirror")) throw new IllegalArgumentException("Unsupported player output contract: "+output);
                if(!backend.equals("native-vulkan")&&!backend.equals("turnip")) throw new IllegalArgumentException("Unsupported private graphics backend: "+backend);
                getIntent().putExtra("gk3hd_native_vulkan",backend.equals("native-vulkan"));
                XrRuntimeSelection.Backend runtime=graphicsRuntime();
                // The pinned private Turnip driver needs this for legacy UI/movie
                // attachments on both supported headsets. It is not an XR-runtime
                // property; system Vulkan and PC VR retain their normal layout.
                String textureLayout=backend.equals("turnip") ? "npot" : "0";
                getOverrideEnvVars().put("GK3HD_LINEAR_RGB565",textureLayout);
                getIntent().putExtra("gk3hd_graphics_runtime",runtime.name());
                getIntent().putExtra("gk3hd_rgb565_layout",textureLayout);
                android.util.Log.i("GK3HDXR","Graphics profile runtime="+runtime+
                    " backend="+backend+" rgb565="+textureLayout);
                boolean allocationCompat=backend.equals("turnip");
                if(BuildConfig.DEBUG&&getIntent().getBooleanExtra("gk3hd_test_no_allocation_compat",false))
                    allocationCompat=false;
                getOverrideEnvVars().put("GK3HD_GPU_ALLOC_COMPAT",allocationCompat ? "1" : "0");
                getOverrideEnvVars().put("GK3HD_STANDALONE_OUTPUT",output);
                boolean ordinaryRestart=getIntent().getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false);
                boolean playerLaunch=getIntent().getBooleanExtra(StandaloneActivity.PLAY_PROFILE,false);
                String qualitySize=playerLaunch&&!ordinaryRestart
                    ? XrRuntimeSelection.headsetEyeResolution(runtime,android.os.Build.MODEL) : null;
                if(ordinaryRestart||playerLaunch||getIntent().hasExtra(StandaloneActivity.EXPERIMENTAL_COMPRESSED)) {
                    boolean requested=getIntent().getBooleanExtra(StandaloneActivity.EXPERIMENTAL_COMPRESSED,qualitySize!=null);
                    // The guest transport is independent of the headset presenter.
                    // OpenXR still uses its existing linear-output shader copy.
                    boolean compressed=requested&&!ordinaryRestart&&
                        backend.equals("turnip")&&TurnipAssets.supportsCompressedX11(this);
                    String setting=compressed?"1":"0";
                    getOverrideEnvVars().put("GK3HD_WXR_DIRECT_TARGET",setting);
                    getOverrideEnvVars().put("MESA_GK3HD_COMPRESSED_X11",setting);
                    getIntent().removeExtra(XrRuntimeSelection.HEADSET_EYE_RESOLUTION);
                    if(compressed&&qualitySize!=null) {
                        getIntent().putExtra(XrRuntimeSelection.HEADSET_EYE_RESOLUTION,qualitySize);
                        if(runtime==XrRuntimeSelection.Backend.PIMAX)
                            getIntent().putExtra("gk3hd_experimental_eye_copy",true);
                    }
                    if(ordinaryRestart)
                        android.util.Log.i("GK3HDXR","Restarting the graphics session with ordinary projection");
                    else if(compressed&&qualitySize!=null)
                        android.util.Log.i("GK3HDXR","Using compressed headset profile at "+qualitySize+" per eye");
                    else if(requested)
                        android.util.Log.i("GK3HDXR",compressed?"Trying experimental compressed stereo":
                            "Compressed stereo unavailable with the selected graphics driver");
                }
                // A per-launch namespace, not a diagnostic activation file.
                // The runtime creates this bounded mapping only for this host.
                String session=java.util.UUID.randomUUID().toString().replace("-","");
                frameSession=session;
                getIntent().putExtra("gk3hd_frame_session",session);
                getOverrideEnvVars().put("GK3HD_FRAME_SESSION",session);
                frameMetadata=new File(launcher.getParentFile(),"gk3hd-frame-"+session+".map");
                if(frameMetadata.exists())throw new IllegalStateException("New frame session is occupied");
            } catch(Exception error) {throw new IllegalStateException("Cannot select this player's graphics backend",error);}
            String arguments=duration==0 ? "--play" : Integer.toString(duration)+(desktop ? " --desktop-control" : "");
            // Reuse the host's normal program launcher: it hides the Wine shell,
            // sets the working directory and starts after the guest is ready.
            getIntent().putExtra("exec_path",launcher.getPath()+" "+arguments);
            getOverrideEnvVars().put("GK3HD_XR_PROTOTYPE","1");
            getOverrideEnvVars().put("GK3HD_STANDALONE_LAUNCH","1");
            // The renderer delegates enumeration to Wine's system DirectDraw.
            // Prefer our local DLL without prohibiting that builtin dependency.
            getOverrideEnvVars().put("WINEDLLOVERRIDES","ddraw=n,b");
            getOverrideEnvVars().put("DXVK_LOG_LEVEL","info");
            getOverrideEnvVars().put("DXVK_LOG_PATH","C:\\gk3hd-vr");
        }
        return true;
    }

    @Override protected void displayStarted() {
        if(BuildConfig.DEBUG&&getIntent().getBooleanExtra("gk3hd_debug_guest",false))
            com.winlator.core.ProcessHelper.addDebugCallback(guestDebug);
        int seconds=getIntent().getIntExtra("gk3hd_duration_seconds",0);
        if(seconds>0 && seconds<=720) new android.os.Handler(getMainLooper()).postDelayed(this::finish,seconds*1000L);
    }

    public final void requestRendererRecovery() {
        recordFailure(null);
    }

    @Override protected void guestExited(int status) {
        if(status!=0)recordFailure(status);
    }

    private void recordFailure(Integer guestStatus) {
        if(frameSession==null)return;
        synchronized(RendererRecovery.class) {
            SharedPreferences recovery=getSharedPreferences(RendererRecovery.PREFERENCES,MODE_PRIVATE);
            // A confirmed renderer failure takes precedence over the guest exit it caused.
            if(guestStatus!=null&&recovery.getBoolean(RendererRecovery.PENDING,false)&&
                    !recovery.contains(RendererRecovery.GUEST_EXIT_STATUS)&&
                    frameSession.equals(recovery.getString(RendererRecovery.FAILED_SESSION,null)))return;
            SharedPreferences.Editor next=recovery.edit()
                .putBoolean(RendererRecovery.PENDING,true)
                .putString(RendererRecovery.FAILED_SESSION,frameSession);
            if(guestStatus==null)next.remove(RendererRecovery.GUEST_EXIT_STATUS);
            else next.putInt(RendererRecovery.GUEST_EXIT_STATUS,guestStatus);
            next.apply();
        }
    }

    /** Only a focused game submission completes an ordinary restart. */
    public final Runnable rendererRecoveryCompletion() {
        if(!getIntent().getBooleanExtra(RendererRecovery.ORDINARY_RESTART,false))return null;
        SharedPreferences recovery=getSharedPreferences(RendererRecovery.PREFERENCES,MODE_PRIVATE);
        String attemptedFailure;
        synchronized(RendererRecovery.class) {
            if(!recovery.getBoolean(RendererRecovery.PENDING,false))return null;
            attemptedFailure=recovery.getString(RendererRecovery.FAILED_SESSION,null);
        }
        return ()->runOnUiThread(()-> {
            synchronized(RendererRecovery.class) {
                if(RendererRecovery.completes(recovery.getBoolean(RendererRecovery.PENDING,false),
                        attemptedFailure,recovery.getString(RendererRecovery.FAILED_SESSION,null))) {
                    recovery.edit().remove(RendererRecovery.PENDING).remove(RendererRecovery.FAILED_SESSION)
                        .remove(RendererRecovery.GUEST_EXIT_STATUS).apply();
                }
            }
        });
    }

    @Override protected boolean displayStartupFailed(XrPresenter.InitializationFailure error) {
        if(frameSession==null)return false;
        android.util.Log.e("GK3HDXR","Standalone presentation setup failed",error);
        requestRendererRecovery();
        return true;
    }

    @Override protected void displayRetired() {
        com.winlator.core.ProcessHelper.removeDebugCallback(guestDebug);
        if(frameMetadata!=null&&!isChangingConfigurations()) {
            File log=new File(frameMetadata.getParentFile(),"standalone-launch-error.log");
            try {
                if(RendererRecovery.reported(log,frameSession))
                    requestRendererRecovery();
                else {
                    Integer status=RendererRecovery.reportedGuestExit(log,frameSession);
                    if(status!=null)recordFailure(status);
                }
            } catch(java.io.IOException error) {
                android.util.Log.w("GK3HDGuest","Could not read the owned renderer failure report",error);
            }
        }
        // This activity owns only its random session's metadata, never saves,
        // other sessions or renderer artifacts. An interrupted guest can leave
        // this harmless 1 KiB file for later cleanup.
        if(frameMetadata!=null&&frameMetadata.isFile()&&frameMetadata.length()<=1024)frameMetadata.delete();
    }
}
