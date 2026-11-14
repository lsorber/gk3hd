package org.gk3hd.standalone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.StatFs;
import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import com.winlator.xenvironment.RootFS;
import com.winlator.xenvironment.RootFSInstaller;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.FileVisitResult;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONObject;

/** Explicit device-only cold setup, confined to one disposable cache tree. */
public final class ManagedSetupContextService extends Service {
    @Override public IBinder onBind(Intent intent) {return null;}
    private static void check(boolean value,String reason) {if(!value)throw new AssertionError(reason);}
    private static final class Isolated extends ContextWrapper {
        final File files,cache;
        final String scope;
        final Set<String> preferences=new HashSet<>();
        Isolated(Context base,File root,String token) throws Exception {
            super(base);files=new File(root,"files");cache=new File(root,"cache");
            check(files.mkdir()&&cache.mkdir(),"Cannot create isolated context");scope="gk3hd-test-"+token+"-";
        }
        @Override public File getFilesDir() {return files;}
        @Override public File getCacheDir() {return cache;}
        @Override public SharedPreferences getSharedPreferences(String name,int mode) {
            String owned=scope+name;preferences.add(owned);return super.getSharedPreferences(owned,mode);
        }
        void removePreferences() {for(String name:preferences)super.deleteSharedPreferences(name);}
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        String token=intent==null?null:intent.getStringExtra("token");
        if(token==null||!token.matches("[0-9a-f]{32}")) {stopSelf();return START_NOT_STICKY;}
        String channel="gk3hd-context-"+token;
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(channel,"GK3HD setup test",NotificationManager.IMPORTANCE_LOW));
        startForeground(2,new Notification.Builder(this,channel).setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Testing isolated GK3HD setup").setOngoing(true).build());
        PowerManager.WakeLock wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
            getPackageName()+":context-test");wake.acquire(540_000L);
        new Thread(()-> {
            JSONObject report=new JSONObject();File root=null;Isolated isolated=null;
            try {
                check(new StatFs(getCacheDir().getPath()).getAvailableBytes()>3L*1024*1024*1024,
                    "Cold test requires three GiB of device headroom");
                SharedPreferences original=android.preference.PreferenceManager.getDefaultSharedPreferences(this);
                HashMap<String,Object> before=new HashMap<>(original.getAll());
                root=Files.createTempDirectory(getCacheDir().toPath(),"gk3hd-cold-context-").toFile();
                isolated=new Isolated(this,root,token);
                final long[] progress={0,0,0};
                check(RootFSInstaller.installManaged(isolated,(done,total)-> {
                    check(done>=progress[0]&&done<=total&&total<=2L*1024*1024*1024,
                        "Runtime extraction progress/bound is invalid");
                    progress[0]=done;progress[1]=total;progress[2]++;
                }),"Cold Context-only runtime extraction failed");
                RootFS runtime=RootFS.find(isolated);
                check(runtime.isValid()&&runtime.getVersion()==RootFSInstaller.LATEST_VERSION,
                    "Cold runtime was not published as valid");
                check(progress[2]>0,"Runtime extraction never reported progress");
                ContainerManager containers=new ContainerManager(isolated);
                check(containers.getContainers().isEmpty(),"Cold fixture inherited a real container");
                Container container=containers.createContainer(new JSONObject().put("name","Isolated setup test"));
                check(container!=null,"Context-only container creation failed");
                container.putExtra("gk3hdManaged","1");container.saveData();
                File prefix=new File(container.getRootDir(),".wine");
                check(new File(prefix,"system.reg").isFile()&&new File(prefix,"user.reg").isFile(),
                    "New container has no complete registry");
                File archive=StandaloneBundleTests.zip(root,StandaloneBundleTests.files(),"");
                try(StandaloneBundle bundle=StandaloneBundle.extract(archive,isolated.getCacheDir(),
                        StandaloneBundle.hash(archive),(stage,done,total)->{})) {
                    check(StandaloneInstallation.publish(bundle,prefix,(stage,done,total)->{}).contains("installed"),
                        "Cold Context-only publisher failed");
                }
                File player=new File(prefix,"drive_c/gk3hd-vr");
                check(new File(player,".gk3hd-standalone.json").isFile(),"Cold player ownership missing");
                for(String name:StandaloneBundle.REQUIRED)check(new File(player,name).isFile(),"Cold player file missing");
                check(before.equals(original.getAll()),"Isolated runtime reset real preferences");
                report.put("success",true);report.put("runtime_bytes",progress[0]);
                report.put("progress_callbacks",progress[2]);report.put("fresh_container",true);
                report.put("tiny_non_executable_player",true);report.put("real_preferences_unchanged",true);
            } catch(Throwable error) {
                try {report.put("success",false);report.put("error",error.toString());}
                catch(Exception ignored) { }
            } finally {
                try {
                    if(isolated!=null)isolated.removePreferences();
                    if(root!=null) {
                        check(root.getCanonicalPath().startsWith(getCacheDir().getCanonicalPath()+File.separator),
                            "Refuse cleanup outside test cache");
                        Files.walkFileTree(root.toPath(),new SimpleFileVisitor<Path>() {
                            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes attrs) throws java.io.IOException {
                                Files.delete(file);return FileVisitResult.CONTINUE;
                            }
                            @Override public FileVisitResult postVisitDirectory(Path dir,java.io.IOException error) throws java.io.IOException {
                                if(error!=null)throw error;Files.delete(dir);return FileVisitResult.CONTINUE;
                            }
                        });
                    }
                    report.put("owned_fixture_removed",root==null||!root.exists());report.put("token",token);
                    Files.write(new File(getFilesDir(),"managed-context-"+token+".json").toPath(),
                        report.toString().getBytes(StandardCharsets.UTF_8));
                } catch(Exception error) {android.util.Log.e("GK3HDSetup","Context fixture cleanup/report failed",error);}
                if(wake.isHeld())wake.release();stopForeground(STOP_FOREGROUND_REMOVE);
                manager.deleteNotificationChannel(channel);stopSelf();
            }
        },"GK3HDColdSetupTest").start();
        return START_NOT_STICKY;
    }
}
