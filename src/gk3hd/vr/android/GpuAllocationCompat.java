package org.gk3hd.standalone;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.security.MessageDigest;

/** APK-owned compatibility for the private ARM64 guest, selected by backend. */
public final class GpuAllocationCompat {
    private static final String ASSET="graphics_driver/libgk3hd_kgsl.so";
    private static final String SHA=com.winlator.BuildConfig.GK3HD_KGSL_SHA;
    private static final int BYTES=com.winlator.BuildConfig.GK3HD_KGSL_BYTES;
    static {System.loadLibrary("gk3hd_files");}
    static native int legacyAllocationPolicy();
    private GpuAllocationCompat() { }

    public static synchronized File prepare(Context context) throws Exception {
        byte[] bytes;
        try(InputStream input=context.getAssets().open(ASSET)) {
            bytes=NativeVulkanClient.read(input,1024*1024);
        }
        return prepare(new File(context.getFilesDir(),"gk3hd-graphics"),bytes);
    }

    static File prepare(File directory,byte[] bytes) throws Exception {
        StringBuilder digest=new StringBuilder();
        for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))
            digest.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
        if(bytes.length!=BYTES||!digest.toString().equals(SHA))
            throw new IllegalStateException("GPU allocation asset does not match this APK");
        if(Files.isSymbolicLink(directory.toPath())||!directory.isDirectory()&&!directory.mkdirs())
            throw new IllegalStateException("GPU compatibility cache is unavailable; existing files preserved");
        File[] entries=directory.listFiles();long total=0;
        if(entries==null||entries.length>64)throw new IllegalStateException("GPU compatibility cache exceeds its bound");
        for(File entry:entries) {
            if(Files.isSymbolicLink(entry.toPath())||!entry.isFile()||(total+=entry.length())>8L*1024*1024)
                throw new IllegalStateException("GPU compatibility cache exceeds its bound; existing files preserved");
        }
        File file=new File(directory,"libgk3hd_kgsl-"+SHA+".so");
        File backup=new File(file.getPath()+".bak");
        if(Files.isSymbolicLink(file.toPath())||Files.isSymbolicLink(backup.toPath()))
            throw new IllegalStateException("GPU compatibility cache is redirected; existing files preserved");
        AtomicFile atomic=new AtomicFile(file);
        if(file.exists()||backup.exists()) {
            try(InputStream input=atomic.openRead()) {
                if(!MessageDigest.isEqual(NativeVulkanClient.read(input,1024*1024),bytes))
                    throw new IllegalStateException("GPU compatibility cache changed; existing files preserved");
            }
        } else {
            java.io.FileOutputStream output=atomic.startWrite();
            try {output.write(bytes);output.getFD().sync();atomic.finishWrite(output);}
            catch(Exception error) {atomic.failWrite(output);throw error;}
            DurableFiles.syncDirectory(directory);
        }
        return file;
    }

    public static String preload(Context context,String existing) throws Exception {
        int policy=legacyAllocationPolicy();
        if(policy<0)throw new IllegalStateException("Cannot inspect the private GPU allocation API: errno="+(-policy));
        if(policy==0) {
            android.util.Log.i("GK3HDGpuMemory","Legacy allocation permitted; compatibility helper not loaded");
            return existing==null ? "" : existing;
        }
        String path=prepare(context).getCanonicalPath();
        android.util.Log.i("GK3HDGpuMemory","Prepared private allocation compatibility sha256="+SHA);
        if(existing==null||existing.isEmpty())return path;
        for(String entry:existing.split("[:\\s]+"))if(entry.equals(path))return existing;
        return path+":"+existing;
    }
}
