package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;

/** Tiny owned filesystem trees; no game, prefix or headset session. */
public final class DurableFilesActivity extends Activity {
    private int checks;
    private void check(boolean valid,String reason) {checks++;if(!valid)throw new AssertionError(reason);}
    private static void write(File file,String text) throws Exception {
        Files.write(file.toPath(),text.getBytes(StandardCharsets.UTF_8));DurableFiles.syncFile(file);
    }
    private static String read(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);
    }
    private void exercise(File root) throws Exception {
        File target=new File(root,"target"),staged=new File(root,"staged");
        check(target.mkdir()&&staged.mkdir(),"fresh owned trees");
        write(new File(target,"program"),"old");write(new File(staged,"program"),"new");
        File save=new File(target,"save0001.gk3"),linked=new File(staged,"save0001.gk3");
        write(save,"saved progress");Files.createLink(linked.toPath(),save.toPath());
        boolean[] transferred={false};
        try {DurableFiles.publish(staged,target);throw new AssertionError("Fresh publication replaced an existing player");}
        catch(java.io.IOException expected) {check(read(new File(target,"program")).equals("old"),"failed fresh publication changed old player");}
        try {DurableFiles.exchange(target,target,()->transferred[0]=true);throw new AssertionError("Self exchange accepted");}
        catch(java.io.IOException expected) {check(!transferred[0],"rejected exchange transferred cleanup ownership");}
        File alias=new File(root,"alias");Files.createSymbolicLink(alias.toPath(),target.toPath());
        try {DurableFiles.exchange(staged,alias,()->transferred[0]=true);throw new AssertionError("Symbolic target accepted");}
        catch(java.io.IOException expected) {check(!transferred[0],"symbolic exchange transferred ownership");}
        DurableFiles.exchange(staged,target,()-> {
            transferred[0]=true;
            try {
                check(read(new File(target,"program")).equals("new")&&read(new File(staged,"program")).equals("old"),
                      "ownership callback ran before publication");
            }catch(Exception error){throw new IllegalStateException(error);}
        });
        check(transferred[0],"successful exchange omitted cleanup ownership transfer");
        check(read(save).equals("saved progress")&&Files.isSameFile(save.toPath(),linked.toPath()),
              "publication changed preserved save data or identity");
        Files.delete(linked.toPath());check(read(save).equals("saved progress"),"retiring old save alias deleted live progress");
        boolean[] interrupted={false};
        try {
            DurableFiles.exchange(staged,target,()-> {interrupted[0]=true;throw new IllegalStateException("after exchange");});
            throw new AssertionError("Post-publication interruption was hidden");
        }catch(IllegalStateException expected) {
            check(expected.getMessage().equals("after exchange")&&interrupted[0],"lost post-publication ownership");
        }
        check(read(new File(target,"program")).equals("old")&&read(new File(staged,"program")).equals("new"),
              "post-publication interruption removed a complete player");
        check(read(linked).equals("saved progress"),"interrupted exchange lost the remaining save link");
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[0-9a-f]{32}"))throw new IllegalArgumentException("Fresh filesystem fixture token required");
        new Thread(()-> {
            File root=null;JSONObject result=new JSONObject();
            try {
                root=Files.createTempDirectory(getCacheDir().toPath(),"gk3hd-files-").toFile();exercise(root);
                result.put("passed",true).put("checks",checks);
            }catch(Throwable error) {
                try {result.put("passed",false).put("error",error.toString());}
                catch(org.json.JSONException impossible){throw new IllegalStateException(impossible);}
            }finally {
                try {
                    if(root!=null)Files.walkFileTree(root.toPath(),new java.nio.file.SimpleFileVisitor<java.nio.file.Path>() {
                        @Override public java.nio.file.FileVisitResult visitFile(java.nio.file.Path file,java.nio.file.attribute.BasicFileAttributes attrs) throws java.io.IOException {
                            Files.delete(file);return java.nio.file.FileVisitResult.CONTINUE;
                        }
                        @Override public java.nio.file.FileVisitResult postVisitDirectory(java.nio.file.Path dir,java.io.IOException error) throws java.io.IOException {
                            if(error!=null)throw error;Files.delete(dir);return java.nio.file.FileVisitResult.CONTINUE;
                        }
                    });
                    result.put("token",token).put("fixture_retired",root==null||!root.exists())
                        .put("scope","Actual Java/JNI filesystem publication; synthetic bytes only, no player, prefix or headset session");
                    File output=new File(getFilesDir(),"durable-files-"+token+".json");
                    try(java.io.FileOutputStream out=new java.io.FileOutputStream(output)) {out.write(result.toString().getBytes(StandardCharsets.UTF_8));out.getFD().sync();}
                }catch(Exception error){android.util.Log.e("GK3HDFileTests","Fixture export/retirement failed",error);}
                runOnUiThread(this::finish);
            }
        },"GK3HDFileTests").start();
    }
}
