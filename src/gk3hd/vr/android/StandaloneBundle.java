package org.gk3hd.standalone;

import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Verify a host-prepared private game bundle before publishing any player files. */
public final class StandaloneBundle implements AutoCloseable {
    static final long MAX_TOTAL=16L*1024*1024*1024,MAX_ARCHIVE=16L*1024*1024*1024,MAX_FILE=512L*1024*1024;
    static final int MAX_ENTRIES=20000,MAX_MANIFEST=2*1024*1024;
    static final String[] REQUIRED={"GK3-VR.exe","gk3hd-wine-launcher.exe","ddraw.dll",
        "openxr_wxr32.dll","openxr.json","launch-switches.txt","binkw32.dll","GK3.ini","dxvk.conf"};
    public interface Progress {void update(String stage,long complete,long total);}
    public final File directory;
    public final JSONObject manifest;
    public final String archiveSha256;
    public final boolean componentUpdate;
    public final boolean verificationOnly;
    public final boolean componentAdditions;
    private boolean exchanged;
    private StandaloneBundle(File directory,JSONObject manifest,String hash,int schema) {
        this.directory=directory;this.manifest=manifest;this.archiveSha256=hash;
        this.componentUpdate=schema!=1;this.verificationOnly=schema==3;this.componentAdditions=schema==4;
    }
    private static String hex(byte[] data) {
        StringBuilder text=new StringBuilder();
        for(byte b:data) text.append(String.format(Locale.ROOT,"%02x",b&255));
        return text.toString();
    }
    public static String hash(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream in=Files.newInputStream(file.toPath(),java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer=new byte[128*1024];int count;
            while((count=in.read(buffer))!=-1) digest.update(buffer,0,count);
        }
        return hex(digest.digest());
    }
    static boolean safeName(String name) {
        if(!name.startsWith("game/")||name.equalsIgnoreCase("game/.gk3hd-standalone.json")||name.length()>240||name.endsWith("/")||
           !name.matches("[A-Za-z0-9_./ '~-]+")) return false;
        for(String part:name.split("/",-1)) {
            if(part.isEmpty()||part.equals(".")||part.equals("..")||part.endsWith(".")||part.endsWith(" ")||
               part.split("\\.",2)[0].matches("(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])")) return false;
        }
        return true;
    }
    public static StandaloneBundle extract(File archive,File cache,String expectedSha256,Progress progress) throws Exception {
        if(!archive.isFile()||archive.length()>MAX_ARCHIVE||expectedSha256==null||!expectedSha256.matches("[0-9a-f]{64}"))
            throw new IllegalArgumentException("Invalid standalone bundle size or identity");
        File stage=Files.createTempDirectory(cache.toPath(),"gk3hd-incoming-").toFile();
        try {
        // Freeze public-download bytes inside this app before trusting the
        // manifest. Other apps must not replace them between hash and unzip.
        File frozen=new File(stage,"bundle.zip");
        MessageDigest archiveDigest=MessageDigest.getInstance("SHA-256");long copied=0;
        try(InputStream in=Files.newInputStream(archive.toPath());OutputStream out=Files.newOutputStream(frozen.toPath())) {
            byte[] buffer=new byte[128*1024];int count;
            while((count=in.read(buffer))!=-1) {
                copied+=count;if(copied>MAX_ARCHIVE) throw new IllegalArgumentException("Standalone archive exceeds storage bound");
                out.write(buffer,0,count);archiveDigest.update(buffer,0,count);progress.update("verify",copied,archive.length());
            }
        }
        String archiveHash=hex(archiveDigest.digest());
        if(!archiveHash.equals(expectedSha256)) throw new IllegalArgumentException("Standalone bundle failed transfer verification");
        try(ZipFile zip=new ZipFile(frozen)) {
            ZipEntry metadata=zip.getEntry("bundle.json");
            if(metadata==null||metadata.getSize()<1||metadata.getSize()>MAX_MANIFEST)
                throw new IllegalArgumentException("Missing or oversized standalone bundle manifest");
            byte[] json;
            try(InputStream in=zip.getInputStream(metadata)) {
                java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();
                byte[] buffer=new byte[8192];int count;
                while((count=in.read(buffer))!=-1) {
                    if(out.size()+count>MAX_MANIFEST) throw new IllegalArgumentException("Oversized standalone manifest");
                    out.write(buffer,0,count);
                }
                json=out.toByteArray();
            }
            JSONObject manifest=new JSONObject(new String(json,StandardCharsets.UTF_8));
            int schema=manifest.getInt("schema");
            if(schema<1||schema>4) throw new IllegalArgumentException("Unsupported standalone bundle schema");
            boolean componentUpdate=schema==2||schema==4;
            JSONObject files=manifest.getJSONObject("files");
            if(files.length()<REQUIRED.length||files.length()>MAX_ENTRIES) throw new IllegalArgumentException("Invalid bundle inventory");
            HashSet<String> planned=new HashSet<>();long total=0,transferTotal=0;boolean hasBarn=false;
            for(java.util.Iterator<String> names=files.keys();names.hasNext();) {
                String name=names.next();JSONObject entry=files.getJSONObject(name);
                long size=entry.getLong("size");String sha=entry.getString("sha256");
                if(!safeName(name)||!planned.add(name.toLowerCase(Locale.ROOT))||size<0||size>MAX_FILE||
                   !sha.matches("[0-9a-f]{64}")) throw new IllegalArgumentException("Unsafe standalone bundle inventory");
                if(name.startsWith("game/Data/")&&name.indexOf('/',10)<0&&name.toLowerCase(Locale.ROOT).endsWith(".brn")) hasBarn=true;
                total+=size;if(total>MAX_TOTAL) throw new IllegalArgumentException("Standalone bundle exceeds storage bound");
                if(componentUpdate&&zip.getEntry(name)!=null)transferTotal+=size;
            }
            if(schema==4&&transferTotal>64L*1024*1024)
                throw new IllegalArgumentException("Standalone component transfer exceeds storage bound");
            for(String name:REQUIRED) if(!files.has("game/"+name))
                throw new IllegalArgumentException("Standalone bundle lacks "+name);
            if(!hasBarn) throw new IllegalArgumentException("Standalone bundle has no game data archives");
            HashSet<String> seen=new HashSet<>();long complete=0;int entries=0;
            Enumeration<? extends ZipEntry> contents=zip.entries();
            while(contents.hasMoreElements()) {
                ZipEntry entry=contents.nextElement();String name=entry.getName();
                if(entry.getMethod()!=ZipEntry.STORED&&entry.getMethod()!=ZipEntry.DEFLATED)
                    throw new IllegalArgumentException("Unsupported standalone archive compression");
                if(++entries>MAX_ENTRIES+1||!seen.add(name.toLowerCase(Locale.ROOT)))
                    throw new IllegalArgumentException("Duplicate or excessive archive entries");
                if(name.equals("bundle.json")) continue;
                if(schema==3) throw new IllegalArgumentException("Verification bundle contains game files");
                if(!safeName(name)||!files.has(name)||entry.isDirectory()) throw new IllegalArgumentException("Unlisted archive entry");
                JSONObject expected=files.getJSONObject(name);long size=expected.getLong("size"),written=0;
                if(entry.getSize()!=size) throw new IllegalArgumentException("Archive size differs from manifest");
                File target=new File(stage,name);
                if(!target.getCanonicalPath().startsWith(stage.getCanonicalPath()+File.separator))
                    throw new IllegalArgumentException("Archive entry escapes installation");
                Files.createDirectories(target.getParentFile().toPath());
                MessageDigest digest=MessageDigest.getInstance("SHA-256");
                try(InputStream in=zip.getInputStream(entry);FileOutputStream out=new FileOutputStream(target)) {
                    byte[] buffer=new byte[128*1024];int count;
                    while((count=in.read(buffer))!=-1) {
                        written+=count;if(written>size) throw new IllegalArgumentException("Expanded archive exceeds inventory");
                        out.write(buffer,0,count);digest.update(buffer,0,count);complete+=count;
                        progress.update("extract",complete,componentUpdate?transferTotal:total);
                    }
                    // A matching digest can still read only dirty page cache.
                    // Persist payload bytes before publishing their directory.
                    out.getFD().sync();
                }
                if(written!=size||!hex(digest.digest()).equals(expected.getString("sha256")))
                    throw new IllegalArgumentException("Standalone file failed integrity verification: "+name);
            }
            if(schema!=3&&(componentUpdate?seen.size()<2:seen.size()!=files.length()+1))
                throw new IllegalArgumentException("Standalone bundle inventory is incomplete");
            return new StandaloneBundle(stage,manifest,archiveHash,schema);
        }
        } catch(Exception error) {
            discard(stage);throw error;
        }
    }
    public void writeReceipt() throws Exception {
        JSONObject receipt=new JSONObject();receipt.put("schema",1);
        receipt.put("bundle_sha256",archiveSha256);receipt.put("files",manifest.getJSONObject("files"));
        File file=new File(directory,"game/.gk3hd-standalone.json");
        if(!file.createNewFile())throw new IllegalStateException("Unexpected staged ownership record; existing player preserved");
        try(FileOutputStream out=new FileOutputStream(file)) {
            out.write(receipt.toString().getBytes(StandardCharsets.UTF_8));out.getFD().sync();
        }
    }
    void retirePublishedGame(File retired) {
        // This must precede any operation that can fail after exchange. The
        // staged game is now the OLD player, not disposable extraction output.
        exchanged=true;
        if(!new File(directory,"game").renameTo(retired))
            throw new IllegalStateException("Player updated; previous files preserved for review at "+directory);
    }
    /** Never recursively discard a retired player after publication. */
    @Override public void close() throws Exception {
        if(!exchanged) {discard(directory);return;}
        Files.deleteIfExists(new File(directory,"bundle.zip").toPath());
        try {Files.delete(directory.toPath());}
        catch(java.nio.file.DirectoryNotEmptyException preserved) { }
    }
    private static void discard(File stage) throws Exception {
        Files.walkFileTree(stage.toPath(),new java.nio.file.SimpleFileVisitor<java.nio.file.Path>() {
            @Override public java.nio.file.FileVisitResult visitFile(java.nio.file.Path file,java.nio.file.attribute.BasicFileAttributes attrs) throws java.io.IOException {
                Files.delete(file);return java.nio.file.FileVisitResult.CONTINUE;
            }
            @Override public java.nio.file.FileVisitResult postVisitDirectory(java.nio.file.Path dir,java.io.IOException error) throws java.io.IOException {
                if(error!=null) throw error;
                Files.delete(dir);return java.nio.file.FileVisitResult.CONTINUE;
            }
        });
    }
}
