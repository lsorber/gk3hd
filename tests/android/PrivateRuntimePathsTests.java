package org.gk3hd.standalone;

import android.content.Context;
import android.system.Os;
import android.util.AtomicFile;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

/** App-owned directory identity and synthetic ELF/audio relocation checks. */
public final class PrivateRuntimePathsTests {
    public static void run(Context context) throws Exception {
        File file=Files.createTempFile(context.getCacheDir().toPath(),"gk3hd-path-test-",".bin").toFile();
        try {
            byte[] fixture="\177ELFprefix/old/root/lib/loader\0other/old/root/tmp/.wine-123\0end".getBytes(StandardCharsets.US_ASCII);
            Files.write(file.toPath(),fixture);
            if(!PrivateRuntimePaths.relocate(file,"/old/root","/new/root")) throw new AssertionError("No relocation");
            byte[] changed=Files.readAllBytes(file.toPath());
            byte[] expected=new String(fixture,StandardCharsets.US_ASCII).replace("/old/root","/new/root").getBytes(StandardCharsets.US_ASCII);
            if(!Arrays.equals(changed,expected)||changed.length!=fixture.length) throw new AssertionError("Native file layout changed");
            if(PrivateRuntimePaths.relocate(file,"/old/root","/new/root")) throw new AssertionError("Not idempotent");
            boolean rejected=false;
            try {PrivateRuntimePaths.relocate(file,"/old/root","/longer/root");}catch(IllegalArgumentException error) {rejected=true;}
            if(!rejected||!Arrays.equals(changed,Files.readAllBytes(file.toPath()))) throw new AssertionError("Unequal width accepted or altered data");
            Files.write(file.toPath(),new byte[]{1,2,3,4});rejected=false;
            try {PrivateRuntimePaths.relocate(file,"/old/root","/new/root");}catch(IllegalArgumentException error) {rejected=true;}
            if(!rejected) throw new AssertionError("Non-ELF data accepted");
        } finally {Files.deleteIfExists(file.toPath());}
        audio(context);
        ownership(context);
        wine(context);
    }
    private static void wine(Context context) throws Exception {
        File source=new File(context.getFilesDir(),"rootfs/opt/wine/lib/wine/i386-windows/wined3d.dll");
        byte[] original=Files.readAllBytes(source.toPath());
        File root=Files.createTempDirectory(context.getCacheDir().toPath(),"gk3hd-wine-test-").toFile();
        File file=new File(root,"opt/wine/lib/wine/i386-windows/wined3d.dll");
        try {
            Files.createDirectories(file.getParentFile().toPath());Files.write(file.toPath(),original);
            Os.chmod(file.getPath(),0740);
            PrivateRuntimePaths.prepareWineMapCompletion(root);
            byte[] ready=Files.readAllBytes(file.toPath());
            if(WineMapCompletion.apply(ready)!=ready||(Os.stat(file.getPath()).st_mode&0777)!=0740)
                throw new AssertionError("Prepared runtime or permissions differ");
            if(PrivateRuntimePaths.prepareWineMapCompletion(root))
                throw new AssertionError("Prepared Wine runtime was rewritten");
            // Simulate interruption after staging bytes but before publication.
            AtomicFile atomic=new AtomicFile(file);
            java.io.FileOutputStream interrupted=atomic.startWrite();
            interrupted.write(new byte[]{1,2,3});interrupted.close();
            if(PrivateRuntimePaths.prepareWineMapCompletion(root)||
                    !Arrays.equals(ready,Files.readAllBytes(file.toPath())))
                throw new AssertionError("Interrupted publication did not recover the accepted runtime");
            byte[] unknown=ready.clone();unknown[unknown.length-1]^=1;Files.write(file.toPath(),unknown);
            boolean rejected=false;
            try {PrivateRuntimePaths.prepareWineMapCompletion(root);}
            catch(IllegalStateException expected) {rejected=true;}
            if(!rejected||!Arrays.equals(unknown,Files.readAllBytes(file.toPath())))
                throw new AssertionError("Unknown runtime was overwritten");
            Files.delete(file.toPath());Os.symlink(source.getPath(),file.getPath());rejected=false;
            try {PrivateRuntimePaths.prepareWineMapCompletion(root);}
            catch(IllegalStateException expected) {rejected=true;}
            if(!rejected||!Arrays.equals(original,Files.readAllBytes(source.toPath())))
                throw new AssertionError("External runtime link was accepted or its source changed");
        } finally {
            Files.deleteIfExists(file.toPath());
            // These are bounded, exclusively test-owned directories, not rootfs.
            try(java.util.stream.Stream<java.nio.file.Path> paths=Files.walk(root.toPath())) {
                java.util.List<java.nio.file.Path> owned=new java.util.ArrayList<>();
                paths.forEach(owned::add);owned.sort(java.util.Comparator.reverseOrder());
                for(java.nio.file.Path path:owned)Files.deleteIfExists(path);
            }
        }
    }
    private static void ownership(Context context) throws Exception {
        File root=new File(context.getFilesDir(),"rootfs");
        File alias=PrivateRuntimePaths.alias(context,root);
        if(!Files.isSameFile(alias.toPath(),root.toPath())||
           !PrivateRuntimePaths.alias(context,root).equals(alias))
            throw new AssertionError("Private runtime alias lost directory identity");
        File other=Files.createTempDirectory(context.getCacheDir().toPath(),"gk3hd-other-root-").toFile();
        try {
            boolean rejected=false;
            try {PrivateRuntimePaths.alias(context,other);}catch(IllegalArgumentException error) {rejected=true;}
            if(!rejected||!other.isDirectory()||!Files.isSameFile(alias.toPath(),root.toPath()))
                throw new AssertionError("Unowned runtime accepted or existing data changed");
        } finally {Files.delete(other.toPath());}
    }
    private static void audio(Context context) throws Exception {
        File root=Files.createTempDirectory(context.getCacheDir().toPath(),"gk3hd-audio-test-").toFile();
        File config=new File(root,"usr/share/alsa/alsa.conf");
        File server=new File(root,"etc/alsa/conf.d/android_aserver.conf");
        try {
            Files.createDirectories(config.getParentFile().toPath());Files.createDirectories(server.getParentFile().toPath());
            Files.write(server.toPath(),"pcm.!default { type android_aserver }".getBytes(StandardCharsets.UTF_8));
            String hook="@hooks [{ func load files [\"/data/data/com.winlator/files/rootfs/etc/alsa/conf.d/android_aserver.conf\"] errors false }]\n# preserved\n";
            Files.write(config.toPath(),hook.getBytes(StandardCharsets.UTF_8));
            if(!PrivateRuntimePaths.relocateAudioConfig(root)) throw new AssertionError("Audio hook was not relocated");
            byte[] expected=hook.replace("/data/data/com.winlator/files/rootfs/etc/alsa/conf.d/android_aserver.conf",server.getPath()).getBytes(StandardCharsets.UTF_8);
            if(!Arrays.equals(expected,Files.readAllBytes(config.toPath()))) throw new AssertionError("Unrelated audio configuration changed");
            if(PrivateRuntimePaths.relocateAudioConfig(root)) throw new AssertionError("Audio relocation is not idempotent");
            byte[] large=new byte[65537];Arrays.fill(large,(byte)'x');Files.write(config.toPath(),large);
            boolean rejected=false;
            try {PrivateRuntimePaths.relocateAudioConfig(root);}catch(IllegalStateException error) {rejected=true;}
            if(!rejected||!Arrays.equals(large,Files.readAllBytes(config.toPath()))) throw new AssertionError("Oversized audio data not preserved");
            Files.delete(server.toPath());rejected=false;
            try {PrivateRuntimePaths.relocateAudioConfig(root);}catch(IllegalStateException error) {rejected=true;}
            if(!rejected) throw new AssertionError("Missing private audio server accepted");
        } finally {
            Files.deleteIfExists(config.toPath());Files.deleteIfExists(server.toPath());
            for(String directory:new String[]{"usr/share/alsa","usr/share","usr","etc/alsa/conf.d","etc/alsa","etc",""})
                Files.deleteIfExists(new File(root,directory).toPath());
        }
    }
}
