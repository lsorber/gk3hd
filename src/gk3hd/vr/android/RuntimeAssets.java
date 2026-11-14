package org.gk3hd.standalone;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.json.JSONException;
import org.json.JSONObject;

/** Stock Winlator inputs are supplied by the USB installer and verified by the signed APK. */
public final class RuntimeAssets {
    private static final String MANIFEST = "gk3hd-runtime.json";
    private static final int MAX_METADATA = 4096;
    private static final int MAX_ENTRIES = 24;
    private static final long MAX_ARCHIVE = 128L * 1024 * 1024;
    private static final LinkOption NO_LINKS = LinkOption.NOFOLLOW_LINKS;

    private RuntimeAssets() {}

    private static MessageDigest digest() {
        try {return MessageDigest.getInstance("SHA-256");}
        catch(NoSuchAlgorithmException error) {throw new AssertionError(error);}
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for(byte value : bytes) result.append(String.format(Locale.ROOT, "%02x", value & 255));
        return result.toString();
    }

    private static final class Pin {
        final String identity;
        final JSONObject files;
        final List<String> names = new ArrayList<>();
        Pin(byte[] data) throws JSONException {
            identity = hex(digest().digest(data));
            files = new JSONObject(new String(data, StandardCharsets.UTF_8));
            if(files.length() < 2 || files.length() > MAX_ENTRIES ||
                    !files.has("rootfs.tzst") || !files.has("container_pattern.tzst"))
                throw new JSONException("Unexpected runtime archive list");
            long total = 0;
            for(java.util.Iterator<String> keys = files.keys(); keys.hasNext();) {
                String name = keys.next();
                if(!name.matches("(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\\.(?:tzst|sf2)"))
                    throw new JSONException("Unsafe runtime asset name");
                JSONObject entry = files.getJSONObject(name);
                long size = entry.getLong("size");
                if(size < 1 || size > MAX_ARCHIVE ||
                        !entry.getString("sha256").matches("[a-f0-9]{64}"))
                    throw new JSONException("Invalid runtime archive pin");
                total += size;
                names.add(name);
            }
            if(total > MAX_ARCHIVE) throw new JSONException("Runtime archive pin is too large");
        }
        long size(String name) {return files.optJSONObject(name).optLong("size");}
        String hash(String name) {return files.optJSONObject(name).optString("sha256");}
        File directory(Context context) {return new File(context.getFilesDir(), "gk3hd-runtime-" + identity);}
    }

    private static File payload(File directory, String name) {
        return new File(directory, name.replace('/', '!'));
    }

    private static Pin pin(Context context) throws IOException {
        try(InputStream input = context.getAssets().open(MANIFEST)) {
            ByteArrayOutputStream data = new ByteArrayOutputStream();
            byte[] buffer = new byte[1024];
            for(int n; (n = input.read(buffer)) != -1;) {
                if(data.size() + n > MAX_METADATA) throw new IOException("Runtime manifest is too large");
                data.write(buffer, 0, n);
            }
            return new Pin(data.toByteArray());
        } catch(FileNotFoundException absent) {
            return null; // Development APKs still embed these assets.
        } catch(JSONException invalid) {
            throw new IOException("Invalid Winlator runtime manifest", invalid);
        }
    }

    private static boolean complete(File directory, Pin pin) throws IOException {
        if(!Files.isDirectory(directory.toPath(), NO_LINKS)) return false;
        for(String name : pin.names) {
            File file = payload(directory, name);
            if(!Files.isRegularFile(file.toPath(), NO_LINKS) || file.length() != pin.size(name))
                return false;
        }
        File marker = new File(directory, MANIFEST);
        return Files.isRegularFile(marker.toPath(), NO_LINKS) &&
            marker.length() == receipt(pin).length &&
            MessageDigest.isEqual(Files.readAllBytes(marker.toPath()), receipt(pin));
    }

    private static byte[] receipt(Pin pin) {
        return ("{\"runtime\":\"" + pin.identity + "\"}").getBytes(StandardCharsets.UTF_8);
    }

