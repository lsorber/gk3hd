package org.gk3hd.standalone;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** The native consumer and guest producer must come from the same player build. */
public final class ComponentPairing {
    public static final String ASSET="gk3hd-components.sha256";
    private static final int MAXIMUM=512,MAX_FILE=8*1024*1024;
    private static final String UPDATE="Player components do not match. Update GK3HD VR and its game bundle together.";
    private ComponentPairing() { }

    public static Map<String,String> expected(InputStream source) throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        int next;
        while((next=source.read())!=-1) {
            if(bytes.size()>=MAXIMUM)throw new IOException(UPDATE);
            bytes.write(next);
        }
        String[] lines=new String(bytes.toByteArray(),StandardCharsets.US_ASCII).split("\n",-1);
        Map<String,String> result=new HashMap<>();
        for(int i=0;i<lines.length;i++) {
            if(i==lines.length-1&&lines[i].isEmpty())continue;
            String[] fields=lines[i].trim().split("\\s+");
            if(fields.length!=2||!fields[0].matches("[0-9a-f]{64}")||
               !(fields[1].equals("openxr_wxr32.dll")||fields[1].equals("gk3hd-wine-launcher.exe"))||
               result.put(fields[1],fields[0])!=null)throw new IOException(UPDATE);
        }
        if(result.size()!=2)throw new IOException(UPDATE);
        return Collections.unmodifiableMap(result);
    }

    public static void require(File directory,Map<String,String> expected) throws Exception {
        for(Map.Entry<String,String> entry:expected.entrySet()) {
            File file=new File(directory,entry.getKey());
            if(Files.isSymbolicLink(file.toPath())||!file.isFile()||file.length()>MAX_FILE)
                throw new IOException(UPDATE);
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            int total=0,count;byte[] block=new byte[65536];
            try(InputStream input=new FileInputStream(file)) {
                while((count=input.read(block))!=-1) {
                    total+=count;if(total>MAX_FILE)throw new IOException(UPDATE);
                    digest.update(block,0,count);
                }
            }
            StringBuilder value=new StringBuilder();
            for(byte b:digest.digest())value.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
            if(!value.toString().equals(entry.getValue()))throw new IOException(UPDATE);
        }
    }
}
