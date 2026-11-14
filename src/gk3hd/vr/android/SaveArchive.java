package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.CheckedInputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

/** Only game saves are portable across independently signed players. */
final class SaveArchive {
    static final int MAX_ARCHIVE = 66 * 1024 * 1024;
    private static final int MAX_TOTAL = 64 * 1024 * 1024;
    private static final int MAX_FILE = 16 * 1024 * 1024;
    private static final int MAX_FILES = 10000;

    private SaveArchive() {}

    private static boolean saveName(String name) {
        return name.matches("(?i)(save[0-9]{4}|fastsave)\\.gk3");
    }

    private static Map<String,File> slots(File player) throws IOException {
        Map<String,File> result = new HashMap<>();
        File[] saves = player.listFiles((parent,name) -> saveName(name));
        if (saves == null) throw new IOException("Cannot list the standalone saves");
        for (File save : saves) {
            if (!Files.isRegularFile(save.toPath(),LinkOption.NOFOLLOW_LINKS) ||
                result.put(save.getName().toLowerCase(Locale.ROOT),save) != null)
                throw new IOException("Conflicting or redirected save preserved: " + save.getName());
        }
        return result;
    }

    static void exportSaves(File player, OutputStream output) throws IOException {
        List<Map.Entry<String,File>> saves = new ArrayList<>(slots(player).entrySet());
        saves.sort(Map.Entry.comparingByKey());
        long total = 0;
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            for (Map.Entry<String,File> slot : saves) {
                Path source = slot.getValue().toPath();
                long size = Files.size(source);
                total = boundedTotal(size,total);
                zip.putNextEntry(new ZipEntry(slot.getKey()));
                try (InputStream input = Files.newInputStream(source,LinkOption.NOFOLLOW_LINKS)) {
                    copy(input,zip,size);
                }
                zip.closeEntry();
            }
        }
    }

    static int restoreSaves(File player, File archive, File staging) throws Exception {
        Map<String,File> existing = slots(player);
        Map<String,File> incoming = new HashMap<>();
        long total = 0;
        try (ZipFile zip = new ZipFile(archive)) {
            if (zip.size() > MAX_FILES + 1) throw new IOException("Too many save files");
            java.util.Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                String name = entry.getName().toLowerCase(Locale.ROOT);
                if (!saveName(name) || entry.isDirectory() || incoming.containsKey(name))
                    throw new IOException("Invalid or duplicate save filename");
                total = boundedTotal(entry.getSize(),total);
                File destination = new File(staging,name);
                try (CheckedInputStream input = new CheckedInputStream(zip.getInputStream(entry),new CRC32());
                     OutputStream output = Files.newOutputStream(destination.toPath())) {
                    copy(input,output,entry.getSize());
                    if (input.getChecksum().getValue() != entry.getCrc())
                        throw new IOException("The save backup failed verification");
                }
                incoming.put(name,destination);
                File original = existing.get(name);
                if (original != null && (original.length() != entry.getSize() ||
                    !StandaloneBundle.hash(original).equals(StandaloneBundle.hash(destination))))
                    throw new IOException("A different save already exists: " + name + ". Existing saves were kept.");
            }
        }
        int added = 0;
        for (Map.Entry<String,File> entry : incoming.entrySet()) {
            if (existing.containsKey(entry.getKey())) continue;
            DurableFiles.syncFile(entry.getValue());
            DurableFiles.moveNewFile(entry.getValue(),new File(player,entry.getKey()));
            added++;
        }
        return added;
    }

    private static long boundedTotal(long size,long previous) throws IOException {
        if (size <= 0 || size > MAX_FILE || previous + size > MAX_TOTAL)
            throw new IOException("Save archive exceeds the supported size");
        return previous + size;
    }

    /** Copy the declared bytes only, including checking for a truncated stream. */
    private static void copy(InputStream input,OutputStream output,long expected) throws IOException {
        byte[] block = new byte[64 * 1024];
        long copied = 0;
        for (int size; (size = input.read(block)) != -1;) {
            copied += size;
            if (copied > expected) throw new IOException("Save length changed");
            output.write(block,0,size);
        }
        if (copied != expected) throw new IOException("Save length changed");
    }
}
