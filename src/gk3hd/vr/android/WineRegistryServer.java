package org.gk3hd.standalone;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;

/** Publish the APK's immutable server beside Wine, retaining its NLS lookup. */
public final class WineRegistryServer {
    public static final int MAX_BYTES=2*1024*1024;
    private static final String PREFIX="gk3hd-wineserver-";
    private static final String STOCK="7a9729c87858ae93e31f77c4e10afa5164087a4eca603c32045209e4c2bf0bd2";
    private WineRegistryServer() { }
    static String hash(byte[] bytes) throws Exception {
        StringBuilder result=new StringBuilder();
        for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))
            result.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
        return result.toString();
    }
    private static void validate(byte[] image,String expected) throws Exception {
        if(image.length<64||image.length>MAX_BYTES||image[0]!=127||image[1]!='E'||
           image[2]!='L'||image[3]!='F'||image[4]!=2||image[5]!=1||
           (image[16]!=2&&image[16]!=3)||image[17]!=0||image[18]!=62||image[19]!=0||
           expected==null||!expected.matches("[a-f0-9]{64}")||!hash(image).equals(expected))
            throw new IOException("The APK's Wine server failed its x86-64 identity check");
    }
    private static byte[] read(InputStream input,int maximum) throws Exception {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] block=new byte[8192];int count;
        while((count=input.read(block))!=-1) {
            if(output.size()+count>maximum)throw new IOException("Wine server asset exceeds its bound");
            output.write(block,0,count);
        }
        return output.toByteArray();
    }
    public static File prepare(File root,InputStream binary,InputStream identity) throws Exception {
        String expected=new String(read(identity,128),java.nio.charset.StandardCharsets.US_ASCII).trim();
        return prepare(root,read(binary,MAX_BYTES),expected);
    }
    private static boolean matches(File file,String expected) throws Exception {
        return file.isFile()&&!Files.isSymbolicLink(file.toPath())&&file.length()<=MAX_BYTES&&
            hash(Files.readAllBytes(file.toPath())).equals(expected);
    }
    public static synchronized File prepare(File root,byte[] image,String expected) throws Exception {
        validate(image,expected);
        File directory=new File(root,"opt/wine/bin");
        if(!directory.isDirectory()||Files.isSymbolicLink(directory.toPath())||
           !directory.getCanonicalFile().toPath().startsWith(root.getCanonicalFile().toPath()))
            throw new IOException("The private Wine executable directory is redirected or missing");
        File[] previous=directory.listFiles((parent,name)->name.startsWith(PREFIX));
        if(previous==null||previous.length>16)
            throw new IOException("The private Wine server cache exceeds its bound; files preserved");
        long total=0;
        for(File file:previous)
            if(Files.isSymbolicLink(file.toPath())||!file.isFile()||file.length()>MAX_BYTES||
               (total+=file.length())>32L*1024*1024)
                throw new IOException("The private Wine server cache changed; files preserved");
        File target=new File(directory,PREFIX+expected);
        if(Files.exists(target.toPath(),java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            if(!matches(target,expected)||!target.canExecute())
                throw new IOException("The cached Wine server changed; existing file preserved");
            return target;
        }
        if(previous.length==16)
            throw new IOException("The private Wine server cache is full; existing versions preserved");
        Path temporary=Files.createTempFile(directory.toPath(),"gk3hd-wine-",".tmp");
        try {
            try(FileOutputStream output=new FileOutputStream(temporary.toFile())) {
                output.write(image);output.getFD().sync();
            }
            if(!temporary.toFile().setExecutable(true,true))
                throw new IOException("Cannot mark the private Wine server executable");
            Files.move(temporary,target.toPath(),StandardCopyOption.ATOMIC_MOVE);
        } finally {Files.deleteIfExists(temporary);}
        if(!matches(target,expected)||!target.canExecute())
            throw new IOException("The private Wine server publication did not verify");
        return target;
    }
    /** Preserve Wine's executable name and Box64's Wine-specific handling. */
    public static synchronized void activate(File root,File selected) throws Exception {
        File directory=new File(root,"opt/wine/bin").getCanonicalFile();
        File server=new File(directory,"wineserver");String identity=selected.getName();
        if(!selected.getCanonicalFile().getParentFile().equals(directory)||
           !identity.matches(PREFIX+"[a-f0-9]{64}")||
           !matches(selected,identity.substring(PREFIX.length())))
            throw new IOException("The selected Wine server is not an owned immutable version");
        String expected=identity.substring(PREFIX.length());
        if(matches(server,expected))return;
        if(Files.isSymbolicLink(server.toPath())||!server.isFile()||server.length()>MAX_BYTES)
            throw new IOException("The Wine server is redirected; existing file preserved");
        byte[] previous=Files.readAllBytes(server.toPath());String previousHash=hash(previous);
        if(previousHash.equals(STOCK))prepare(root,previous,STOCK);
        else if(!matches(new File(directory,PREFIX+previousHash),previousHash))
            throw new IOException("The original Wine server changed; existing file preserved");
        Path temporary=Files.createTempFile(directory.toPath(),"gk3hd-wine-active-",".tmp");
        try {
            try(FileOutputStream output=new FileOutputStream(temporary.toFile())) {
                output.write(Files.readAllBytes(selected.toPath()));output.getFD().sync();
            }
            if(!temporary.toFile().setExecutable(true,true))
                throw new IOException("Cannot mark the selected Wine server executable");
            Files.move(temporary,server.toPath(),StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING);
        } finally {Files.deleteIfExists(temporary);}
        if(!matches(server,expected)||!server.canExecute())
            throw new IOException("The selected Wine server publication did not verify");
    }
}
