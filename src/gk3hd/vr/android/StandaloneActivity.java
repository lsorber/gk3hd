package com.winlator;

import android.app.Activity;
import android.app.AlertDialog;
import android.Manifest;
import android.content.pm.PackageManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import java.io.File;
import org.gk3hd.standalone.XrRuntimeDiscovery;
import org.gk3hd.standalone.XrRuntimeSelection;
import org.gk3hd.standalone.ComponentPairing;
import org.gk3hd.standalone.RendererRecovery;
import org.gk3hd.standalone.RuntimeAssets;
import org.gk3hd.standalone.StandaloneInstallation;

/** Single launcher entry for the prepared development player, not a file browser. */
public final class StandaloneActivity extends Activity {
    static final String EXPERIMENTAL_COMPRESSED="gk3hd_experimental_compressed";
    static final String PLAY_PROFILE="gk3hd_use_headset_profile";
    private static final String INSTALL_AGAIN=
        "Connect the headset over USB and run uvx gk3hd@latest vr standalone install on your PC.";
    private int selectedContainer;
    private XrRuntimeSelection.Backend backend;
    private boolean started,errorShown,permissionRequested;
    private boolean restartWithOrdinaryGraphics;
    static boolean prepared(Container container) {
        File player=new File(container.getRootDir(),".wine/drive_c/gk3hd-vr");
        if(!container.getExtra("gk3hdManaged").equals("1")||
           !new File(player,".gk3hd-standalone.json").isFile()) return false;
        for(String name:new String[]{"GK3-VR.exe","gk3hd-wine-launcher.exe","ddraw.dll",
                "openxr_wxr32.dll","openxr.json","launch-switches.txt","binkw32.dll","GK3.ini","dxvk.conf"})
            if(!new File(player,name).isFile()) return false;
        return true;
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        restartWithOrdinaryGraphics=state!=null&&state.getBoolean(RendererRecovery.ORDINARY_RESTART);
        if(ManagedPlayerAccess.installing()) {unavailable("GK3HD VR is still installing. Open it again when setup finishes.");return;}
        Container selected=null;
        for(Container container:new ContainerManager(this).getContainers()) {
            if("1".equals(container.getExtra("gk3hdManaged"))&&StandaloneInstallation.updatePending(container.getRootDir())) {
                unavailable("The last update was interrupted. "+INSTALL_AGAIN);return;
            }
            if(!prepared(container)) continue;
            if(selected!=null) {unavailable("More than one prepared player was found. Select its container explicitly for development.");return;}
            selected=container;
        }
        if(selected==null) {unavailable("The game files are missing or incomplete. "+INSTALL_AGAIN);return;}
        selectedContainer=selected.id;
        final File player=new File(selected.getRootDir(),".wine/drive_c/gk3hd-vr");
        android.widget.TextView status=new android.widget.TextView(this);
        status.setText("Starting GK3HD VR…");status.setTextColor(android.graphics.Color.WHITE);
        status.setBackgroundColor(android.graphics.Color.BLACK);setContentView(status);
        new Thread(()-> {
            try {
                RuntimeAssets.requireInstalled(this);
                try(java.io.InputStream pairing=getAssets().open(ComponentPairing.ASSET)) {
                    ComponentPairing.require(player,ComponentPairing.expected(pairing));
                }
            }catch(Exception failure) {
                android.util.Log.w("GK3HDXR","Standalone player verification failed",failure);
                runOnUiThread(()->unavailable("The app and game files could not be verified together. "+INSTALL_AGAIN));
                return;
            }
            try {
                XrRuntimeSelection.Backend selectedBackend=XrRuntimeDiscovery.discover(this);
                runOnUiThread(()-> {backend=selectedBackend;continueStartup();});
            }catch(Exception|LinkageError failure) {
                android.util.Log.w("GK3HDXR","Standalone VR runtime discovery failed",failure);
                runOnUiThread(()->unavailable("Could not start the headset's VR runtime. "
                    +"Restart the headset in standalone mode and try again."));
            }
        },"GK3HDVrDiscovery").start();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putBoolean(RendererRecovery.ORDINARY_RESTART,restartWithOrdinaryGraphics);
        super.onSaveInstanceState(state);
    }

    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if(code!=1) return;
        if(results.length==1 && results[0]==PackageManager.PERMISSION_GRANTED) continueStartup();
        else unavailable("Crystal tracking needs camera access. Open Settings, find GK3HD VR in "
            +"your apps, and allow Camera. GK3HD does not save or send camera images.");
    }

    private void continueStartup() {
        if(started||errorShown||backend==null||isFinishing()||isDestroyed())return;
        SharedPreferences recovery=getSharedPreferences(RendererRecovery.PREFERENCES,MODE_PRIVATE);
        if(!restartWithOrdinaryGraphics&&recovery.getBoolean(RendererRecovery.PENDING,false)) {
            Integer guestStatus=recovery.contains(RendererRecovery.GUEST_EXIT_STATUS)
                ? recovery.getInt(RendererRecovery.GUEST_EXIT_STATUS,0) : null;
            // A library launch already asks to play. Quest can hide Android dialogs
            // during this immersive handoff, and Crystal can display them rotated.
            restartWithOrdinaryGraphics=true;
            android.util.Log.w("GK3HDXR",RendererRecovery.retryMessage(guestStatus));
        }
        if(XrRuntimeSelection.needsCamera(backend)&&
                checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED) {
            // Pimax's public mobile SDK requires camera access for tracking.
            // This permission is unnecessary for the OpenXR runtime path.
            if(!permissionRequested) {permissionRequested=true;requestPermissions(new String[]{Manifest.permission.CAMERA},1);}
            return;
        }
        started=true;
        Class<?> activity=backend==XrRuntimeSelection.Backend.OPENXR?OpenXrActivity.class:CrystalActivity.class;
        // Preserve the platform's VR launch context when handing off to the
        // selected backend. A new empty intent loses Horizon's launch identity.
        startActivity(new Intent(getIntent()).setClass(this,activity)
                .putExtra("container_id",selectedContainer).putExtra("gk3hd_launch_game",true)
                .putExtra(PLAY_PROFILE,true)
                .putExtra(RendererRecovery.ORDINARY_RESTART,restartWithOrdinaryGraphics));
        finish();
    }

    private void unavailable(String message) {
        if(errorShown||started||isFinishing()||isDestroyed())return;
        errorShown=true;
        new AlertDialog.Builder(this).setTitle("GK3HD VR").setMessage(message)
                .setPositiveButton("Close",(dialog,which)->finish())
                .setOnCancelListener(dialog->finish()).show();
    }
}
