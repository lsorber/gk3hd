package org.gk3hd.standalone;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

public final class ComponentPairingTests {
    private static final String ABC="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static Map<String,String> parse(String text) throws IOException {
        return ComponentPairing.expected(new ByteArrayInputStream(text.getBytes(StandardCharsets.US_ASCII)));
    }
    private static void rejects(String text) throws IOException {
        try {parse(text);}catch(IOException expected){return;}
        throw new AssertionError("Malformed component pairing was accepted");
    }
    public static void main(String[] args) throws Exception {
        String good=ABC+"  openxr_wxr32.dll\n"+ABC+"  gk3hd-wine-launcher.exe\n";
        Map<String,String> expected=parse(good);
        require(parse(good.replace("\n","\r\n")).equals(expected),"CRLF changes component identity");
        rejects("");rejects(ABC+"  openxr_wxr32.dll\n");
        rejects(good+ABC+"  openxr_wxr32.dll\n");rejects(good.replace("openxr_wxr32.dll","../openxr_wxr32.dll"));
        rejects(good.replace(ABC,"invalid"));rejects(good+"\n");
        rejects(new String(new char[513]).replace('\0','x'));
        Path directory=Files.createTempDirectory("gk3hd-components-");
        try {
            File runtime=directory.resolve("openxr_wxr32.dll").toFile();
            File launcher=directory.resolve("gk3hd-wine-launcher.exe").toFile();
            Files.write(runtime.toPath(),"abc".getBytes(StandardCharsets.US_ASCII));
            Files.write(launcher.toPath(),"abc".getBytes(StandardCharsets.US_ASCII));
            ComponentPairing.require(directory.toFile(),expected);
            Files.write(runtime.toPath(),"changed".getBytes(StandardCharsets.US_ASCII));
            boolean rejected=false;
            try {ComponentPairing.require(directory.toFile(),expected);}catch(IOException mismatch){rejected=true;}
            require(rejected,"Changed runtime passed the launch check");
        }finally {
            Files.deleteIfExists(directory.resolve("openxr_wxr32.dll"));
            Files.deleteIfExists(directory.resolve("gk3hd-wine-launcher.exe"));
            Files.delete(directory);
        }
        if(args.length==3) {
            try(java.io.InputStream asset=Files.newInputStream(new File(args[0]).toPath())) {
                Map<String,String> actual=ComponentPairing.expected(asset);
                for(Map.Entry<String,String> entry:actual.entrySet()) {
                    File file=new File(entry.getKey().equals("openxr_wxr32.dll")?args[1]:args[2]);
                    require(file.getName().equals(entry.getKey()),"Unexpected build component name");
                    ComponentPairing.require(file.getParentFile(),java.util.Collections.singletonMap(entry.getKey(),entry.getValue()));
                }
            }
        }
        System.out.println("Component pairing: malformed/missing/duplicate identities rejected, matching bytes accepted and changed runtime rejected");
    }
}
