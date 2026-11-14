package org.gk3hd.standalone;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Visible-eye/layout properties and bounded vectors for the native producer. */
public final class StereoTransportTests {
    private static void check(boolean value,String text) {if(!value)throw new AssertionError(text);}
    private static void rejected(int visible) {
        try {StereoTransport.height(visible);throw new AssertionError("Invalid visible height accepted");}
        catch(IllegalArgumentException expected) {}
    }
    public static void main(String[] args)throws Exception {
        StringBuilder vectors=new StringBuilder();
        for(int visible=1;visible<=4096;visible++) {
            int physical=StereoTransport.height(visible);
            check(physical>visible&&physical-visible<=4,"Metadata/padding changes the visible extent");
            check(physical%4==0,"Transport does not fit the pinned linear-image row alignment");
            vectors.append(visible).append(' ').append(physical).append('\n');
        }
        for(int visible:new int[]{8191,8192,16383,16384,Integer.MAX_VALUE-4}) {
            int physical=StereoTransport.height(visible);
            check(physical>visible&&physical-visible<=4&&physical%4==0,"Upper layout boundary overflow");
            vectors.append(visible).append(' ').append(physical).append('\n');
        }
        for(int invalid:new int[]{Integer.MIN_VALUE,-1,0,Integer.MAX_VALUE-3,Integer.MAX_VALUE})rejected(invalid);
        if(args.length==1)Files.write(Paths.get(args[0]),vectors.toString().getBytes(StandardCharsets.US_ASCII));
        else check(args.length==0,"Expected zero arguments or a new native-vector output");
        System.out.println("Standalone visible-eye/transport layout checks passed");
    }
}
