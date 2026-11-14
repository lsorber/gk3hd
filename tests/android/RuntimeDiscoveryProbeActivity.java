package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Actual runtime selection only: no permission request, game, session or poses. */
public final class RuntimeDiscoveryProbeActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh probe token required");
        new Thread(()->run(token),"GK3HDRuntimeProbe").start();
    }
    private void run(String token) {
        org.json.JSONObject result=new org.json.JSONObject();
        try {
            int first=NativeOpenXr.capabilities(getApplicationContext());
            int second=NativeOpenXr.capabilities(this);
            if(first!=second)throw new IllegalStateException("Runtime changed between discovery contexts");
            XrRuntimeSelection.Backend backend=XrRuntimeDiscovery.discover(this);
            result.put("support",first).put("backend",backend.name())
                .put("camera_required",XrRuntimeSelection.needsCamera(backend)).put("passed",true);
        }catch(Exception|LinkageError failure) {
            try {result.put("passed",false).put("error",failure.toString());}
            catch(org.json.JSONException impossible){throw new IllegalStateException(impossible);}
        }finally {
            try {
                result.put("token",token).put("scope","Capability selection only. No game, graphics session, tracking, permission request or physical presentation.");
                File output=new File(getFilesDir(),"runtime-selection-"+token+".json");
                if(!output.createNewFile())throw new IllegalStateException("Preserve earlier discovery evidence");
                try(FileOutputStream out=new FileOutputStream(output)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
            }catch(Exception failure){android.util.Log.e("GK3HDRuntimeProbe","Probe export failed",failure);}
            runOnUiThread(this::finish);
        }
    }
}
