package org.gk3hd.standalone;

import android.content.Context;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONObject;

/** Verified APK asset and tiny private cache only. No installed game/driver edits. */
public final class NativeVulkanClientTests {
    private static void check(boolean value,String reason) {if(!value) throw new AssertionError(reason);}
    private interface Attempt {void run() throws Exception;}
    private static void reject(Attempt attempt) throws Exception {
        boolean rejected=false;try {attempt.run();} catch(IllegalArgumentException|IllegalStateException expected) {rejected=true;}
        check(rejected,"Unsafe native client input was accepted");
    }
    public static void run(Context context) throws Exception {
        android.content.Intent options=new android.content.Intent();
        check(NativeVulkan.stereoOnlyWaits(options),"Ordinary XR waits for an unconsumed mono mirror");
        options.putExtra("gk3hd_capture_guest",true);
        check(!NativeVulkan.stereoOnlyWaits(options),"Desktop capture lost its publication ordering");
        options.putExtra("gk3hd_test_native_stereo_only",true);
        check(NativeVulkan.stereoOnlyWaits(options),"Explicit debug wait control was ignored");
        options.putExtra("gk3hd_test_native_stereo_only",false).putExtra("gk3hd_capture_guest",false);
        check(!NativeVulkan.stereoOnlyWaits(options),"Conservative debug wait control was ignored");
        byte[] archive;
        try(InputStream input=context.getAssets().open(NativeVulkanClient.ASSET)) {archive=NativeVulkanClient.read(input,1024*1024);}
        File cache=Files.createTempDirectory(context.getCacheDir().toPath(),"native-vulkan-test-").toFile();
        String alias="/data/data/org.gk3hd.standalone/root";
        try {
            File manifest=NativeVulkanClient.prepare(cache,archive,alias);
            byte[] description=Files.readAllBytes(manifest.toPath());
            JSONObject icd=new JSONObject(new String(description,StandardCharsets.UTF_8));
            File client=new File(icd.getJSONObject("ICD").getString("library_path"));
            check(client.getCanonicalFile().getParentFile().equals(cache.getCanonicalFile()),"Client escaped private cache");
            byte[] expected=NativeVulkanClient.extract(archive);
            check(PrivateRuntimePaths.relocateBytes(expected,"/data/data/com.winlator/files/rootfs",alias),"No native client path relocation");
            check(Arrays.equals(expected,Files.readAllBytes(client.toPath())),"Cached client differs from relocated pinned asset");
            long modified=client.lastModified();
            check(NativeVulkanClient.prepare(cache,archive,alias).equals(manifest)&&cache.list().length==2&&client.lastModified()==modified,
                "Repeated launch replaced/duplicated the native client");
            byte[] damaged=archive.clone();damaged[0]^=1;
            reject(()->NativeVulkanClient.prepare(cache,damaged,alias));
            check(Arrays.equals(expected,Files.readAllBytes(client.toPath())),"Rejected archive altered valid cache");
            reject(()->NativeVulkanClient.prepare(cache,archive,"/wrong/width"));
            byte[] edited={1,2,3};Files.write(client.toPath(),edited);
            reject(()->NativeVulkanClient.prepare(cache,archive,alias));
            check(Arrays.equals(edited,Files.readAllBytes(client.toPath()))&&Arrays.equals(description,Files.readAllBytes(manifest.toPath())),
                "Modified cached files were overwritten");
            Files.delete(client.toPath());Files.createSymbolicLink(client.toPath(),manifest.toPath());
            reject(()->NativeVulkanClient.prepare(cache,archive,alias));
            check(Arrays.equals(description,Files.readAllBytes(manifest.toPath())),"Redirected cache altered its target");
        } finally {
            File[] files=cache.listFiles();if(files!=null) for(File file:files) Files.deleteIfExists(file.toPath());
            Files.deleteIfExists(cache.toPath());
        }
    }
}
