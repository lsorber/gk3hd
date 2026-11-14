package com.winlator;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.AtomicFile;
import android.util.Log;
import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import com.winlator.xenvironment.RootFS;
import com.winlator.xenvironment.RootFSInstaller;
import org.gk3hd.standalone.StandaloneBundle;
import org.gk3hd.standalone.StandaloneInstallation;
import org.gk3hd.standalone.SetupMetadataProvider;
import org.gk3hd.standalone.ComponentPairing;
import org.gk3hd.standalone.OwnedGuestShutdown;
import org.gk3hd.standalone.RuntimeAssets;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** ADB-authorized file import. Does not create a display or enter a VR session. */
public final class ManagedSetupService extends Service {
    private static final String CHANNEL="gk3hd-install";
    private static final int NOTIFICATION=1;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private PowerManager.WakeLock wake;
    private volatile boolean destroyed;
    private String token,lastStage="";
    private long lastProgress;
    @Override public IBinder onBind(Intent intent) {return null;}
    @Override public void onCreate() {
        super.onCreate();
        NotificationManager notifications=getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL,
            "GK3HD installation",NotificationManager.IMPORTANCE_LOW));
        startForeground(NOTIFICATION,new Notification.Builder(this,CHANNEL)
            .setSmallIcon(R.drawable.gk3hd_icon).setContentTitle("Installing GK3HD VR")
            .setContentText("Preparing private game files")
            .setCategory(Notification.CATEGORY_PROGRESS).setOngoing(true).build());
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        String requested=intent==null?null:intent.getStringExtra("gk3hd_install_id");
        String path=intent==null?null:intent.getStringExtra("gk3hd_bundle");
        String hash=intent==null?null:intent.getStringExtra("gk3hd_bundle_sha256");
        boolean recovery=intent!=null&&intent.getBooleanExtra("gk3hd_recover",false);
        if(requested==null||!requested.matches("[0-9a-f]{32}")||
           (recovery?(path!=null||hash!=null):(path==null||hash==null||!hash.matches("[0-9a-f]{64}")))) {
            Log.e("GK3HDSetup","Explicit request ID and either recovery or a verified bundle required");
            if(token==null)stopSelf(startId);
            return START_NOT_STICKY;
        }
        ManagedPlayerAccess.Lease access=token==null ? ManagedPlayerAccess.tryInstall() : null;
        if(access==null) {
            // Report the rejected request without replacing the active one's
            // atomic progress file or retiring its service/wake lock.
            if(token!=null||ManagedPlayerAccess.installing()) {
                try {Log.i("GK3HDSetup",report(requested,"failed",0,0,
                    "Another managed installation is still active").toString());}
                catch(Exception error) {Log.e("GK3HDSetup","Cannot report busy installer",error);}
            } else {
                token=requested;
                status("failed",0,0,"Close the standalone game before installing");
                stopForeground(STOP_FOREGROUND_REMOVE);stopSelf(startId);
            }
            return START_NOT_STICKY;
        }
        token=requested;
        try {
            wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                getPackageName()+":installation");
            wake.acquire(600_000L);
            worker.execute(()-> {
                try {
                    if(recovery)recover();
                    else if(BuildConfig.DEBUG&&intent.getBooleanExtra("gk3hd_test_bundle",false))runTests();
                    else install(new File(path),hash);
                } catch(Exception|LinkageError error) {
                    status("failed",0,0,error.getMessage()==null?error.getClass().getSimpleName():error.getMessage());
                } finally {
                    try {
                        if(wake!=null&&wake.isHeld())wake.release();
                        stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();
                    } finally {access.close();}
                }
            });
        } catch(RuntimeException|Error error) {
            access.close();
            if(wake!=null&&wake.isHeld())wake.release();
            throw error;
        }
        return START_NOT_STICKY;
    }
    private static Container managedContainer(ContainerManager manager) {
        Container selected=null;
        for(Container container:manager.getContainers()) {
            if(!"1".equals(container.getExtra("gk3hdManaged")))
                throw new IllegalStateException("Unmanaged container found in GK3HD app; preserve it before setup");
            if(selected!=null)throw new IllegalStateException("Multiple managed containers require review");
            selected=container;
        }
        return selected;
    }
    private void recover() throws Exception {
        OwnedGuestShutdown.requirePlayerStopped();
        Container selected=managedContainer(new ContainerManager(this));
        if(selected==null)throw new IllegalStateException("No managed player to recover");
        status("configure",0,0,"Checking the interrupted GK3HD VR update");
        StandaloneInstallation.recover(new File(selected.getRootDir(),".wine"));
        status("complete",1,1,"Previous GK3HD VR update recovered");
    }

    private void install(File bundle,String hash) throws Exception {
        OwnedGuestShutdown.requirePlayerStopped();
        status("runtime",0,0,"Preparing the private compatibility runtime");
        RuntimeAssets.install(this,new File(bundle.getParentFile(),"gk3hd-runtime-"+token+".zip"));
        RootFS root=RootFS.find(this);
        if(root.isValid()&&root.getVersion()>RootFSInstaller.LATEST_VERSION)
            throw new IllegalStateException("Newer private compatibility runtime preserved");
        if(!root.isValid()||root.getVersion()<RootFSInstaller.LATEST_VERSION) {
            if(!RootFSInstaller.installManaged(this,(done,total)->
                status("runtime",done,total,"Preparing the private compatibility runtime")))
                throw new IllegalStateException("Compatibility runtime setup did not complete");
        }
        status("verify",0,bundle.length(),"Verifying the game bundle");
        String message;
        try(StandaloneBundle extracted=StandaloneBundle.extract(bundle,getCacheDir(),hash,
                (stage,done,total)->status(stage,done,total,stage.equals("verify")?
                    "Verifying the transfer":"Installing private game files"))) {
            try(java.io.InputStream pairing=getAssets().open(ComponentPairing.ASSET)) {
                JSONObject files=extracted.manifest.getJSONObject("files");
                for(java.util.Map.Entry<String,String> entry:ComponentPairing.expected(pairing).entrySet()) {
                    if(!entry.getValue().equals(files.getJSONObject("game/"+entry.getKey()).getString("sha256")))
                        throw new IllegalStateException("Player components do not match. Prepare the game bundle with this GK3HD VR build.");
                }
            }
            ContainerManager manager=new ContainerManager(this);
            Container selected=managedContainer(manager);
            if(selected==null) {
                if(extracted.componentUpdate)
                    throw new IllegalStateException("A component update requires an existing GK3HD player");
                JSONObject config=new JSONObject();
                config.put("name","GK3HD VR");config.put("screenSize","1280x800");
                config.put("graphicsDriver","turnip,gladio");config.put("dxwrapper","wined3d");
                config.put("wincomponents",Container.FALLBACK_WINCOMPONENTS);config.put("drives","");
                status("container",0,0,"Creating an isolated game environment");
                selected=manager.createContainer(config);
                if(selected==null)throw new IllegalStateException("Cannot create the game environment");
                selected.putExtra("gk3hdManaged","1");selected.saveData();
            }
            OwnedGuestShutdown.requirePlayerStopped();
            message=StandaloneInstallation.publish(extracted,new File(selected.getRootDir(),".wine"),
                (stage,done,total)->status(stage,done,total,stage.equals("update")?
                    "Checking installed player files":"Preparing private player files"));
        }
        // Completion follows resource cleanup and durable publication.
        status("complete",1,1,message);
    }
    private void runTests() throws Exception {
        for(String name:new String[]{"StandaloneBundleTests","PrivateRuntimePathsTests",
                "NativeVulkanClientTests","TurnipAssetsTests","ContainerSettingsTests","NativeSaveFileTests"})
            Class.forName("org.gk3hd.standalone."+name).getMethod("run",android.content.Context.class).invoke(null,this);
        status("complete",1,1,"Bundle, native loader/client and container settings safety fixtures passed");
    }
    private static JSONObject report(String token,String stage,long done,long total,String message) throws Exception {
        JSONObject record=new JSONObject();record.put("token",token);record.put("stage",stage);
        record.put("completed",done);record.put("total",total);record.put("message",message);return record;
    }
    private synchronized void status(String stage,long done,long total,String message) {
        if(destroyed&&!stage.equals("failed"))
            throw new IllegalStateException("Installation service stopped before completion");
        long now=System.nanoTime();
        if(stage.equals(lastStage)&&done<total&&now-lastProgress<250_000_000L)return;
        lastStage=stage;lastProgress=now;
        try {
            String record=report(token,stage,done,total,message).toString();
            // Live status remains available if the private status file cannot be written.
            Log.i("GK3HDSetup",record);
            AtomicFile file=new AtomicFile(new File(getFilesDir(),SetupMetadataProvider.STATUS_FILE));
            java.io.FileOutputStream stream=file.startWrite();
            try {stream.write(record.getBytes(StandardCharsets.UTF_8));file.finishWrite(stream);}
            catch(Exception error) {file.failWrite(stream);throw error;}
        } catch(Exception error) {Log.e("GK3HDSetup","Cannot persist setup state",error);}
    }
    @Override public void onDestroy() {destroyed=true;worker.shutdown();super.onDestroy();}
}
