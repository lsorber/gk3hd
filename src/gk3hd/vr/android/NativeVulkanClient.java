package org.gk3hd.standalone;

import android.content.Context;
import android.util.AtomicFile;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.apache.commons.compress.archivers.tar.TarArchiveEntry;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.apache.commons.compress.compressors.zstandard.ZstdCompressorInputStream;
import org.json.JSONObject;

/** Versioned APK asset, cached in this app. No download or installed-driver edit. */
public final class NativeVulkanClient {
    static final String ASSET="graphics_driver/gk3hd-vortek.tzst";
    static final String ARCHIVE_SHA=com.winlator.BuildConfig.GK3HD_VORTEK_ARCHIVE_SHA;
    static final String CLIENT_SHA=com.winlator.BuildConfig.GK3HD_VORTEK_CLIENT_SHA;
    private static final int MAX_ARCHIVE=1024*1024,CLIENT_BYTES=com.winlator.BuildConfig.GK3HD_VORTEK_CLIENT_BYTES;
    private NativeVulkanClient() { }
    private static String hash(byte[] bytes) throws Exception {
        StringBuilder result=new StringBuilder();
        for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))
            result.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
        return result.toString();
    }
    static byte[] read(InputStream in,int maximum) throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
        while((count=in.read(buffer))!=-1) {
            if(out.size()+count>maximum) throw new IllegalArgumentException("Native Vulkan asset exceeds its bound");
            out.write(buffer,0,count);
        }
        return out.toByteArray();
    }
    static byte[] extract(byte[] archive) throws Exception {
        if(archive.length>MAX_ARCHIVE||!hash(archive).equals(ARCHIVE_SHA))
            throw new IllegalArgumentException("The APK's native Vulkan archive does not match the pinned input");
        byte[] client=null;int count=0;long total=0;
        try(TarArchiveInputStream tar=new TarArchiveInputStream(new ZstdCompressorInputStream(new ByteArrayInputStream(archive)))) {
            TarArchiveEntry entry;
            while((entry=tar.getNextTarEntry())!=null) {
                if(++count>32||(total+=entry.getSize())>MAX_ARCHIVE||entry.isSymbolicLink()||entry.isLink())
                    throw new IllegalArgumentException("Unexpected native Vulkan archive layout");
                if(!entry.getName().equals("./usr/lib/libvulkan_vortek.so")) continue;
                if(client!=null||!entry.isFile()||entry.getSize()!=CLIENT_BYTES)
                    throw new IllegalArgumentException("Unexpected native Vulkan client entry");
                client=read(tar,CLIENT_BYTES);
            }
        }
        if(client==null||client.length!=CLIENT_BYTES||!hash(client).equals(CLIENT_SHA))
            throw new IllegalArgumentException("The APK's native Vulkan client failed verification");
        return client;
    }
    private static void publish(File file,byte[] bytes) throws Exception {
        File backup=new File(file.getPath()+".bak");
        if(Files.isSymbolicLink(file.toPath())||Files.isSymbolicLink(backup.toPath()))
            throw new IllegalStateException("Native Vulkan cache is redirected; existing files preserved");
        AtomicFile atomic=new AtomicFile(file);
        if(file.exists()||backup.exists()) {
            try(InputStream input=atomic.openRead()) {
                if(!MessageDigest.isEqual(read(input,bytes.length),bytes))
                    throw new IllegalStateException("Native Vulkan cache changed; existing files preserved");
            }
            return;
        }
        java.io.FileOutputStream output=atomic.startWrite();
        try {output.write(bytes);output.getFD().sync();atomic.finishWrite(output);}
        catch(Exception error) {atomic.failWrite(output);throw error;}
    }
    static synchronized File prepare(File cache,byte[] archive,String alias) throws Exception {
        if(Files.isSymbolicLink(cache.toPath())) throw new IllegalStateException("Native Vulkan cache directory is redirected");
        byte[] bytes=extract(archive);
        if(!PrivateRuntimePaths.relocateBytes(bytes,"/data/data/com.winlator/files/rootfs",alias))
            throw new IllegalStateException("Native Vulkan client has no expected loader paths");
        if(!cache.isDirectory()&&!cache.mkdirs()) throw new IllegalStateException("Cannot create native Vulkan cache");
        File[] entries=cache.listFiles();long total=0;
        if(entries==null||entries.length>64) throw new IllegalStateException("Native Vulkan cache inventory exceeds its bound");
        for(File entry:entries) {
            if(!entry.isFile()||Files.isSymbolicLink(entry.toPath())||(total+=entry.length())>8L*1024*1024)
                throw new IllegalStateException("Native Vulkan cache exceeds its storage bound; files preserved");
        }
        String id=hash(bytes);
        File client=new File(cache,"libvulkan_vortek-"+id+".so");
        File manifest=new File(cache,"vortek-"+id+".json");
        publish(client,bytes);
        JSONObject descriptor=new JSONObject().put("file_format_version","1.0.0")
            .put("ICD",new JSONObject().put("api_version","1.1.128").put("library_path",client.getCanonicalPath()));
        publish(manifest,descriptor.toString().getBytes(StandardCharsets.UTF_8));
        DurableFiles.syncDirectory(cache);
        return manifest;
    }
    public static File prepare(Context context,File root) throws Exception {
        File alias=PrivateRuntimePaths.alias(context,root);byte[] archive;
        try(InputStream input=context.getAssets().open(ASSET)) {archive=read(input,MAX_ARCHIVE);}
        return prepare(new File(context.getFilesDir(),"gk3hd-vulkan"),archive,alias.getPath());
    }
}
