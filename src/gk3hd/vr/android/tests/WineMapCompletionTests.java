package org.gk3hd.standalone;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;

/** Qualify the actual pinned upstream input without distributing a second DLL. */
public final class WineMapCompletionTests {
    private WineMapCompletionTests() { }
    public static void main(String[] args) throws Exception {
        if(args.length!=2)throw new IllegalArgumentException("Expected pinned input and fresh output paths");
        Path source=Paths.get(args[0]),output=Paths.get(args[1]);
        if(Files.exists(output))throw new IllegalArgumentException("Preserve existing test output");
        byte[] original=Files.readAllBytes(source),saved=original.clone();
        byte[] completed=WineMapCompletion.apply(original);
        if(completed==original||!Arrays.equals(original,saved)||completed.length!=original.length)
            throw new AssertionError("Correction did not preserve its original input");
        if(WineMapCompletion.apply(completed)!=completed)
            throw new AssertionError("Qualified output is not idempotent");
        // Corruption at the header, native instructions, padding and end of file
        // must never be repaired by guessing, even for an otherwise known image.
        int rejected=0;
        for(byte[] image:new byte[][]{original,completed}) {
            for(int offset:new int[]{0,384,1745942,1746317,2071632,2071664,image.length-1}) {
                byte[] damaged=image.clone();damaged[offset]^=1;byte[] before=damaged.clone();
                try {WineMapCompletion.apply(damaged);throw new AssertionError("Unknown runtime accepted");}
                catch(IllegalStateException expected) {rejected++;}
                if(!Arrays.equals(before,damaged))throw new AssertionError("Unknown bytes were modified");
            }
        }
        for(int size:new int[]{0,original.length-1,original.length+1}) {
            byte[] malformed=new byte[size];
            try {WineMapCompletion.apply(malformed);throw new AssertionError("Unexpected size accepted");}
            catch(IllegalStateException expected) {rejected++;}
        }
        if(!Arrays.equals(saved,Files.readAllBytes(source)))throw new AssertionError("Source file changed");
        Files.write(output,completed);
        System.out.println("Pinned Wine correction, idempotency, input preservation and "+rejected+" rejection controls passed");
    }
}