    public static File installedReceipt(Context context) throws IOException {
        Pin pin = pin(context);
        if(pin == null || !complete(pin.directory(context), pin))
            throw new FileNotFoundException("Winlator runtime setup is incomplete");
        return new File(pin.directory(context), MANIFEST);
    }

    public static void requireInstalled(Context context) throws IOException {
        Pin pin = pin(context);
        if(pin != null && !complete(pin.directory(context), pin))
            throw new FileNotFoundException("Winlator runtime setup is incomplete");
    }

    public static InputStream open(Context context, String name) throws IOException {
        if(name.endsWith(".tzst") || name.endsWith(".sf2")) {
            Pin pin = pin(context);
            if(pin != null && pin.files.has(name)) {
                File directory = pin.directory(context);
                if(!complete(directory, pin))
                    throw new FileNotFoundException("Winlator runtime setup is incomplete");
                return Files.newInputStream(payload(directory, name).toPath(), NO_LINKS);
            }
        }
        return context.getAssets().open(name);
    }

    /** Keep the native Windows font and MFC overlays out of the Wine prefix. */
    public static File filterOverlay(File root, File destination) {
        String relative = root.toPath().relativize(destination.toPath().normalize()).toString();
        if(relative.toLowerCase(Locale.ROOT).matches(
                "home/[^/]+/\\.wine/drive_c/windows/(?:fonts(?:/.*)?|syswow64/mfc42\\.dll)"))
            return null;
        return destination;
    }

    public static void install(Context context, File archive) throws IOException {
        Pin pin = pin(context);
        if(pin == null) return;
        File target = pin.directory(context);
        if(complete(target, pin)) return;
        if(!Files.isRegularFile(archive.toPath(), NO_LINKS) || archive.length() > MAX_ARCHIVE)
            throw new IOException("Winlator runtime files are missing. Reconnect USB and run the same install command.");
        File stage = Files.createTempDirectory(context.getCacheDir().toPath(), "gk3hd-runtime-").toFile();
        try(ZipFile zip = new ZipFile(archive)) {
            if(zip.size() != pin.names.size()) throw new IOException("Unexpected files in Winlator runtime transfer");
            for(String name : pin.names) {
                File output = payload(stage, name);
                extract(zip, name, output, pin);
                DurableFiles.syncFile(output);
            }
            File marker = new File(stage, MANIFEST);
            Files.write(marker.toPath(), receipt(pin));
            DurableFiles.syncFile(marker);
            if(Files.isDirectory(target.toPath(), NO_LINKS))
                DurableFiles.exchange(stage, target, () -> {});
            else DurableFiles.publish(stage, target);
        } finally {
            for(String name : pin.names) Files.deleteIfExists(payload(stage, name).toPath());
            Files.deleteIfExists(new File(stage, MANIFEST).toPath());
            Files.deleteIfExists(stage.toPath());
        }
    }

    private static void extract(ZipFile zip, String name, File output, Pin pin) throws IOException {
        ZipEntry entry = zip.getEntry(name);
        long size = pin.size(name);
        if(entry == null || entry.getSize() != size || entry.getMethod() != ZipEntry.STORED)
            throw new IOException("Wrong Winlator runtime archive size: " + name);
        long copied = 0;
        MessageDigest hash = digest();
        try(InputStream input = zip.getInputStream(entry);
            OutputStream target = Files.newOutputStream(output.toPath())) {
            byte[] buffer = new byte[128 * 1024];
            for(int n; (n = input.read(buffer)) != -1;) {
                copied += n;
                if(copied > size) throw new IOException("Winlator runtime archive grew: " + name);
                target.write(buffer, 0, n);
                hash.update(buffer, 0, n);
            }
        }
        if(copied != size || !hex(hash.digest()).equals(pin.hash(name)))
            throw new IOException("Winlator runtime transfer failed verification. Run the same install command again.");
    }
}
