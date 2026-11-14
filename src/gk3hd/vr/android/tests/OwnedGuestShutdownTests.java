package org.gk3hd.standalone;

import java.nio.charset.StandardCharsets;

/** Ownership matching is exact across Linux and Wine command-line spellings. */
public final class OwnedGuestShutdownTests {
    private static void check(boolean condition,String reason) {
        if(!condition)throw new AssertionError(reason);
    }
    public static void main(String[] args) {
        String own="0123456789abcdef0123456789abcdef",other="abcdef0123456789abcdef0123456789";
        byte[] environment=("A=B\0GK3HD_FRAME_SESSION="+own+"\0C=D\0").getBytes(StandardCharsets.ISO_8859_1);
        check(OwnedGuestShutdown.sessionMatches(environment,own),"Own exact namespace rejected");
        check(!OwnedGuestShutdown.sessionMatches(environment,other),"Another session authorized");
        check(!OwnedGuestShutdown.sessionMatches(environment,null),"Missing namespace authorized");
        check(!OwnedGuestShutdown.sessionMatches(environment,""),"Empty namespace authorized");
        check(!OwnedGuestShutdown.sessionMatches(environment,own.substring(1)),"Partial namespace authorized");
        check(!OwnedGuestShutdown.sessionMatches(("XGK3HD_FRAME_SESSION="+own+"\0").getBytes(StandardCharsets.ISO_8859_1),own),"Substring key authorized");
        check(!OwnedGuestShutdown.sessionMatches(("GK3HD_FRAME_SESSION="+own+"x\0").getBytes(StandardCharsets.ISO_8859_1),own),"Substring value authorized");
        check(OwnedGuestShutdown.launcherName("gk3hd-wine-launcher.exe"),"Bare launcher rejected");
        check(OwnedGuestShutdown.launcherName("C:\\gk3hd-vr\\GK3HD-WINE-LAUNCHER.EXE"),"Wine path rejected");
        check(OwnedGuestShutdown.launcherName("/private/player/gk3hd-wine-launcher.exe"),"Unix path rejected");
        check(!OwnedGuestShutdown.launcherName("other-gk3hd-wine-launcher.exe"),"Different executable authorized");
        check(!OwnedGuestShutdown.launcherName(null),"Missing executable authorized");
        for(String command:new String[]{
            "GK3-VR.exe\0",
            "C:\\gk3hd-vr\\GK3HD-WINE-LAUNCHER.EXE\0",
            "/opt/wine/bin/wine64-preloader\0C:\\gk3hd-vr\\GK3-VR.exe\0",
            "/private/bin/box64\0/opt/wine/bin/wine\0GK3-VR.exe\0"
        })check(OwnedGuestShutdown.playerCommand(command.getBytes(StandardCharsets.ISO_8859_1)),
            "Running player command missed");
        for(String command:new String[]{
            "", "wineserver\0", "other-gk3hd-wine-launcher.exe\0",
            "wine64\0GK3-VR.exe.bak\0", "/bin/checksum\0GK3-VR.exe\0"
        })check(!OwnedGuestShutdown.playerCommand(command.getBytes(StandardCharsets.ISO_8859_1)),
            "Unrelated process treated as a player");
        System.out.println("Owned guest shutdown identity tests passed; OS lifecycle remains a separate qualification");
    }
}
