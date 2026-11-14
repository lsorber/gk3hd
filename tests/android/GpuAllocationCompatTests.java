package org.gk3hd.standalone;

import android.app.Activity;
import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.util.Arrays;

/** APK-owned extraction and conflict preservation, with no GPU or game. */
final class GpuAllocationCompatTests {
    static void run(Activity activity) throws Exception {
        byte[] asset;
        try(InputStream input=activity.getAssets().open("graphics_driver/libgk3hd_kgsl.so")) {
            asset=NativeVulkanClient.read(input,1024*1024);
        }
        File root=Files.createTempDirectory(activity.getCacheDir().toPath(),"allocation-check-").toFile();
        byte[] wrong=asset.clone();wrong[wrong.length-1]^=1;
        try {GpuAllocationCompat.prepare(new File(root,"bad-input"),wrong);throw new AssertionError("Wrong APK input accepted");}
        catch(IllegalStateException expected) { }
        if(new File(root,"bad-input").exists())throw new AssertionError("Invalid input created cache output");
        File directory=new File(root,"valid");
        File library=GpuAllocationCompat.prepare(directory,asset);
        long modified=library.lastModified();
        if(!Arrays.equals(Files.readAllBytes(library.toPath()),asset))throw new AssertionError("Published allocation bytes differ");
        if(!GpuAllocationCompat.prepare(directory,asset).equals(library)||library.lastModified()!=modified)
            throw new AssertionError("Identical preparation replaced the library");
        Files.write(library.toPath(),wrong);
        try {GpuAllocationCompat.prepare(directory,asset);throw new AssertionError("Changed cache accepted");}
        catch(IllegalStateException expected) { }
        if(!Arrays.equals(Files.readAllBytes(library.toPath()),wrong))throw new AssertionError("Changed cache overwritten");
        if(!library.delete()||!directory.delete()||!root.delete())throw new AssertionError("Owned fixture cleanup failed");
        String first=GpuAllocationCompat.preload(activity,"");
        int policy=GpuAllocationCompat.legacyAllocationPolicy();
        if(policy<0||policy==0&&!first.isEmpty()||policy==1&&first.isEmpty())
            throw new AssertionError("Preload selection disagrees with the actual kernel API");
        if(!GpuAllocationCompat.preload(activity,first).equals(first))throw new AssertionError("Repeated preload duplicated");
        if(!GpuAllocationCompat.preload(activity,"custom.so").equals(first.isEmpty() ? "custom.so" : first+":custom.so"))
            throw new AssertionError("Existing preload lost");
    }
}
