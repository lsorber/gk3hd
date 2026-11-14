package org.gk3hd.standalone;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONException;
import org.json.JSONObject;

/** Actual Android persistence checks, confined to a disposable cache directory. */
public final class ContainerSettingsTests {
    public static void run(Context context) throws Exception {
        File directory=Files.createTempDirectory(context.getCacheDir().toPath(),"gk3hd-settings-").toFile();
        File file=new File(directory,".container");
        try {
            // Exercise the actual host's save path too, without registering or
            // altering any real game container.
            com.winlator.container.Container container=new com.winlator.container.Container(17);
            container.setRootDir(directory);container.setName("Gabriel’s game");
            container.putExtra("gk3hdManaged","1");container.saveData();
            JSONObject read=ContainerSettings.read(file);
            if(read.getInt("id")!=17||!read.getString("name").equals("Gabriel’s game")||
               !read.getJSONObject("extraData").getString("gk3hdManaged").equals("1"))
                throw new AssertionError("Settings did not survive a complete write");
            ContainerSettings.write(file,new JSONObject().put("id",1).put("name","Updated"));
            byte[] previous=Files.readAllBytes(file.toPath());
            // Simulate interruption after partial bytes reach storage, without
            // the writer's normal finish/failure cleanup. No real reboot needed.
            AtomicFile interrupted=new AtomicFile(file);
            try(FileOutputStream partial=interrupted.startWrite()) {
                partial.write("{partial".getBytes(StandardCharsets.UTF_8));partial.getFD().sync();
            }
            if(!ContainerSettings.read(file).getString("name").equals("Updated")||
               !Arrays.equals(previous,Files.readAllBytes(file.toPath())))
                throw new AssertionError("Interrupted update lost committed settings");
            boolean rejected=false;
            try {ContainerSettings.write(file,new JSONObject().put("large",new String(new char[1024*1024])));}
            catch(IOException expected) {rejected=true;}
            if(!rejected||!Arrays.equals(previous,Files.readAllBytes(file.toPath())))
                throw new AssertionError("Oversized update damaged committed settings");
            Files.write(file.toPath(),new byte[1024*1024]);rejected=false;
            try {ContainerSettings.read(file);}catch(IOException expected) {rejected=true;}
            if(!rejected) throw new AssertionError("Oversized settings were accepted");
            Files.write(file.toPath(),"invalid".getBytes(StandardCharsets.UTF_8));rejected=false;
            try {ContainerSettings.read(file);}catch(JSONException expected) {rejected=true;}
            if(!rejected||!new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8).equals("invalid"))
                throw new AssertionError("Invalid settings were accepted or silently reset");
        } finally {
            for(String name:new String[]{".container",".container.bak",".container.new"})
                Files.deleteIfExists(new File(directory,name).toPath());
            Files.deleteIfExists(directory.toPath());
        }
    }
}
