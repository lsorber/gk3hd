package org.gk3hd.standalone;

import android.app.Activity;
import android.os.Bundle;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real importer, registry publisher and updater on tiny non-executable fixtures. */
public final class StandaloneInstallationActivity extends Activity {
    private int checks;
    private final JSONArray scenarios=new JSONArray();
    private File staging;
    private boolean copyPreservationObserved;
    private boolean lateCopyPreserved;
    private final StandaloneBundle.Progress quiet=(stage,done,total)->{};
    private void check(boolean valid,String reason) {checks++;if(!valid)throw new AssertionError(reason);}
    private static byte[] bytes(String text) {return text.getBytes(StandardCharsets.UTF_8);}
    private static void write(File file,String text) throws Exception {
        Files.createDirectories(file.getParentFile().toPath());Files.write(file.toPath(),bytes(text));DurableFiles.syncFile(file);
    }
    private static String read(File file) throws Exception {return new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);}
    private static String identity(File target) throws Exception {
        return new JSONObject(read(new File(target,".gk3hd-standalone.json"))).getString("bundle_sha256");
    }
    private StandaloneBundle unpack(File archive,File root) throws Exception {
        return StandaloneBundle.extract(archive,staging,StandaloneBundle.hash(archive),quiet);
    }
    private String publish(File archive,File root,File prefix) throws Exception {
        try(StandaloneBundle incoming=unpack(archive,root)) {return StandaloneInstallation.publish(incoming,prefix,quiet);}
    }
    private Set<File> retired(File target) {
        Set<File> result=new HashSet<>();File[] files=target.getParentFile().listFiles();
        if(files!=null)for(File file:files)if(file.getName().startsWith("gk3hd-vr-retired-"))result.add(file);
        return result;
    }
    private File newRetired(File target,Set<File> before) {
        Set<File> after=retired(target);after.removeAll(before);check(after.size()==1,"unexpected retirement identity");return after.iterator().next();
    }
    private void rejected(File archive,File root,File prefix,File target,String expected) throws Exception {
        String previous=identity(target);byte[] save=Files.readAllBytes(new File(target,"save0001.gk3").toPath());
        boolean rejected=false;
        try {publish(archive,root,prefix);}
        catch(Exception error) {rejected=error.getMessage().contains(expected);}
        check(rejected,"update did not reject "+expected);
        check(identity(target).equals(previous)&&Arrays.equals(save,Files.readAllBytes(new File(target,"save0001.gk3").toPath())),
              "rejected update changed player identity or save");
    }
    private void exercise(File root) throws Exception {
        File prefix=new File(root,"prefix"),target=new File(prefix,"drive_c/gk3hd-vr");
        check(new File(prefix,"drive_c").mkdirs(),"fresh fixture prefix");
        write(new File(prefix,"system.reg"),"WINE REGISTRY Version 2\n\n");
        write(new File(prefix,"user.reg"),"WINE REGISTRY Version 2\n\n");
        Map<String,byte[]> old=StandaloneBundleTests.files();
        old.put("game/conf.txt",bytes("original bindings"));old.put("game/old/managed.bmp",bytes("old asset"));
        File first=StandaloneBundleTests.zip(root,old,"");
        check(publish(first,root,prefix).contains("installed"),"fresh public publisher failed");
        check(read(new File(prefix,"system.reg")).contains("ActiveRuntime"),"fresh runtime defaults not configured");
        scenarios.put("fresh installation through setup's publication entry");
        write(new File(target,"GK3.ini"),"CUSTOM PATHS = my textures\n");write(new File(target,"conf.txt"),"my controller bindings");
        write(new File(target,"save0001.gk3"),"player progress");write(new File(target,"notes/readme.txt"),"my notes");
        write(new File(prefix,"user.reg"),"WINE REGISTRY Version 2\n\n[MyPreferences]\n\"Gamma\"=\"1.7\"\n");
        byte[] registry=Files.readAllBytes(new File(prefix,"user.reg").toPath());
        check(publish(first,root,prefix).contains("already installed"),"identical bundle was not verified");
        check(read(new File(target,"conf.txt")).equals("my controller bindings"),"verification reset bindings");
        scenarios.put("identical bundle preserves mutable preferences");
        Map<String,byte[]> next=new LinkedHashMap<>(old);next.put("game/GK3-VR.exe",bytes("new program"));
        next.remove("game/old/managed.bmp");next.put("game/new.bmp",bytes("new asset"));
        File second=StandaloneBundleTests.zip(root,next,"");
        check(publish(second,root,prefix).contains("updated"),"changed bundle was not published");
        check(read(new File(target,"GK3-VR.exe")).equals("new program")&&new File(target,"new.bmp").isFile()&&
              !new File(target,"old/managed.bmp").exists(),"managed update/addition/removal failed");
        check(read(new File(target,"save0001.gk3")).equals("player progress")&&read(new File(target,"notes/readme.txt")).equals("my notes"),"user files lost");
        check(read(new File(target,"GK3.ini")).equals("CUSTOM PATHS = my textures\n")&&read(new File(target,"conf.txt")).equals("my controller bindings"),"preferences reset");
        check(Arrays.equals(registry,Files.readAllBytes(new File(prefix,"user.reg").toPath())),"update reset registry");
        check(retired(target).isEmpty(),"normal update left a retired tree");
        scenarios.put("update/add/remove managed files with saves, settings and notes preserved");
        write(new File(target,"ddraw.dll"),"my renderer");rejected(first,root,prefix,target,"Changed managed file");
        Files.write(new File(target,"ddraw.dll").toPath(),next.get("game/ddraw.dll"));
        scenarios.put("changed managed file leaves existing player intact");
        Map<String,byte[]> collision=new LinkedHashMap<>(next);collision.put("game/future.txt",bytes("official new asset"));
        write(new File(target,"future.txt"),"my existing file");
        rejected(StandaloneBundleTests.zip(root,collision,""),root,prefix,target,"Unmanaged file conflicts");
        check(read(new File(target,"future.txt")).equals("my existing file"),"collision overwrote user file");Files.delete(new File(target,"future.txt").toPath());
        scenarios.put("unmanaged collision rejected before publication");
        File outside=new File(root,"outside/managed.bmp");write(outside,"outside user data");
        File symbolic=new File(target,"external");Files.createSymbolicLink(symbolic.toPath(),outside.toPath());
        rejected(first,root,prefix,target,"Unsupported existing player entry");Files.delete(symbolic.toPath());
        check(read(outside).equals("outside user data"),"symbolic path escaped installation");
        scenarios.put("existing symbolic link rejected without following it");
        Map<String,byte[]> third=new LinkedHashMap<>(next);third.put("game/GK3-VR.exe",bytes("third program"));
        third.put("game/obsolete/managed.bmp",bytes("obsolete asset"));
        File thirdArchive=StandaloneBundleTests.zip(root,third,"");Set<File> before=retired(target);File incomingDirectory;
        try(StandaloneBundle incoming=unpack(thirdArchive,root)) {
            incomingDirectory=incoming.directory;
            try {StandaloneInstallation.update(incoming,target,quiet,()->{throw new IllegalStateException("after publication");});throw new AssertionError("interruption hidden");}
            catch(IllegalStateException expected) {check(expected.getMessage().equals("after publication"),"unexpected interruption");}
        }
        File preserved=newRetired(target,before);
        copyPreservationObserved=!Files.isSameFile(new File(preserved,"save0001.gk3").toPath(),new File(target,"save0001.gk3").toPath());
        check(!incomingDirectory.exists()&&read(new File(target,"GK3-VR.exe")).equals("third program"),"publication/cleanup ownership lost");
        check(read(new File(preserved,"save0001.gk3")).equals("player progress")&&read(new File(target,"save0001.gk3")).equals("player progress"),"interruption lost old or live progress");
        check(publish(thirdArchive,root,prefix).contains("already installed")&&preserved.isDirectory(),"retry damaged retained prior player");
        scenarios.put("interrupted publication preserves complete players and supports retry");
        Map<String,byte[]> fourth=new LinkedHashMap<>(third);fourth.put("game/GK3-VR.exe",bytes("fourth program"));
        fourth.put("game/ddraw.dll",bytes("new renderer"));fourth.remove("game/obsolete/managed.bmp");
        File fourthArchive=StandaloneBundleTests.zip(root,fourth,"");Set<File> prior=retired(target);String message;
        try(StandaloneBundle incoming=unpack(fourthArchive,root)) {
            message=StandaloneInstallation.update(incoming,target,quiet,()-> {
                try {
                    File previous=newRetired(target,prior);write(new File(previous,"late-notes.txt"),"unreviewed notes");
                    write(new File(previous,"ddraw.dll"),"unreviewed renderer");
                    File oldNotes=new File(previous,"notes/readme.txt"),liveNotes=new File(target,"notes/readme.txt");
                    if(!Files.isSameFile(oldNotes.toPath(),liveNotes.toPath())) {
                        write(oldNotes,"notes changed after publication");lateCopyPreserved=true;
                    }
                    File dir=new File(previous,"obsolete");Files.delete(new File(dir,"managed.bmp").toPath());Files.delete(dir.toPath());
                    Files.createSymbolicLink(dir.toPath(),outside.getParentFile().toPath());
                }catch(Exception error){throw new IllegalStateException(error);}
            });
        }
        File review=newRetired(target,prior);
        check(message.contains("unrecognized")&&read(new File(review,"late-notes.txt")).equals("unreviewed notes"),"late unlisted file discarded");
        check(read(new File(review,"ddraw.dll")).equals("unreviewed renderer")&&read(new File(target,"ddraw.dll")).equals("new renderer"),"late managed modification discarded or published");
        if(lateCopyPreserved)check(read(new File(review,"notes/readme.txt")).equals("notes changed after publication")&&
            read(new File(target,"notes/readme.txt")).equals("my notes"),"retirement discarded changed copied notes or changed the live snapshot");
        check(Files.isSymbolicLink(new File(review,"obsolete").toPath())&&read(outside).equals("outside user data"),"retirement followed or removed late symbolic directory");
        check(Arrays.equals(registry,Files.readAllBytes(new File(prefix,"user.reg").toPath())),"later update changed registry");
        scenarios.put("retirement preserves late files/modifications and never follows a symbolic directory");
    }
    private void componentUpdate(File root) throws Exception {
        File prefix=new File(root,"component-prefix"),target=new File(prefix,"drive_c/gk3hd-vr");
        check(target.getParentFile().mkdirs(),"fresh component fixture prefix");
        String registry="WINE REGISTRY Version 2\n\n";
        write(new File(prefix,"system.reg"),registry);write(new File(prefix,"user.reg"),registry);
        Map<String,byte[]> original=StandaloneBundleTests.files(),next=new LinkedHashMap<>(original);
        String launcher="game/gk3hd-wine-launcher.exe",renderer="game/ddraw.dll",ini="game/GK3.ini";
        next.put(launcher,bytes("new launcher"));next.put(renderer,bytes("new renderer"));
        Map<String,byte[]> replacements=new LinkedHashMap<>();
        replacements.put(launcher,next.get(launcher));replacements.put(renderer,next.get(renderer));
        File component=StandaloneBundleTests.componentZip(root,next,replacements);
        boolean freshRejected=false;
        try {publish(component,root,prefix);}
        catch(java.io.IOException error) {freshRejected=error.getMessage().contains("existing GK3HD player");}
        check(freshRejected&&!target.exists()&&read(new File(prefix,"user.reg")).equals(registry),"component archive created a fresh player");
        publish(StandaloneBundleTests.zip(root,original,""),root,prefix);
        write(new File(target,"GK3.ini"),"personal paths");write(new File(target,"save0001.gk3"),"personal save");
        rejected(StandaloneBundleTests.componentZip(root,next,java.util.Collections.singletonMap(launcher,next.get(launcher))),
            root,prefix,target,"Component update payload does not match");
        Map<String,byte[]> extra=new LinkedHashMap<>(replacements);extra.put(ini,original.get(ini));
        rejected(StandaloneBundleTests.componentZip(root,next,extra),root,prefix,target,"Component update payload does not match");
        Map<String,byte[]> corrupt=new LinkedHashMap<>(replacements);corrupt.put(renderer,bytes("bad renderer"));
        rejected(StandaloneBundleTests.componentZip(root,next,corrupt),root,prefix,target,"failed integrity verification");
        Map<String,byte[]> different=new LinkedHashMap<>(next);different.put("game/extra.bmp",bytes("extra"));
        rejected(StandaloneBundleTests.componentZip(root,different,replacements),root,prefix,target,"ownership differs");
        File barn=new File(target,"Data/TEST.BRN");
        Files.write(barn.toPath(),new byte[]{4,3,2,1});
        File verification=StandaloneBundleTests.verificationZip(root,original);
        rejected(verification,root,prefix,target,"Changed managed file");
        rejected(component,root,prefix,target,"Changed managed file");
        check(Arrays.equals(Files.readAllBytes(barn.toPath()),new byte[]{4,3,2,1}),"failed component update modified corrupt source");
        Files.write(barn.toPath(),original.get("game/Data/TEST.BRN"));
        rejected(StandaloneBundleTests.verificationZip(root,next),root,prefix,target,"ownership differs");
        Set<File> before=retired(target);
        String installed=identity(target);
        check(publish(verification,root,prefix).contains("already installed")&&identity(target).equals(installed)
            &&retired(target).equals(before)&&read(new File(target,"GK3.ini")).equals("personal paths")
            &&read(new File(target,"save0001.gk3")).equals("personal save"),"Verification replaced the installed player");
        long originalInode=android.system.Os.stat(barn.getPath()).st_ino;
        check(publish(component,root,prefix).contains("updated"),"component publication failed");
        check(read(new File(target,"gk3hd-wine-launcher.exe")).equals("new launcher")&&read(new File(target,"ddraw.dll")).equals("new renderer"),"replacement bytes not published");
        check(read(new File(target,"GK3.ini")).equals("personal paths")&&read(new File(target,"save0001.gk3")).equals("personal save"),"component update lost settings or save");
        check(Arrays.equals(Files.readAllBytes(barn.toPath()),original.get("game/Data/TEST.BRN"))&&
              android.system.Os.stat(barn.getPath()).st_ino==originalInode,"component update replaced unchanged data");
        check(publish(component,root,prefix).contains("already installed"),"component retry failed");
        Map<String,byte[]> finalFiles=new LinkedHashMap<>(next);finalFiles.put(renderer,bytes("final renderer"));
        File last=StandaloneBundleTests.componentZip(root,finalFiles,java.util.Collections.singletonMap(renderer,finalFiles.get(renderer)));
        check(publish(last,root,prefix).contains("updated")&&read(new File(target,"ddraw.dll")).equals("final renderer"),"normal component publication failed");
        check(retired(target).equals(before)&&!ComponentExchange.isPending(target),"normal component update left a retired or pending player");
        scenarios.put("component update validates reused bytes, preserves saves, publishes atomically and supports retry");
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);String token=getIntent().getStringExtra("token");
        if(token==null||!token.matches("[0-9a-f]{32}"))throw new IllegalArgumentException("Fresh upgrade fixture token required");
        new Thread(()-> {
            File root=null;JSONObject result=new JSONObject();
            try {
                staging=Files.createTempDirectory(getCacheDir().toPath(),"gk3hd-upgrade-stage-").toFile();
                root=Files.createTempDirectory(getFilesDir().toPath(),"gk3hd-upgrade-files-").toFile();exercise(root);
                componentUpdate(root);
                result.put("passed",true).put("checks",checks).put("scenarios",scenarios)
                    .put("copy_preservation_observed",copyPreservationObserved).put("late_copy_preserved",lateCopyPreserved);
            }catch(Throwable error) {
                try {result.put("passed",false).put("error",error.toString()).put("scenarios",scenarios);}
                catch(org.json.JSONException impossible){throw new IllegalStateException(impossible);}
            }finally {
                try {
                    for(File owned:new File[]{root,staging})if(owned!=null)Files.walkFileTree(owned.toPath(),new java.nio.file.SimpleFileVisitor<java.nio.file.Path>() {
                        @Override public java.nio.file.FileVisitResult visitFile(java.nio.file.Path file,java.nio.file.attribute.BasicFileAttributes attrs) throws java.io.IOException {
                            Files.delete(file);return java.nio.file.FileVisitResult.CONTINUE;
                        }
                        @Override public java.nio.file.FileVisitResult postVisitDirectory(java.nio.file.Path dir,java.io.IOException error) throws java.io.IOException {
                            if(error!=null)throw error;Files.delete(dir);return java.nio.file.FileVisitResult.CONTINUE;
                        }
                    });
                    result.put("token",token).put("fixture_retired",(root==null||!root.exists())&&(staging==null||!staging.exists()))
                        .put("scope","Actual setup publication entry and Java/JNI importer/updater; tiny synthetic payloads, no game or registered container");
                    File output=new File(getFilesDir(),"installation-"+token+".json");
                    if(!output.createNewFile())throw new IllegalStateException("Preserve an existing fixture report");
                    try(java.io.FileOutputStream out=new java.io.FileOutputStream(output)) {out.write(result.toString().getBytes(StandardCharsets.UTF_8));out.getFD().sync();}
                }catch(Exception error){android.util.Log.e("GK3HDInstallTests","Fixture export/cleanup failed",error);}
                runOnUiThread(this::finish);
            }
        },"GK3HDInstallTest").start();
    }
}
