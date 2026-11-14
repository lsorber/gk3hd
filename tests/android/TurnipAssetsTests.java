package org.gk3hd.standalone;

import android.content.Context;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.json.JSONObject;

/** Isolated owned files only, never the installed compatibility runtime. */
public final class TurnipAssetsTests {
    private static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
    public static void run(Context context) throws Exception {
        File root=Files.createTempDirectory(context.getCacheDir().toPath(),"turnip-assets-test-").toFile();
        File lib=new File(root,"usr/lib");check(lib.mkdirs(),"No test library directory");
        File icd=new File(root,"usr/share/vulkan/icd.d/freedreno_icd.aarch64.json");
        check(icd.getParentFile().mkdirs(),"No test descriptor directory");
        Files.write(icd.toPath(),new byte[]{1});
        JSONObject files=new JSONObject();byte[] original=new byte[64];original[0]=42;
        StringBuilder hash=new StringBuilder();
        for(byte value:MessageDigest.getInstance("SHA-256").digest(original))
            hash.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
        for(String library:TurnipAssets.LIBRARIES) {
            Files.write(new File(lib,library).toPath(),original);
            files.put(library,new JSONObject().put("bytes",original.length).put("sha256",hash.toString()));
        }
        JSONObject description=new JSONObject().put("files",files);
        try {
            check(TurnipAssets.matches(root,description),"Complete driver rejected");
            File target=new File(lib,TurnipAssets.LIBRARIES[0]);
            Files.write(target.toPath(),new byte[3]);
            check(!TurnipAssets.matches(root,description),"Truncated driver accepted");
            byte[] changed=original.clone();changed[16]^=1;Files.write(target.toPath(),changed);
            check(!TurnipAssets.matches(root,description),"Same-size changed driver accepted");
            Files.write(target.toPath(),original);Files.delete(icd.toPath());
            check(!TurnipAssets.matches(root,description),"Missing descriptor accepted");
            Files.write(icd.toPath(),new byte[]{1});Files.delete(target.toPath());
            check(!TurnipAssets.matches(root,description),"Missing driver accepted");
            Files.createSymbolicLink(target.toPath(),icd.toPath());boolean rejected=false;
            try {TurnipAssets.matches(root,description);}catch(IllegalStateException expected) {rejected=true;}
            check(rejected,"Redirected library accepted");
            check(Files.readAllBytes(icd.toPath()).length==1,"Validation altered redirected target");
        } finally {
            for(String library:TurnipAssets.LIBRARIES)Files.deleteIfExists(new File(lib,library).toPath());
            Files.deleteIfExists(icd.toPath());Files.delete(icd.getParentFile().toPath());
            Files.delete(icd.getParentFile().getParentFile().toPath());
            Files.delete(icd.getParentFile().getParentFile().getParentFile().toPath());
            Files.delete(lib.toPath());Files.delete(lib.getParentFile().toPath());Files.delete(root.toPath());
        }
    }
}
