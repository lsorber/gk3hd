package com.winlator;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;
import org.gk3hd.standalone.FixtureReport;
import org.gk3hd.standalone.NativeGameFlow;

/** Debug-only source benchmark, separate from headset compositor qualification. */
public final class OffHeadDisplayService extends Service {
    private static OffHeadDisplayService owner;
    private java.lang.ref.WeakReference<Activity> gameActivity=new java.lang.ref.WeakReference<>(null);
    private final Handler main=new Handler(android.os.Looper.getMainLooper());
    private HandlerThread consumer;
    private ImageReader reader;
    private VirtualDisplay display;
    private PowerManager.WakeLock wake;
    private String token;
    private String endReason="activity-destroyed";
    private volatile boolean closing;
    @Override public IBinder onBind(Intent intent) {return null;}
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        try {
            NotificationManager notices=getSystemService(NotificationManager.class);
            notices.createNotificationChannel(new NotificationChannel("gk3hd-gpu-test","GK3HD GPU test",NotificationManager.IMPORTANCE_LOW));
            startForeground(7401,new Notification.Builder(this,"gk3hd-gpu-test")
                .setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("GK3HD source test")
                .setContentText("Off-head source test, no VR compositor").setOngoing(true).build());
            if(intent==null||display!=null)throw new IllegalArgumentException("One owned private-display run required");
            token=intent.getStringExtra("gk3hd_observation_token");
            if(token==null)token=java.util.UUID.randomUUID().toString().replace("-","");
            intent.putExtra("gk3hd_observation_token",token);
            int seconds=intent.getIntExtra("gk3hd_duration_seconds",105);
            int soakSeconds=intent.getIntExtra("gk3hd_test_exploration_soak_seconds",0);
            new org.gk3hd.standalone.ExplorationSoak(soakSeconds);
            if(soakSeconds!=0&&(!"benchmark".equals(intent.getStringExtra("gk3hd_scenario"))||
                    !intent.getBooleanExtra("gk3hd_test_world_motion",false)))
                throw new IllegalArgumentException("Exploration soak requires moving world input");
            boolean longTravel=intent.getBooleanExtra("gk3hd_test_long_travel",false);
            if(longTravel&&(!"benchmark".equals(intent.getStringExtra("gk3hd_scenario"))||
                    !intent.getBooleanExtra("gk3hd_test_world_motion",false)||
                    !intent.getBooleanExtra("gk3hd_test_restore_cycles",false)))
                throw new IllegalArgumentException("Long travel requires the bounded multi-Restore fixture");
            if(token==null||!token.matches("[a-f0-9]{32}")||seconds<10||
                    seconds>120+soakSeconds+NativeGameFlow.titleIntroAllowance(intent)+(longTravel?24:0))
                throw new IllegalArgumentException("Bounded owned observation required");
            wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"GK3HD:source-test");
            wake.acquire((seconds+5)*1000L);
            consumer=new HandlerThread("GK3HDTestDisplay");consumer.start();
            String route=intent.getStringExtra("gk3hd_test_display_route");
            if(route==null)route="private";
            if(!route.equals("private")&&!route.equals("platform-2d"))
                throw new IllegalArgumentException("Unknown off-head display route");
            if(route.equals("private")) {
            reader=ImageReader.newInstance(1280,800,PixelFormat.RGBA_8888,2);
            reader.setOnImageAvailableListener(input->{
                try(Image image=input.acquireLatestImage()) { /* Retire without mapping/copying pixels. */ }
                catch(IllegalStateException error) {if(!closing)Log.e("GK3HDXR","Private display consumer failed",error);}
            },new Handler(consumer.getLooper()));
            display=getSystemService(DisplayManager.class).createVirtualDisplay("GK3HD test "+token,
                1280,800,160,reader.getSurface(),DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY|DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION);
            if(display==null)throw new IllegalStateException("Private display unavailable");
            }
            owner=this;
            Intent game=new Intent(this,OffHeadGameActivity.class);
            game.putExtras(intent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
            int displayId=display==null ? -1 : display.getDisplay().getDisplayId();
            if(display!=null)game.putExtra("gk3hd_private_display_id",displayId);
            Log.i("GK3HDXR","Off-head source route="+route+" requested display="+displayId+" token="+token);
            // The shell controller launches the Activity on this exact display.
            // A background service cannot start it reliably on Android 10.
            java.io.File handoff=new java.io.File(getFilesDir(),"private-display-launch-"+token+".json");
            if(handoff.exists())throw new IllegalStateException("Preserve existing display handoff");
            org.json.JSONObject launchInfo=new org.json.JSONObject().put("token",token)
                .put("display_id",displayId).put("route",route).put("intent_uri",game.toUri(Intent.URI_INTENT_SCHEME));
            FixtureReport.write(handoff,launchInfo.toString());
            final java.io.File flow=new java.io.File(getFilesDir(),"standalone-flow-"+token+".json");
            com.winlator.container.Container container=new com.winlator.container.ContainerManager(this)
                .getContainerById(intent.getIntExtra("container_id",0));
            if(container==null||flow.exists())throw new IllegalStateException("Preserve ambiguous private-display observation");
            final java.io.File launch=new java.io.File(container.getRootDir(),".wine/drive_c/gk3hd-vr/standalone-launch.log");
            main.postDelayed(new Runnable() {public void run() {
                if(closing)return;
                try {
                    if(flow.isFile()&&flow.length()<65536&&launch.isFile()&&launch.length()<262144) {
                        org.json.JSONObject current=new org.json.JSONObject(new String(java.nio.file.Files.readAllBytes(flow.toPath()),java.nio.charset.StandardCharsets.UTF_8));
                        if(token.equals(current.optString("token"))&&current.optBoolean("native_quit_requested")&&
                                new String(java.nio.file.Files.readAllBytes(launch.toPath()),java.nio.charset.StandardCharsets.UTF_8).contains("Owned child exit=0")) {
                            endReason="native-quit";
                            Activity activity=gameActivity.get();
                            if(activity==null)throw new IllegalStateException("Owned test Activity missing at native Quit");
                            activity.finish();return;
                        }
                    }
                } catch(Exception error) {Log.e("GK3HDXR","Private display completion observation failed",error);}
                main.postDelayed(this,500);
            }},500);
            main.postDelayed(()-> {endReason="deadline";Log.e("GK3HDXR","Private display deadline reached token="+token);stopSelf();},seconds*1000L);
        } catch(Exception failure) {Log.e("GK3HDXR","Private source display failed",failure);stopSelf();}
        return START_NOT_STICKY;
    }
    static void gameStarted(Activity activity) {
        OffHeadDisplayService service=owner;
        if(service!=null&&service.token.equals(activity.getIntent().getStringExtra("gk3hd_observation_token")))
            service.gameActivity=new java.lang.ref.WeakReference<>(activity);
    }
    static void gameClosed(Activity activity) {
        OffHeadDisplayService service=owner;
        Log.i("GK3HDXR","Off-head gameClosed identity="+System.identityHashCode(activity)+
            " owner="+(service==null ? "absent" : System.identityHashCode(service.gameActivity.get()))+
            " changing="+activity.isChangingConfigurations()+" finishing="+activity.isFinishing());
        if(service!=null&&
                service.token.equals(activity.getIntent().getStringExtra("gk3hd_observation_token"))&&
                (service.display==null||activityDisplay(activity)==service.display.getDisplay().getDisplayId()))
            service.stopSelf();
    }
    static int activityDisplay(Activity activity) {
        if(android.os.Build.VERSION.SDK_INT>=30) {
            android.view.Display current=activity.getDisplay();
            if(current==null)throw new IllegalStateException("Activity display unavailable");
            return current.getDisplayId();
        }
        if(android.os.Build.VERSION.SDK_INT>=29) {
            for(android.app.ActivityManager.AppTask task:activity.getSystemService(android.app.ActivityManager.class).getAppTasks()) {
                android.app.ActivityManager.RecentTaskInfo info=task.getTaskInfo();
                if(info.taskId==activity.getTaskId()) {
                    // Android 10 hides TaskInfo.displayId from the public SDK.
                    // Its public diagnostic text includes the actual task display,
                    // unlike a locale-wrapped Activity's default-display context.
                    // Test workbench only: reject unknown platform formats.
                    java.util.regex.Matcher match=java.util.regex.Pattern.compile(
                        "^TaskInfo\\{userId=\\d+ stackId=-?\\d+ taskId="+info.taskId+" displayId=(\\d+) ")
                        .matcher(info.toString());
                    if(match.find())return Integer.parseInt(match.group(1));
                    throw new IllegalStateException("Unsupported task display diagnostic: "+info);
                }
            }
            throw new IllegalStateException("Current Activity task not found");
        }
        return activity.getWindowManager().getDefaultDisplay().getDisplayId();
    }
    @Override public void onDestroy() {
        Log.i("GK3HDXR","Off-head service destroy reason="+endReason);
        closing=true;main.removeCallbacksAndMessages(null);
        Activity activity=gameActivity.get();
        if(activity!=null&&!activity.isFinishing())activity.finish();
        gameActivity.clear();
        if(owner==this)owner=null;
        if(display!=null){display.release();display=null;}
        if(reader!=null){reader.close();reader=null;}
        if(consumer!=null){consumer.quitSafely();consumer=null;}
        if(wake!=null&&wake.isHeld())wake.release();
        Log.i("GK3HDXR","Private source display retired token="+token+" reason="+endReason);
        stopForeground(true);
        super.onDestroy();
    }
}
