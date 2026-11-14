package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.Objects;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Recovery signals for the current standalone session. */
public final class RendererRecovery {
    public static final String PREFERENCES = "gk3hd-recovery";
    public static final String PENDING = "renderer_failure_pending";
    public static final String FAILED_SESSION = "renderer_failed_session";
    public static final String GUEST_EXIT_STATUS = "guest_exit_status";
    public static final String ORDINARY_RESTART = "gk3hd_restart_with_ordinary_graphics";
    static final long STEREO_TIMEOUT_NS=5_000_000_000L;
    private static final int LOG_TAIL_LIMIT = 4096;

    private RendererRecovery() {}

    public static boolean completes(boolean pending, String attemptedFailure, String currentFailure) {
        return pending && Objects.equals(attemptedFailure, currentFailure);
    }

    public static String retryMessage(Integer guestStatus) {
        if (guestStatus == null)
            return "The graphics session stopped. Start again with compatibility settings, then restore your last save.";
        if (guestStatus == -1)
            return "The game could not start. If it happens again, reconnect USB and run "
                +"uvx gk3hd@latest vr standalone install on your PC.";
        return "The game stopped (code "+guestStatus+"). Start again and restore your last save.";
    }

    public static final class StereoTimeout extends IllegalStateException {
        private static final long serialVersionUID=1L;

        StereoTimeout(String operation) {super(operation+" did not complete within five seconds");}
    }

    public static boolean reported(File log, String session) throws IOException {
        return tail(log,session).contains("\nGK3HD_RENDERER_FAULT " + session + "\n");
    }

    public static Integer reportedGuestExit(File log, String session) throws IOException {
        String text=tail(log,session);
        if(text.isEmpty())return null;
        Pattern marker=Pattern.compile("\nGK3HD_GUEST_EXIT " + session + " ([1-9][0-9]{0,8})\n");
        Matcher result=marker.matcher(text);
        return result.find() ? Integer.valueOf(result.group(1)) : null;
    }

    private static String tail(File log, String session) throws IOException {
        if (session == null || !session.matches("[a-f0-9]{32}") ||
                !Files.isRegularFile(log.toPath(), LinkOption.NOFOLLOW_LINKS)) return "";
        try (RandomAccessFile input = new RandomAccessFile(log, "r")) {
            long length = input.length();
            byte[] tail = new byte[(int)Math.min(length, LOG_TAIL_LIMIT)];
            input.seek(length - tail.length);
            input.readFully(tail);
            String text = new String(tail, StandardCharsets.US_ASCII).replace("\r\n", "\n");
            return length <= tail.length ? "\n" + text : text;
        }
    }
}
