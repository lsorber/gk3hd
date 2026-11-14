package org.gk3hd.standalone;

import android.content.Context;
import java.io.File;
import java.io.RandomAccessFile;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;

/** Tiny disposable files, never real saves or a second full game installation. */
public final class NativeSaveFileTests {
    public static void run(Context context) throws Exception {runIn(context.getCacheDir());}
    public static void main(String[] args) throws Exception {
        if(args.length!=1) throw new IllegalArgumentException("Explicit test cache required");
        runIn(new File(args[0]));
    }
    private static void check(boolean value,String reason) {
        if(!value) throw new AssertionError(reason);
    }
    private static void runIn(File cache) throws Exception {
        File file=Files.createTempFile(cache.toPath(),"native-save-",".gk3").toFile();
        try(RandomAccessFile output=new RandomAccessFile(file,"rw")) {
            check(!NativeSaveFile.finalized(file),"Empty save accepted");
            output.setLength(512);output.writeBytes("GK3!Save");
            check(!NativeSaveFile.finalized(file),"Allocated but unfinished save accepted");
            // Actual native format prefix through the completed-size field,
            // with only the size replaced by this tiny fixture's 512 bytes.
            // The field is intentionally unaligned. Do not test a reader and
            // writer which merely share the same guessed aligned offset.
            byte[] header={71,75,51,33,83,97,118,101,4,0,0,0,(byte)232,0,0,0,
                0,0,1,0,(byte)143,0,0,0,10,0,0,0,80,114,111,100,117,99,116,
                105,111,110,0,0,5,0,0,32,3,0,0,1,0,0,0,0,2,0,0,0,0,0,0};
            output.seek(0);output.write(header);
            check(NativeSaveFile.finalized(file),"Finalized native length rejected");
            output.seek(0xf8);
            for(String value:new String[]{"Lobby fixture","lby","102p"}) {
                output.writeInt(Integer.reverseBytes(value.length()));output.writeBytes(value);output.writeByte(0);
            }
            byte[] before=Files.readAllBytes(file.toPath());
            String[] catalog=NativeSaveFile.catalog(file);
            check(catalog[0].equals("Lobby fixture")&&catalog[1].equals("lby")&&catalog[2].equals("102p"),"Native catalog identity changed");
            check(java.util.Arrays.equals(before,Files.readAllBytes(file.toPath())),"Catalog observation mutated the save");
            output.seek(0xf8);output.writeInt(Integer.reverseBytes(1025));
            try {NativeSaveFile.catalog(file);throw new AssertionError("Unbounded catalog accepted");}catch(java.io.IOException expected) { }
            output.seek(0xf8);output.writeInt(Integer.reverseBytes(13));
            output.seek(0xf8+4+13);output.writeByte(1);
            try {NativeSaveFile.catalog(file);throw new AssertionError("Invalid terminator accepted");}catch(java.io.IOException expected) { }
            output.setLength(511);
            check(!NativeSaveFile.finalized(file),"Truncated payload accepted");
            output.setLength(513);
            check(!NativeSaveFile.finalized(file),"Growing payload accepted");
            output.setLength(512);output.seek(0);output.writeByte('X');
            check(!NativeSaveFile.finalized(file),"Unrelated file accepted");
            output.seek(0);output.writeByte('G');output.seek(0x33);output.writeInt(-1);
            check(!NativeSaveFile.finalized(file),"Unsigned invalid length accepted");
        } finally {Files.deleteIfExists(file.toPath());}
        check(!NativeSaveFile.finalized(file),"Missing save accepted");
        checkSaveEntries(cache);
    }

    private static void checkSaveEntries(File cache) throws Exception {
        Path directory=Files.createTempDirectory(cache.toPath(),"native-save-entries-");
        try {
            for(int i=0;i<1001;i++) Files.createFile(directory.resolve("diagnostic-"+i+".log"));
            Files.createFile(directory.resolve("save0027.GK3"));
            Files.createFile(directory.resolve("save00012.gk3"));
            File[] saves=NativeSaveFile.entries(directory.toFile());
            check(saves!=null&&saves.length==1&&saves[0].getName().equals("save0027.GK3"),
                "Unrelated diagnostics must not consume the save inventory");
        } finally {
            try(DirectoryStream<Path> entries=Files.newDirectoryStream(directory)) {
                for(Path path : entries) Files.delete(path);
            }
            Files.delete(directory);
        }
    }
}
