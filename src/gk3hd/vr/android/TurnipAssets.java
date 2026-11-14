package org.gk3hd.standalone;

import android.content.Context;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import com.winlator.core.TarCompressorUtils;
import org.json.JSONObject;

/** Verify the built-in private driver before any translated program starts. */
public final class TurnipAssets {
    static final String ASSET="gk3hd-turnip.json";
    static final String[] LIBRARIES={"libvulkan_freedreno.so","libxcb-xfixes.so.0",
        "libxcb-shape.so.0","libxshmfence.so.1"};
    private TurnipAssets() { }
    static JSONObject descriptor(Context context) throws Exception {
        try(InputStream input=context.getAssets().open(ASSET)) {
            return new JSONObject(new String(NativeVulkanClient.read(input,65536),StandardCharsets.UTF_8));
        }
    }
    public static boolean supportsCompressedX11(Context context) throws Exception {
        return Boolean.TRUE.equals(descriptor(context).opt("compressed_x11"));
    }
    static boolean matches(File root,JSONObject description) throws Exception {
        JSONObject files=description.getJSONObject("files");
        if(files.length()!=LIBRARIES.length)throw new IllegalStateException("Unexpected private driver inventory");
        File directory=new File(root,"usr/lib");
        if(!directory.getCanonicalFile().toPath().startsWith(root.getCanonicalFile().toPath())||
                Files.isSymbolicLink(directory.toPath()))
            throw new IllegalStateException("Private graphics directory is redirected");
        boolean valid=true;
        for(String library:LIBRARIES) {
            JSONObject entry=files.getJSONObject(library);
            long size=entry.getLong("bytes");String expected=entry.getString("sha256");
            long maximum=library.equals(LIBRARIES[0])?32L*1024*1024:1024*1024;
            if(size<20||size>maximum||!expected.matches("[0-9a-f]{64}"))
                throw new IllegalStateException("Invalid private graphics identity");
            File file=new File(directory,library);
            if(Files.isSymbolicLink(file.toPath())||
                    !file.getCanonicalFile().getParentFile().equals(directory.getCanonicalFile()))
                throw new IllegalStateException("Private graphics library is redirected");
            if(!file.isFile()||file.length()!=size) {valid=false;continue;}
            MessageDigest hash=MessageDigest.getInstance("SHA-256");long total=0;
            try(InputStream input=Files.newInputStream(file.toPath())) {
                byte[] block=new byte[65536];int count;
                while((count=input.read(block))!=-1) {
                    total+=count;if(total>size)break;hash.update(block,0,count);
                }
            }
            StringBuilder actual=new StringBuilder();
            for(byte value:hash.digest())actual.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
            if(total!=size||!actual.toString().equals(expected))valid=false;
        }
        return valid&&new File(root,"usr/share/vulkan/icd.d/freedreno_icd.aarch64.json").isFile();
    }
    /** Use the APK's private driver identity regardless of the Winlator profile cache. */
    public static synchronized void prepare(Context context,File root) throws Exception {
        JSONObject description=descriptor(context);
        if(matches(root,description))return;
        String version=description.getString("version");
        if(!version.matches("[0-9.]+-gk3hd-[a-f0-9]{12}"))
            throw new IllegalStateException("Invalid private graphics archive version");
        String asset="graphics_driver/turnip-"+version+".tzst";
        if(!TarCompressorUtils.extract(TarCompressorUtils.Type.ZSTD,context,asset,root)||!matches(root,description))
            throw new IllegalStateException("Private graphics installation is incomplete. Launch again to repair it.");
    }
}
