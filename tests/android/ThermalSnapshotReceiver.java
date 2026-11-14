package org.gk3hd.standalone;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.os.PowerManager;
import android.os.SystemClock;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import org.json.JSONObject;

/** Debug-only, read-only system query. Never overrides thermal/power settings. */
public final class ThermalSnapshotReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent) {
        String token=intent.getStringExtra("gk3hd_probe_token");
        if(token==null||!token.matches("[a-f0-9]{32}"))return;
        try {
            PowerManager power=context.getSystemService(PowerManager.class);
            Intent battery=context.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if(power==null||battery==null)throw new IllegalStateException("Missing system health data");
            JSONObject report=new JSONObject().put("token",token).put("elapsed_realtime_ms",SystemClock.elapsedRealtime())
                .put("sdk",Build.VERSION.SDK_INT).put("battery_level",battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1))
                .put("battery_scale",battery.getIntExtra(BatteryManager.EXTRA_SCALE,-1))
                .put("battery_health",battery.getIntExtra(BatteryManager.EXTRA_HEALTH,-1))
                .put("battery_temperature_tenths_c",battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1))
                .put("scope","Read-only health snapshot; no display, GPU, game or system-setting changes");
            report.put("thermal_status",Build.VERSION.SDK_INT>=29?power.getCurrentThermalStatus():JSONObject.NULL);
            float headroom=Float.NaN;
            if(Build.VERSION.SDK_INT>=30) {
                try {headroom=power.getThermalHeadroom(0);}
                catch(RuntimeException unsupported){report.put("headroom_error",unsupported.getClass().getName());}
            }
            report.put("thermal_headroom_0s",Float.isFinite(headroom)?headroom:JSONObject.NULL);
            File output=new File(context.getFilesDir(),"thermal-"+token+".json");
            File pending=new File(context.getFilesDir(),"thermal-"+token+".tmp");
            if(output.exists())throw new IllegalStateException("Preserve existing health evidence");
            Files.write(pending.toPath(),report.toString().getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
            Files.move(pending.toPath(),output.toPath(),StandardCopyOption.ATOMIC_MOVE);
        } catch(Exception failure) {android.util.Log.e("GK3HDXR","Read-only thermal query failed",failure);}
    }
}
