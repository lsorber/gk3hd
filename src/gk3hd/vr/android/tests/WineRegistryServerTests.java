package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/** Immutable cache updates preserve the original Wine executable and other versions. */
public final class WineRegistryServerTests {
    private WineRegistryServerTests() { }
    private static byte[] image(int variant) {
        byte[] bytes=new byte[64];byte[] header={127,'E','L','F',2,1};
        System.arraycopy(header,0,bytes,0,header.length);bytes[16]=3;bytes[18]=62;bytes[32]=(byte)variant;
        return bytes;
    }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory("gk3hd-wine-server-test-");
        Path bin=root.resolve("opt/wine/bin");Files.createDirectories(bin);
        Path original=bin.resolve("wineserver");Files.write(original,new byte[]{1,2,3});
        byte[] first=image(1),second=image(2);String firstHash=WineRegistryServer.hash(first);
        File one=WineRegistryServer.prepare(root.toFile(),first,firstHash);
        if(!Arrays.equals(first,Files.readAllBytes(one.toPath()))||!one.canExecute())
            throw new AssertionError("First executable was not published exactly");
        if(!WineRegistryServer.prepare(root.toFile(),first,firstHash).equals(one))
            throw new AssertionError("Existing immutable version was not reused");
        File two=WineRegistryServer.prepare(root.toFile(),second,WineRegistryServer.hash(second));
        if(one.equals(two)||!Arrays.equals(first,Files.readAllBytes(one.toPath()))||
           !Arrays.equals(new byte[]{1,2,3},Files.readAllBytes(original)))
            throw new AssertionError("Updating the server changed another owned executable");
        try {WineRegistryServer.activate(root.toFile(),two);throw new AssertionError("Unknown original server overwritten");}
        catch(IOException expected) { }
        if(!Arrays.equals(new byte[]{1,2,3},Files.readAllBytes(original)))
            throw new AssertionError("Unexpected original server content was lost");
        Files.write(original,first);
        WineRegistryServer.activate(root.toFile(),two);
        WineRegistryServer.activate(root.toFile(),two);
        if(Files.isSymbolicLink(original)||!Arrays.equals(second,Files.readAllBytes(original))||
           !original.toFile().canExecute()||!Arrays.equals(first,Files.readAllBytes(one.toPath())))
            throw new AssertionError("Selecting an update lost the regular executable or prior version");
        byte[] corrupt=first.clone();corrupt[32]++;
        try {WineRegistryServer.prepare(root.toFile(),corrupt,firstHash);throw new AssertionError("Corruption accepted");}
        catch(IOException expected) { }
        byte[] arm=image(3);arm[18]=(byte)183;
        try {WineRegistryServer.prepare(root.toFile(),arm,WineRegistryServer.hash(arm));throw new AssertionError("Wrong CPU accepted");}
        catch(IOException expected) { }
        Files.write(one.toPath(),new byte[]{9});
        try {WineRegistryServer.prepare(root.toFile(),first,firstHash);throw new AssertionError("Changed cache overwritten");}
        catch(IOException expected) { }
        if(!Arrays.equals(new byte[]{9},Files.readAllBytes(one.toPath())))
            throw new AssertionError("Unexpected cache content was lost");
        System.out.println("Wine server immutable publication: 8 behavior checks passed");
    }
}
