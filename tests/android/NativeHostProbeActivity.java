package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Isolated JNI/loader initialization, without starting a game or graphics session. */
public final class NativeHostProbeActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh probe token required");
        android.widget.TextView text=new android.widget.TextView(this);text.setText("Checking native OpenXR host initialization");setContentView(text);
        new Thread(()->run(token),"GK3HDNativeHostProbe").start();
    }
    private void run(String token) {
        org.json.JSONObject result=new org.json.JSONObject();long host=0;boolean loaded=false;
        try {
            Class.forName("org.gk3hd.standalone.NativeOpenXr");loaded=true;
            host=NativeOpenXr.create(this,0,0);
            int[] size=new int[2];NativeOpenXr.dimensions(host,size);
            result.put("runtime_available",true).put("eye_width",size[0]).put("eye_height",size[1]);
        } catch(Exception|LinkageError failure) {
            try {result.put("runtime_available",false).put("error",failure.toString());}
            catch(org.json.JSONException impossible){throw new IllegalStateException(impossible);}
        } finally {
            try {
                if(host!=0)NativeOpenXr.close(host);
                result.put("token",token).put("native_library_loaded",loaded)
                    .put("scope","Instance/system discovery only, no graphics session, game, fabricated pose or controller")
                    .put("initialization_returned",true);
                File output=new File(getFilesDir(),"native-host-"+token+".json");
                if(!output.createNewFile())throw new IllegalStateException("Preserve earlier initialization evidence");
                try(FileOutputStream out=new FileOutputStream(output)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
            }catch(Exception failure){android.util.Log.e("GK3HDNativeHostProbe","Probe export/cleanup failed",failure);}
            runOnUiThread(this::finish);
        }
    }
}
