package org.gk3hd.standalone;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;

/** POSIX/Android filesystem regression, also runnable with a Linux JDK.
 * Windows open-file sharing does not model Android's atomic replacement. */
public final class FixtureReportTests {
    public static void main(String[] args) throws Exception {
        Path directory=Files.createTempDirectory("gk3hd-report-test-");
        Path report=directory.resolve("state.json");
        char[] padding=new char[131072];Arrays.fill(padding,'A');
        String large="{\"state\":\""+new String(padding)+"\"}",small="{\"state\":\"ready\"}";
        byte[] largeBytes=large.getBytes(StandardCharsets.UTF_8),smallBytes=small.getBytes(StandardCharsets.UTF_8);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread writer=new Thread(()->{
            try {for(int i=0;i<256;i++) FixtureReport.write(report.toFile(),i%2==0 ? large : small);}
            catch(Throwable error) {failure.set(error);}
        });
        try {
            FixtureReport.write(report.toFile(),small);
            writer.start();
            for(int i=0;i<1000;i++) {
                byte[] bytes=Files.readAllBytes(report);
                if(!Arrays.equals(bytes,largeBytes)&&!Arrays.equals(bytes,smallBytes))
                    throw new AssertionError("A reader observed a partial report");
            }
            writer.join();
            if(failure.get()!=null) throw new AssertionError("Report writer failed",failure.get());
            if(!Arrays.equals(Files.readAllBytes(report),smallBytes)) throw new AssertionError("Latest report lost");
            if(Files.exists(directory.resolve("state.json.pending"))) throw new AssertionError("Pending report leaked");
            System.out.println("Atomic fixture report: 256 replacements and 1000 complete reads passed");
        } finally {
            writer.join();
            Files.deleteIfExists(report);
            Files.deleteIfExists(directory.resolve("state.json.pending"));
            Files.delete(directory);
        }
    }
}
