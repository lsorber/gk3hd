package org.gk3hd.standalone;

import android.app.Activity;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Execute a hash-selected private driver diagnostic in the actual app domain. */
final class NativeDriverProbe {
    static JSONObject run(Activity activity,String token) throws Exception {
        String expected=activity.getIntent().getStringExtra("probe_sha256");
        if(expected==null||!expected.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("Select the exact diagnostic binary");
        File executable=new File(activity.getFilesDir(),"driver-probe-"+token);
        if(!executable.isFile()||executable.length()>131072||
            !StandaloneBundle.hash(executable).equals(expected)||!executable.setExecutable(true,true))
            throw new IllegalArgumentException("Missing or changed private diagnostic");
        File lib=new File(activity.getFilesDir(),"rootfs/usr/lib"),driver=new File(lib,"libvulkan_freedreno.so");
        File output=new File(activity.getFilesDir(),"driver-probe-"+token+".txt");
        if(!output.createNewFile())throw new IllegalStateException("Preserve diagnostic output");
        ProcessBuilder command=new ProcessBuilder(new File(lib,"ld-linux-aarch64.so.1").getPath(),
            "--library-path",lib.getPath(),executable.getPath(),driver.getPath());
        command.environment().put("LD_LIBRARY_PATH",lib.getPath());
        File allocation=null;
        if(activity.getIntent().getBooleanExtra("allocation_compat",false)) {
            allocation=GpuAllocationCompat.prepare(activity);
            command.environment().put("LD_PRELOAD",allocation.getCanonicalPath());
        }
        Process process=command.redirectErrorStream(true).redirectOutput(output).start();
        if(!process.waitFor(10,TimeUnit.SECONDS)) {
            process.destroyForcibly();
            if(!process.waitFor(2,TimeUnit.SECONDS))throw new IllegalStateException("Owned driver diagnostic did not retire");
            throw new IllegalStateException("Driver diagnostic deadline");
        }
        if(output.length()>65536)throw new IllegalStateException("Driver diagnostic output exceeded its bound");
        String text=new String(Files.readAllBytes(output.toPath()),StandardCharsets.UTF_8);
        JSONObject result=new JSONObject().put("token",token).put("mode","driver")
            .put("probe_sha256",expected).put("driver_sha256",StandaloneBundle.hash(driver))
            .put("parent_domain",new String(Files.readAllBytes(new File("/proc/self/attr/current").toPath()),StandardCharsets.UTF_8).trim())
            .put("exit_code",process.exitValue()).put("output",text)
            .put("scope","App-domain logical-device diagnostic, no game or headset session");
        if(allocation!=null)result.put("allocation_sha256",StandaloneBundle.hash(allocation));
        for(String line:text.split("\n"))if(line.startsWith("{\"instance_result\":"))result.put("device",new JSONObject(line));
        result.put("passed",process.exitValue()==0&&result.has("device")&&result.getJSONObject("device").optInt("device_result",-1)==0);
        return result;
    }
}
