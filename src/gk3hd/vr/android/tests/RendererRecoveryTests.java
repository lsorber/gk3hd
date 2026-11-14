package org.gk3hd.standalone;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

public final class RendererRecoveryTests {
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        String session="0123456789abcdef0123456789abcdef";
        String record="GK3HD_RENDERER_FAULT "+session;
        String exit="GK3HD_GUEST_EXIT "+session;
        Path log=Files.createTempFile("gk3hd-launch-",".log");
        try {
            Files.write(log,(record+"\r\nThe graphics runtime failed.\r\n").getBytes(StandardCharsets.US_ASCII));
            require(RendererRecovery.reported(log.toFile(),session),"Current Windows launcher failure was missed");
            require(!RendererRecovery.reported(log.toFile(),"f"+session.substring(1)),"Stale session triggered recovery");
            require(!RendererRecovery.reported(log.toFile(),null),"An unowned launch triggered recovery");
            Files.write(log,("prefix: "+record+"\n"+record).getBytes(StandardCharsets.US_ASCII));
            require(!RendererRecovery.reported(log.toFile(),session),"Prefixed or incomplete line triggered recovery");
            char[] large=new char[8192];Arrays.fill(large,'x');
            Files.write(log,(new String(large)+"\n"+record+"\n").getBytes(StandardCharsets.US_ASCII));
            require(RendererRecovery.reported(log.toFile(),session),"A long diagnostic prefix hid the fault");
            Files.write(log,("Normal child exit\n").getBytes(StandardCharsets.US_ASCII));
            require(!RendererRecovery.reported(log.toFile(),session),"Normal exit triggered recovery");
            require(RendererRecovery.reportedGuestExit(log.toFile(),session)==null,"Normal exit recorded a guest failure");
            Files.write(log,(record+"\r\n"+exit+" 2\r\n").getBytes(StandardCharsets.US_ASCII));
            require(RendererRecovery.reported(log.toFile(),session),"Guest exit hid confirmed graphics failure");
            require(Integer.valueOf(2).equals(RendererRecovery.reportedGuestExit(log.toFile(),session)),
                "Current guest launch's true exit status was missed");
            require(RendererRecovery.reportedGuestExit(log.toFile(),"f"+session.substring(1))==null,
                "Stale guest exit triggered recovery");
            require(RendererRecovery.reportedGuestExit(log.toFile(),"[")==null,"Invalid guest session was accepted");
            Files.write(log,("prefix: "+exit+" 2\n"+exit+" 0\n"+exit+" 2").getBytes(StandardCharsets.US_ASCII));
            require(RendererRecovery.reportedGuestExit(log.toFile(),session)==null,
                "Prefixed, successful or incomplete guest exit triggered recovery");
        } finally {
            Files.deleteIfExists(log);
        }
        require(!RendererRecovery.reported(log.toFile(),session),"An absent log triggered recovery");
        require(RendererRecovery.completes(true,session,session),"A completed retry must clear its own failure");
        require(!RendererRecovery.completes(true,session,"f"+session.substring(1)),"A stale retry cleared a newer failure");
        require(!RendererRecovery.completes(false,session,session),"A completed failure must not be handled again");
        require(RendererRecovery.completes(true,null,null),"A pending record without an identity must remain recoverable");
        require(!RendererRecovery.completes(true,null,session),"A retry of an unidentified fault cleared an identified failure");
        require(RendererRecovery.retryMessage(null).contains("graphics session"),"Confirmed graphics failures need specific guidance");
        require(RendererRecovery.retryMessage(-1).contains("could not start"),"A failed guest spawn needs startup guidance");
        require(RendererRecovery.retryMessage(7).contains("code 7"),"An abnormal guest exit needs its original status");
        System.out.println("Renderer recovery: exact session, complete record, bounded tail and normal exit passed");
    }
}
