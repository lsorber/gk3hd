package org.gk3hd.standalone;

import android.content.Context;
import android.system.Os;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;

/** Relocate upstream ELF storage paths into an app-owned runtime alias. */
public final class PrivateRuntimePaths {
    private static final String UPSTREAM="/data/data/com.winlator/files/rootfs";
    private static final long MAX_ELF=64L*1024*1024,MAX_TOTAL=1024L*1024*1024;
    private PrivateRuntimePaths() { }
    public static synchronized File prepare(Context context,File root) throws Exception {
        File alias=alias(context,root);String replacement=alias.getPath();
        prepareWineMapCompletion(root);
        relocateAudioConfig(root);
        prepareNativePaths(context,root,replacement);
        try(InputStream binary=context.getAssets().open("gk3hd/wine-server.elf");
            InputStream identity=context.getAssets().open("gk3hd/wine-server.sha256")) {
            File server=WineRegistryServer.prepare(root,binary,identity);
            WineRegistryServer.activate(root,server);
        }
        return alias;
    }
    /** Publish the exact qualified runtime before starting any translated process. */
    static boolean prepareWineMapCompletion(File root) throws Exception {
        File file=new File(root,"opt/wine/lib/wine/i386-windows/wined3d.dll");
        if(Files.isSymbolicLink(file.toPath())||
                !file.getCanonicalFile().toPath().startsWith(root.getCanonicalFile().toPath()))
            throw new IllegalStateException("Wine map runtime must belong to the private root");
        AtomicFile atomic=new AtomicFile(file);
        byte[] original=new byte[WineMapCompletion.SIZE];
        // openRead also recovers the previous file after an interrupted write.
        try(java.io.FileInputStream input=atomic.openRead()) {
            if(input.getChannel().size()!=original.length)
                throw new IllegalStateException("The private Wine map runtime has an unexpected size");
            int offset=0;
            while(offset<original.length) {
                int count=input.read(original,offset,original.length-offset);
                if(count<0)throw new IllegalStateException("The private Wine map runtime is incomplete");
                offset+=count;
            }
            if(input.read()!=-1)throw new IllegalStateException("The private Wine map runtime grew during preparation");
        }
        byte[] updated=WineMapCompletion.apply(original);
        if(updated==original)return false;
        int mode=Os.stat(file.getPath()).st_mode&0777;
        java.io.FileOutputStream stream=atomic.startWrite();
        try {
            stream.write(updated);Os.fchmod(stream.getFD(),mode);stream.getFD().sync();
            atomic.finishWrite(stream);
        } catch(Exception error) {atomic.failWrite(stream);throw error;}
        byte[] published=atomic.readFully();
        if(WineMapCompletion.apply(published)!=published)
            throw new IllegalStateException("Wine map completion publication did not finish");
        android.util.Log.i("GK3HDRuntime","Prepared Wine texture-map completion handshake");
        return true;
    }
    /** Establish the private loader alias before any optional client is staged. */
    static synchronized File alias(Context context,File root) throws Exception {
        File app=new File("/data/data",context.getPackageName());
        // Android can bind-mount /data/data and /data/user/0 onto the same
        // directory without a symlink. Canonical path strings then differ.
        if(!Files.isSameFile(app.toPath(),context.getDataDir().toPath())||
           !Files.isSameFile(root.toPath(),new File(context.getFilesDir(),"rootfs").toPath()))
            throw new IllegalArgumentException("Runtime must belong to this app");
        // Equal-width alias preserves every ELF offset and embedded string size.
        // It is a symlink inside OUR sandbox, never one into Winlator's data.
        File alias=new File(app,"root");String replacement=alias.getPath();
        if(replacement.length()!=UPSTREAM.length()) throw new IllegalStateException("Private runtime alias width differs");
        if(Files.exists(alias.toPath(),LinkOption.NOFOLLOW_LINKS)) {
            if(!Files.isSymbolicLink(alias.toPath())||!Files.isSameFile(alias.toPath(),root.toPath()))
                throw new IllegalStateException("Private runtime alias is occupied; existing data was preserved");
        } else Os.symlink(root.getPath(),alias.getPath());
        return alias;
    }
    private static void prepareNativePaths(Context context,File root,String replacement) throws Exception {
        File icd=new File(root,"usr/share/vulkan/icd.d/freedreno_icd.aarch64.json");
        File driver=new File(root,"usr/lib/libvulkan_freedreno.so");
        if(!icd.isFile()||icd.length()>65536||!driver.isFile())
            throw new IllegalStateException("The private Turnip driver is missing");
        JSONObject driverManifest=new JSONObject(new String(Files.readAllBytes(icd.toPath()),StandardCharsets.UTF_8));
        JSONObject descriptor=driverManifest.getJSONObject("ICD");
        if(!descriptor.optString("library_arch","64").equals("64"))
            throw new IllegalStateException("The private Vulkan driver has the wrong architecture");
        if(!descriptor.getString("library_path").equals(driver.getPath())) {
            descriptor.put("library_path",driver.getPath());
            AtomicFile updated=new AtomicFile(icd);java.io.FileOutputStream stream=updated.startWrite();
            try {stream.write(driverManifest.toString().getBytes(StandardCharsets.UTF_8));updated.finishWrite(stream);}
            catch(Exception error) {updated.failWrite(stream);throw error;}
        }
        File cache=new File(root,".gk3hd-native-paths.json");JSONObject previous=new JSONObject();
        if(cache.isFile()&&cache.length()<2*1024*1024)
            previous=new JSONObject(new String(Files.readAllBytes(cache.toPath()),StandardCharsets.UTF_8));
        JSONObject current=new JSONObject();long total=0;int count=0;
        for(String directory:new String[]{"usr","opt"}) {
            try(java.util.stream.Stream<Path> paths=Files.walk(new File(root,directory).toPath())) {
                java.util.Iterator<Path> iterator=paths.iterator();
                while(iterator.hasNext()) {
                    Path path=iterator.next();if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)) continue;
                    if(++count>20000) throw new IllegalStateException("Private runtime file count exceeds its bound");
                    File file=path.toFile();String name=root.toPath().relativize(path).toString();
                    String identity=file.length()+":"+file.lastModified();
                    if(identity.equals(previous.optString(name,""))) {current.put(name,identity);continue;}
                    if(isElf(file)) {
                        total+=file.length();if(total>MAX_TOTAL) throw new IllegalStateException("Native relocation exceeds its storage bound");
                        relocate(file,UPSTREAM,replacement);
                    }
                    current.put(name,file.length()+":"+file.lastModified());
                }
            }
        }
        AtomicFile state=new AtomicFile(cache);java.io.FileOutputStream stream=state.startWrite();
        try {stream.write(current.toString().getBytes(StandardCharsets.UTF_8));state.finishWrite(stream);}
        catch(Exception error) {state.failWrite(stream);throw error;}
    }
    /** The upstream ALSA hook is text, so ELF relocation cannot fix it. */
    static boolean relocateAudioConfig(File root) throws Exception {
        File config=new File(root,"usr/share/alsa/alsa.conf");
        File server=new File(root,"etc/alsa/conf.d/android_aserver.conf");
        if(!server.isFile()) throw new IllegalStateException("The private audio configuration is missing");
        AtomicFile updated=new AtomicFile(config);
        byte[] bytes;
        try(InputStream input=updated.openRead();java.io.ByteArrayOutputStream output=new java.io.ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];int count;
            while((count=input.read(buffer))!=-1) {
                if(output.size()+count>65536) throw new IllegalStateException("Audio configuration exceeds its size bound");
                output.write(buffer,0,count);
            }
            bytes=output.toByteArray();
        }
        String original=new String(bytes,StandardCharsets.UTF_8);
        String changed=original.replace(UPSTREAM+"/etc/alsa/conf.d/android_aserver.conf",server.getPath());
        if(changed.equals(original)) return false;
        byte[] result=changed.getBytes(StandardCharsets.UTF_8);
        if(result.length>65536) throw new IllegalStateException("Relocated audio configuration exceeds its size bound");
        java.io.FileOutputStream stream=updated.startWrite();
        try {stream.write(result);stream.getFD().sync();updated.finishWrite(stream);}
        catch(Exception error) {updated.failWrite(stream);throw error;}
        return true;
    }
    private static boolean isElf(File file) throws Exception {
        try(InputStream input=Files.newInputStream(file.toPath())) {
            byte[] magic=new byte[4];int offset=0;
            while(offset<magic.length) {int read=input.read(magic,offset,magic.length-offset);if(read<0) return false;offset+=read;}
            return Arrays.equals(magic,new byte[]{127,'E','L','F'});
        }
    }
    static boolean relocate(File file,String original,String replacement) throws Exception {
        byte[] before=original.getBytes(StandardCharsets.US_ASCII),after=replacement.getBytes(StandardCharsets.US_ASCII);
        if(before.length==0||before.length!=after.length||file.length()>MAX_ELF||!isElf(file))
            throw new IllegalArgumentException("Native relocation requires bounded ELF data and equal-width paths");
        byte[] bytes=Files.readAllBytes(file.toPath());
        if(!relocateBytes(bytes,original,replacement)) return false;
        Path temporary=Files.createTempFile(file.getParentFile().toPath(),"gk3hd-native-",".tmp");
        try {
            Files.write(temporary,bytes);Os.chmod(temporary.toString(),Os.stat(file.getPath()).st_mode&0777);
            Files.move(temporary,file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        } finally {Files.deleteIfExists(temporary);}
        return true;
    }
    /** Relocate a verified asset in memory before publishing its cached bytes. */
    static boolean relocateBytes(byte[] bytes,String original,String replacement) {
        byte[] before=original.getBytes(StandardCharsets.US_ASCII),after=replacement.getBytes(StandardCharsets.US_ASCII);
        if(before.length==0||before.length!=after.length||bytes.length<4||bytes.length>MAX_ELF||
           bytes[0]!=127||bytes[1]!='E'||bytes[2]!='L'||bytes[3]!='F')
            throw new IllegalArgumentException("Native relocation requires bounded ELF data and equal-width paths");
        boolean changed=false;
        for(int offset=4;offset<=bytes.length-before.length;offset++) {
            int index=0;while(index<before.length&&bytes[offset+index]==before[index]) index++;
            if(index!=before.length) continue;
            System.arraycopy(after,0,bytes,offset,after.length);changed=true;offset+=before.length-1;
        }
        return changed;
    }
}
