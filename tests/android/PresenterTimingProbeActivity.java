package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;
import org.json.JSONObject;

/** Isolated synthetic observer data. Never starts a game, graphics or XR session. */
public final class PresenterTimingProbeActivity extends Activity {
    private static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
    private static final class Source implements XrPresenter.Source {
        public boolean hasStereoFrame(){return true;}
        public void onSurfaceCreated(GL10 gl,EGLConfig config){}
        public void onSurfaceChanged(GL10 gl,int width,int height){}
        public void onDrawFrame(GL10 gl){}
        public long[] snapshotFrameEvents(Integer id) {
            long[] data=new long[17];for(int i=0;i<data.length;i++)data[i]=100+i;return data;
        }
    }
    private JSONObject read() throws Exception {
        return new JSONObject(new String(java.nio.file.Files.readAllBytes(
            new File(getFilesDir(),"native-presenter-timing.json").toPath()),StandardCharsets.UTF_8));
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Fresh probe token required");
        getIntent().putExtra("gk3hd_observation_token",token).putExtra("gk3hd_xr_presenter","openxr");
        JSONObject result=new JSONObject();
        try {
            NativeFrameTiming observer=new NativeFrameTiming(this);Source source=new Source();
            long[] times={1000,1100,1200,1300,1500,1600,1600,1600,1800};
            observer.sampled(11,1150,3);
            observer.nativeFrame(0,1,7,900000000L,11111111L,3,true,true,1350,1450,11);
            observer.frame(source,0,11,31,times,false);
            observer.checkpoint();JSONObject first=read();
            check(first.getInt("schema")==3&&!first.getBoolean("closed")&&first.getInt("checkpoint")==1,"Pause checkpoint closed the collector");
            check(first.getJSONArray("frames").length()==1&&first.getJSONArray("native_frames").length()==1,"First native timeline missing");
            check(first.getJSONArray("frames").getJSONArray(0).getLong(3)==1150,"Selected image sampling time lost");
            check(first.getJSONArray("frames").getJSONArray(0).getLong(30)==116,"Exact-image diagnostics lost");
            check(first.getJSONArray("native_frames").getJSONArray(0).getLong(8)==1350,"Ownership wait timing lost");
            String other=token.charAt(0)=='0'?"1"+token.substring(1):"0"+token.substring(1);
            getIntent().putExtra("gk3hd_observation_token",other);
            NativeFrameTiming intruder=new NativeFrameTiming(this);boolean ownershipRejected=false;
            try {intruder.checkpoint();}catch(java.io.IOException expected){ownershipRejected=true;}
            check(ownershipRejected&&read().getString("token").equals(token),"Another observation overwrote preserved timing evidence");
            getIntent().putExtra("gk3hd_observation_token",token);
            long[] bad=times.clone();bad[3]=1;
            boolean rejected=false;
            try {observer.frame(source,1,11,31,bad,false);}catch(IllegalStateException expected){rejected=true;}
            check(rejected,"Invalid clock order accepted");
            rejected=false;
            try {observer.nativeFrame(1,2,8,1,1,3,true,true,30,20,12);}catch(IllegalArgumentException expected){rejected=true;}
            check(rejected,"Invalid ownership timing accepted");
            observer.sampled(12,2150,3);
            for(int i=0;i<times.length;i++)times[i]+=1000;
            observer.nativeFrame(1,2,8,911111111L,11111111L,3,true,false,2350,2450,12);
            observer.frame(source,1,12,32,times,false);observer.checkpoint();
            JSONObject resumed=read();
            check(!resumed.getBoolean("closed")&&resumed.getJSONArray("frames").length()==2,"Resume lost the second frame or earlier evidence");
            check(resumed.getJSONArray("native_frames").getJSONArray(1).getLong(2)==8,"Coordinate epoch lost");
            check(resumed.getJSONArray("native_frames").getJSONArray(1).getLong(7)==0,"Actual focus state changed");
            for(int i=0;i<300;i++)observer.sampled(100+i,10_000_000L+i*10_000_000L,3);
            for(int i=0;i<times.length;i++)times[i]+=4_000_000_000L;
            observer.frame(source,2,12,32,times,false);
            observer.close();JSONObject complete=read();
            check(complete.getJSONArray("frames").getJSONArray(2).getLong(3)==2150,
                "Held image lost or refreshed its original sampling time after history eviction");
            check(complete.getBoolean("closed")&&complete.getInt("checkpoint")==3,"Final export not distinguished from pause");
            check(complete.getString("backend").equals("openxr")&&complete.getString("token").equals(token),"Backend or observation identity lost");
            check(complete.getJSONArray("native_frames").getJSONArray(1).getLong(10)==12,"Generated pose/native timing join lost");
            java.nio.file.Files.copy(new File(getFilesDir(),"native-presenter-timing.json").toPath(),
                new File(getFilesDir(),"observer-openxr-"+token+".json").toPath());
            observer.frame(source,2,12,32,times,false);
            observer.close();check(read().getInt("checkpoint")==3,"Closed observation mutated");
            getIntent().removeExtra("gk3hd_xr_presenter");
            NativeFrameTiming vendor=new NativeFrameTiming(this);
            long crystalSample=times[2];
            vendor.sampled(12,crystalSample,15);
            vendor.frame(source,0,12,32,times,true);
            vendor.crystalSubmission(0,1,5,15,true,2,false);
            for(int i=0;i<times.length;i++)times[i]+=11_000_000;
            vendor.frame(source,1,12,32,times,false);
            vendor.crystalSubmission(1,2,5,15,true,2,true);
            for(int i=0;i<times.length;i++)times[i]+=22_000_000;
            vendor.frame(source,2,null,0,times,true);
            vendor.crystalSubmission(2,4,7,5,false,0,false);
            vendor.close();
            JSONObject crystal=read();
            check(crystal.getString("backend").equals("pimax"),"Vendor route mislabeled");
            org.json.JSONArray outputs=crystal.getJSONArray("crystal_submissions");
            check(outputs.length()==3,"Crystal submissions do not match the timing rows");
            org.json.JSONArray repeat=outputs.getJSONArray(1);
            check(repeat.getLong(0)==1&&repeat.getLong(1)==2&&repeat.getLong(2)==5&&
                repeat.getInt(3)==15&&repeat.getInt(4)==1&&repeat.getInt(5)==2&&repeat.getInt(6)==1,
                "Repeated output lost its focus, draw or slot identity");
            check(crystal.getJSONArray("frames").getJSONArray(1).getLong(3)==crystalSample,
                "Repeated Crystal output refreshed the original pose time");
            org.json.JSONArray interrupted=outputs.getJSONArray(2);
            check(interrupted.getLong(1)==4&&interrupted.getLong(2)==7&&interrupted.getInt(3)==5&&
                interrupted.getInt(4)==0&&interrupted.getInt(6)==0,"Crystal interruption evidence was lost");
            result.put("passed",true).put("checked_frames",3).put("checkpoints",3);
        }catch(Exception|AssertionError failure) {
            try {result.put("passed",false).put("error",failure.toString());}
            catch(org.json.JSONException impossible){throw new IllegalStateException(impossible);}
        }finally {
            try {
                result.put("token",token).put("scope","Synthetic observer/JSON/lifecycle data only. No game, graphics, XR session, headset tracking or measured performance.");
                File output=new File(getFilesDir(),"presenter-timing-"+token+".json");
                if(!output.createNewFile())throw new IllegalStateException("Preserve earlier probe result");
                try(FileOutputStream out=new FileOutputStream(output)){out.write(result.toString().getBytes(StandardCharsets.UTF_8));}
            }catch(Exception failure){android.util.Log.e("GK3HDTimingProbe","Probe export failed",failure);}
            finish();
        }
    }
}
