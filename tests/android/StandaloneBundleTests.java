package org.gk3hd.standalone;

import android.content.Context;
import org.json.JSONObject;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Tiny synthetic archives, never installed as a player or executed. */
public final class StandaloneBundleTests {
    private static void check(boolean value,String text) {if(!value) throw new AssertionError(text);}
    private static String hash(byte[] bytes) throws Exception {
        StringBuilder text=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes)) text.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return text.toString();
    }
    static Map<String,byte[]> files() {
        Map<String,byte[]> files=new LinkedHashMap<>();
        for(String name:new String[]{"GK3-VR.exe","gk3hd-wine-launcher.exe","ddraw.dll","openxr_wxr32.dll",
            "openxr.json","launch-switches.txt","binkw32.dll","GK3.ini","dxvk.conf","Data/TEST.BRN"})
            files.put("game/"+name,new byte[]{1,2,3,4});
        return files;
    }
    static File zip(File folder,Map<String,byte[]> files,String defect) throws Exception {
        return zip(folder,files,files,1,defect);
    }
    static File componentZip(File folder,Map<String,byte[]> files,Map<String,byte[]> replacements) throws Exception {
        return zip(folder,files,replacements,2,"");
    }
    static File additionsZip(File folder,Map<String,byte[]> files,Map<String,byte[]> payload) throws Exception {
        return zip(folder,files,payload,4,"");
    }
    static File verificationZip(File folder,Map<String,byte[]> files) throws Exception {
        return zip(folder,files,java.util.Collections.emptyMap(),3,"");
    }
    private static File zip(File folder,Map<String,byte[]> files,Map<String,byte[]> payload,int schema,String defect) throws Exception {
        JSONObject inventory=new JSONObject();
        for(Map.Entry<String,byte[]> file:files.entrySet()) {
            JSONObject entry=new JSONObject();entry.put("size",file.getValue().length);entry.put("sha256",hash(file.getValue()));
            inventory.put(file.getKey(),entry);
        }
        if(defect.equals("hash")) inventory.getJSONObject("game/ddraw.dll").put("sha256",new String(new char[64]).replace('\0','0'));
        if(defect.equals("size")) inventory.getJSONObject("game/ddraw.dll").put("size",5);
        if(defect.equals("oversized")) inventory.getJSONObject("game/ddraw.dll").put("size",513L*1024*1024);
        if(defect.equals("expanded")) for(int i=0;i<33;i++) {
            JSONObject large=new JSONObject();large.put("size",512L*1024*1024);large.put("sha256",hash(new byte[0]));
            inventory.put("game/large-"+i+".BMP",large);
        }
        JSONObject manifest=new JSONObject();manifest.put("schema",schema);manifest.put("files",inventory);
        File output=File.createTempFile("bundle-",".zip",folder);
        try(ZipOutputStream zip=new ZipOutputStream(Files.newOutputStream(output.toPath()))) {
            if(!defect.equals("manifest")) {
                zip.putNextEntry(new ZipEntry("bundle.json"));zip.write(manifest.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));zip.closeEntry();
            }
            for(Map.Entry<String,byte[]> file:payload.entrySet()) {
                zip.putNextEntry(new ZipEntry(file.getKey()));zip.write(file.getValue());zip.closeEntry();
            }
            if(defect.equals("unlisted")) {zip.putNextEntry(new ZipEntry("game/unknown.txt"));zip.write(5);zip.closeEntry();}
        }
        return output;
    }
    private static void rejected(File folder,Map<String,byte[]> files,String defect) throws Exception {
        File archive=zip(folder,files,defect);String expected=StandaloneBundle.hash(archive);
        if(defect.equals("transfer")) expected=new String(new char[64]).replace('\0','0');
        try {
            try(StandaloneBundle ignored=StandaloneBundle.extract(archive,folder,expected,(phase,done,total)->{})) {
                throw new AssertionError("Unsafe bundle accepted: "+defect);
            }
        } catch(IllegalArgumentException expectedFailure) {
            if(defect.equals("expanded")) check(expectedFailure.getMessage().contains("storage bound"),"Expanded bound was not enforced before extraction");
        }
        check(folder.listFiles((dir,name)->name.startsWith("gk3hd-incoming-")).length==0,"Failed import left staging artifacts");
    }
    public static void run(Context context) throws Exception {
        runInCache(context.getCacheDir());
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=1) throw new IllegalArgumentException("Explicit test-owned cache required");
        runInCache(new File(args[0]));
        System.out.println("Android private-bundle extraction: compression, original texture names, expanded bound and unsafe-input cleanup passed");
    }
    private static void runInCache(File cache) throws Exception {
        File folder=Files.createTempDirectory(cache.toPath(),"gk3hd-bundle-test-").toFile();
        try {
            File verification=verificationZip(folder,files());
            try(StandaloneBundle bundle=StandaloneBundle.extract(verification,folder,StandaloneBundle.hash(verification),(phase,done,total)->{})) {
                check(bundle.verificationOnly&&!new File(bundle.directory,"game").exists(),"Verification staged game data");
            }
            File valid=zip(folder,files(),"");final long[] progress={0,0};
            try(StandaloneBundle bundle=StandaloneBundle.extract(valid,folder,StandaloneBundle.hash(valid),(phase,done,total)-> {
                if(phase.equals("extract")) {progress[0]=done;progress[1]=total;}
            })) {
                check(new File(bundle.directory,"game/GK3-VR.exe").isFile(),"Verified game not staged");
                check(progress[0]==40&&progress[1]==40,"Incorrect extraction progress");
                File staged=new File(bundle.directory,"game"),published=new File(folder,"published");
                DurableFiles.syncFile(new File(staged,"GK3-VR.exe"));
                DurableFiles.publish(staged,published);
                check(!staged.exists()&&java.util.Arrays.equals(Files.readAllBytes(new File(published,"GK3-VR.exe").toPath()),new byte[]{1,2,3,4}),
                    "Durable publication changed verified player bytes");
                File another=new File(folder,"another");check(another.mkdir(),"Cannot create isolated second import");
                try {DurableFiles.publish(another,published);throw new AssertionError("Existing player overwritten");}
                catch(java.io.IOException expected) {check(another.isDirectory(),"Rejected publication consumed staging");}
                check(java.util.Arrays.equals(Files.readAllBytes(new File(published,"GK3-VR.exe").toPath()),new byte[]{1,2,3,4}),
                    "Rejected publication changed the existing player");
            }
            for(String defect:new String[]{"hash","size","oversized","expanded","manifest","unlisted","transfer"}) rejected(folder,files(),defect);
            for(String path:new String[]{"game/../escape","game/C:/escape","game/CON.txt","game/file.","game/\\escape"}) {
                Map<String,byte[]> invalid=files();invalid.put(path,new byte[]{1});rejected(folder,invalid,"path");
            }
            Map<String,byte[]> duplicate=files();duplicate.put("game/DDRAW.DLL",new byte[]{1});rejected(folder,duplicate,"case collision");
            Map<String,byte[]> missing=files();missing.remove("game/GK3-VR.exe");rejected(folder,missing,"required player");
            Map<String,byte[]> originals=files();
            originals.put("game/gk3hd/textures/installed/FLOORT~1.BMP",new byte[1024]);
            originals.put("game/gk3hd/textures/installed/L'ERMITAGE3.BMP",new byte[1024]);
            File compressed=zip(folder,originals,"");
            try(StandaloneBundle bundle=StandaloneBundle.extract(compressed,folder,StandaloneBundle.hash(compressed),(phase,done,total)->{})) {
                check(new File(bundle.directory,"game/gk3hd/textures/installed/FLOORT~1.BMP").length()==1024,"DOS texture name lost");
                check(new File(bundle.directory,"game/gk3hd/textures/installed/L'ERMITAGE3.BMP").length()==1024,"Quoted texture name lost");
            }
            check(!new File(folder,"escape").exists(),"Archive escaped staging");
        } finally {
            Files.walkFileTree(folder.toPath(),new java.nio.file.SimpleFileVisitor<java.nio.file.Path>() {
                @Override public java.nio.file.FileVisitResult visitFile(java.nio.file.Path path,java.nio.file.attribute.BasicFileAttributes attrs) throws java.io.IOException {
                    Files.delete(path);return java.nio.file.FileVisitResult.CONTINUE;
                }
                @Override public java.nio.file.FileVisitResult postVisitDirectory(java.nio.file.Path path,java.io.IOException error) throws java.io.IOException {
                    if(error!=null) throw error;Files.delete(path);return java.nio.file.FileVisitResult.CONTINUE;
                }
            });
        }
    }
}
