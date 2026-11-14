package org.gk3hd.standalone;

import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/** Bounded, synced container settings with interrupted-write recovery. */
public final class ContainerSettings {
    private static final int MAX_BYTES=64*1024;
    private ContainerSettings() { }

    public static synchronized JSONObject read(File file) throws IOException,JSONException {
        // openRead also recovers the platform's pending atomic-file backup.
        try(InputStream input=new AtomicFile(file).openRead();
            ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
            byte[] block=new byte[4096];int length;
            while((length=input.read(block))!=-1) {
                if(bytes.size()+length>MAX_BYTES) throw new IOException("Container settings exceed their size limit");
                bytes.write(block,0,length);
            }
            return new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
        }
    }

    public static synchronized void write(File file,JSONObject settings) throws IOException {
        byte[] bytes=settings.toString().getBytes(StandardCharsets.UTF_8);
        if(bytes.length>MAX_BYTES) throw new IOException("Container settings exceed their size limit");
        AtomicFile atomic=new AtomicFile(file);FileOutputStream output=null;
        try {
            output=atomic.startWrite();output.write(bytes);
            output.getFD().sync();atomic.finishWrite(output);
        } catch(IOException error) {
            atomic.failWrite(output);throw error;
        }
    }
}
