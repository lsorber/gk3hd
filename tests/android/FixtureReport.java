package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** Single-writer fixture reports must never expose a truncated intermediate JSON. */
public final class FixtureReport {
    public static void write(File target,String text) throws IOException {
        Path path=target.toPath(),pending=path.resolveSibling(path.getFileName()+".pending");
        try {
            Files.write(pending,text.getBytes(StandardCharsets.UTF_8));
            Files.move(pending,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        } finally {Files.deleteIfExists(pending);}
    }
}
