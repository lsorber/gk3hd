package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.FileSystemException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import org.json.JSONObject;
import com.winlator.core.WineRegistryEditor;

/** Replace verified managed bytes while preserving preferences and unlisted files. */
public final class StandaloneInstallation {
    private static final String MARKER=".gk3hd-standalone.json";
    private StandaloneInstallation() { }

    private static File player(File prefix) {return new File(prefix,"drive_c/gk3hd-vr");}

    public static boolean updatePending(File container) {
        return ComponentExchange.isPending(player(new File(container,".wine")));
    }

    public static void recover(File prefix) throws Exception {
        File target=player(prefix);
        if(!ComponentExchange.isPending(target))return;
        if(Files.isSymbolicLink(prefix.toPath())||Files.isSymbolicLink(target.getParentFile().toPath()))
            throw new IOException("Symbolic player prefix preserved");
        ComponentExchange.recover(target);
    }

    public static String publish(StandaloneBundle incoming,File prefix,StandaloneBundle.Progress progress) throws Exception {
        recover(prefix);
        File target=player(prefix);
        if(target.exists()||Files.isSymbolicLink(target.toPath()))return update(incoming,target,progress);
        if(incoming.componentUpdate)throw new IOException("A component update requires an existing GK3HD player");
        progress.update("configure",0,0);
        try(WineRegistryEditor registry=new WineRegistryEditor(new File(prefix,"system.reg"))) {
            for(String name:new String[]{"Software\\Khronos\\OpenXR\\1","Software\\Wow6432Node\\Khronos\\OpenXR\\1"})
                registry.setStringValue(name,"ActiveRuntime","C:\\gk3hd-vr\\openxr.json");
        }
        // Only a new player receives defaults. Updates never reset its prefix.
        try(WineRegistryEditor registry=new WineRegistryEditor(new File(prefix,"user.reg"))) {
            String engine="Software\\Sierra On-Line\\Gabriel Knight 3\\Engine";
            registry.setDwordValue(engine,"Full Screen",0);
            registry.setDwordValue(engine,"Game Width",1280);registry.setDwordValue(engine,"Screen Width",1280);
            registry.setDwordValue(engine,"Game Height",800);registry.setDwordValue(engine,"Screen Height",800);
            String hardware=engine+"\\Hardware";
            registry.setStringValue(hardware,"Gamma","1.000000");registry.setStringValue(hardware,"Surface Quality","High");
            registry.setDwordValue(hardware,"Incremental Rendering",0);registry.setDwordValue(hardware,"Interpolation",1);
            registry.setDwordValue(hardware,"Lod",100);registry.setDwordValue(hardware,"Mip Mapping",1);
            registry.setDwordValue(hardware,"Trilinear Filtering",1);
        }
        DurableFiles.syncFile(new File(prefix,"system.reg"));DurableFiles.syncFile(new File(prefix,"user.reg"));
        DurableFiles.syncDirectory(prefix);incoming.writeReceipt();
        DurableFiles.publish(new File(incoming.directory,"game"),target);
        return "Private GK3HD player installed";
    }
    private static String key(String name) {return name.toLowerCase(Locale.ROOT);}
    private static boolean mutable(String name) {return name.equalsIgnoreCase("GK3.ini")||name.equalsIgnoreCase("conf.txt");}
    private static File checkedPath(File root,String relative) throws IOException {
        if(!root.isDirectory()||Files.isSymbolicLink(root.toPath()))throw new IOException("Changed player directory preserved");
        File current=root;
        for(String part:relative.split("/")) {
            current=new File(current,part);
            if(Files.isSymbolicLink(current.toPath()))throw new IOException("Symbolic player path preserved: "+relative);
        }
        return current;
    }
    private static File checkedFile(File root,String relative) throws IOException {
        File current=checkedPath(root,relative);
        if(!current.isFile())throw new IOException("Missing or changed player file preserved: "+relative);
        return current;
    }
    static File ownershipReceipt(File container) throws IOException {
        return checkedFile(container,".wine/drive_c/gk3hd-vr/"+MARKER);
    }
    private static Map<String,String> index(JSONObject files) throws Exception {
        if(files.length()<StandaloneBundle.REQUIRED.length||files.length()>StandaloneBundle.MAX_ENTRIES)
            throw new IOException("Invalid player inventory; existing files preserved");
        Map<String,String> result=new HashMap<>();long total=0;
        for(java.util.Iterator<String> names=files.keys();names.hasNext();) {
            String name=names.next();JSONObject entry=files.getJSONObject(name);
            long size=entry.getLong("size");String digest=entry.getString("sha256");
            if(!StandaloneBundle.safeName(name)||size<0||size>StandaloneBundle.MAX_FILE||!digest.matches("[0-9a-f]{64}"))
                throw new IOException("Invalid player ownership entry; existing files preserved");
            total+=size;if(total>StandaloneBundle.MAX_TOTAL)throw new IOException("Player inventory exceeds storage bound");
            String prefix="";
            for(String part:name.substring(5).split("/")) {
                prefix=prefix.isEmpty()?part:prefix+"/"+part;
                String previous=result.put(key(prefix),prefix);
                if(previous!=null&&!previous.equals(prefix))throw new IOException("Conflicting player path case: "+prefix);
            }
        }
        for(String required:StandaloneBundle.REQUIRED)if(!files.has("game/"+required))
            throw new IOException("Incomplete player ownership record; existing files preserved");
        return result;
    }
    private static boolean matches(File file,JSONObject expected) throws Exception {
        return !Files.isSymbolicLink(file.toPath())&&file.isFile()&&file.length()==expected.getLong("size")&&
            StandaloneBundle.hash(file).equals(expected.getString("sha256"));
    }
    private static boolean sameContent(JSONObject first,JSONObject second) throws Exception {
        return first.getLong("size")==second.getLong("size")&&first.getString("sha256").equals(second.getString("sha256"));
    }
    private static ArrayList<String> componentChanges(JSONObject oldFiles,JSONObject newFiles) throws Exception {
        ArrayList<String> changed=new ArrayList<>();
        long bytes=0;
        for(java.util.Iterator<String> names=oldFiles.keys();names.hasNext();) {
            String name=names.next(),relative=name.substring(5);
            JSONObject oldFile=oldFiles.getJSONObject(name),newFile=newFiles.optJSONObject(name);
            if(newFile==null)throw new IOException("Installed bundle ownership differs");
            if(mutable(relative)||sameContent(oldFile,newFile))continue;
            changed.add(relative);
            bytes+=oldFile.getLong("size")+newFile.getLong("size");
        }
        if(oldFiles.length()!=newFiles.length()) {
            HashSet<String> parents=new HashSet<>();
            for(java.util.Iterator<String> names=oldFiles.keys();names.hasNext();) {
                String name=names.next();
                parents.add(name.substring(0,name.lastIndexOf('/')));
            }
            for(java.util.Iterator<String> names=newFiles.keys();names.hasNext();) {
                String name=names.next(),relative=name.substring(5);
                if(oldFiles.has(name))continue;
                if(mutable(relative)||!parents.contains(name.substring(0,name.lastIndexOf('/'))))
                    throw new IOException("Added component requires an existing managed directory: "+relative);
                changed.add(relative);
                bytes+=newFiles.getJSONObject(name).getLong("size");
            }
        }
        return ComponentExchange.eligible(changed.size(),bytes)?changed:new ArrayList<>();
    }
    private static void copyVerified(File installed,File staged,JSONObject expected,String relative) throws Exception {
        Files.createDirectories(staged.getParentFile().toPath());
        // Give the live and retired players separate copies. A later edit to
        // a retained old file must not mutate the newly published player.
        Files.copy(installed.toPath(),staged.toPath(),java.nio.file.LinkOption.NOFOLLOW_LINKS);
        if(!matches(staged,expected))throw new IOException("Changed managed file preserved: "+relative);
        DurableFiles.syncFile(staged);
    }
    private static Path destination(Path staged,Path relative,Map<String,String> cases) {
        String name="";
        for(Path component:relative) {
            String next=name.isEmpty()?component.toString():name+"/"+component;
            name=cases.getOrDefault(key(next),next);
        }
        return staged.resolve(name);
    }
    private static String preserve(Path source,Path destination) throws Exception {
        try {Files.createLink(destination,source);return null;}
        catch(FileSystemException|UnsupportedOperationException unavailable) {
            String digest=StandaloneBundle.hash(source.toFile());
            Files.copy(source,destination,java.nio.file.LinkOption.NOFOLLOW_LINKS);
            DurableFiles.syncFile(destination.toFile());
            if(!digest.equals(StandaloneBundle.hash(source.toFile()))||
               !digest.equals(StandaloneBundle.hash(destination.toFile())))
                throw new IOException("Preserved file changed during copying: "+source.getFileName());
            return digest;
        }
    }
    static String update(StandaloneBundle incoming,File target,StandaloneBundle.Progress progress) throws Exception {
        return update(incoming,target,progress,null);
    }
    // Deterministic post-publication fault seam; never a user option or runtime flag.
    static String update(StandaloneBundle incoming,File target,StandaloneBundle.Progress progress,Runnable afterPublication) throws Exception {
        if(!target.isDirectory()||Files.isSymbolicLink(target.toPath()))
            throw new IOException("Unmanaged player path preserved");
        File marker=checkedFile(target,MARKER);
        if(marker.length()>StandaloneBundle.MAX_MANIFEST+512)throw new IOException("Oversized player ownership record preserved");
        byte[] previousReceipt=Files.readAllBytes(marker.toPath());
        JSONObject previous=new JSONObject(new String(previousReceipt,StandardCharsets.UTF_8));
        if(previous.getInt("schema")!=1||!previous.getString("bundle_sha256").matches("[0-9a-f]{64}"))
            throw new IOException("Invalid player ownership record; existing files preserved");
        JSONObject oldFiles=previous.getJSONObject("files"),newFiles=incoming.manifest.getJSONObject("files");
        index(oldFiles);Map<String,String> cases=index(newFiles);
        boolean sameArchive=previous.getString("bundle_sha256").equals(incoming.archiveSha256);
        boolean verifyOnly=incoming.verificationOnly||sameArchive;
        if((verifyOnly||incoming.componentUpdate&&!incoming.componentAdditions)&&
           oldFiles.length()!=newFiles.length())
            throw new IOException("Installed bundle ownership differs");
        ArrayList<String> changes=incoming.componentUpdate&&!verifyOnly?
            componentChanges(oldFiles,newFiles):new ArrayList<>();
        if(incoming.componentAdditions&&!verifyOnly) {
            if(changes.isEmpty()||newFiles.length()<=oldFiles.length())
                throw new IOException("Added components exceed the journal's limits or require a fresh update");
            for(String relative:changes) {
                if(!oldFiles.has("game/"+relative)) {
                    checkedFile(incoming.directory,"game/"+relative);
                    ComponentExchange.requireVacant(target,relative);
                }
            }
        }
        long total=0;for(java.util.Iterator<String> names=oldFiles.keys();names.hasNext();)total+=oldFiles.getJSONObject(names.next()).getLong("size");
        long verified=0;
        for(java.util.Iterator<String> names=oldFiles.keys();names.hasNext();) {
            String name=names.next(),relative=name.substring(5);JSONObject expected=oldFiles.getJSONObject(name);
            File installed=checkedFile(target,relative);
            if((incoming.componentUpdate||sameArchive)&&!newFiles.has(name))
                throw new IOException("Installed bundle ownership differs");
            if(verifyOnly&&!sameContent(expected,newFiles.getJSONObject(name)))
                throw new IOException("Installed bundle ownership differs");
            boolean reuse=false;
            File staged=new File(incoming.directory,name);
            if(incoming.componentUpdate&&!verifyOnly) {
                reuse=sameContent(expected,newFiles.getJSONObject(name));
                if(reuse==staged.isFile())throw new IOException("Component update payload does not match installed inventory: "+relative);
            }
            if(!mutable(relative)) {
                if(reuse&&changes.isEmpty())copyVerified(installed,staged,expected,relative);
                else if(!matches(installed,expected))throw new IOException("Changed managed file preserved: "+relative);
            }
            verified+=expected.getLong("size");progress.update("update",verified,total);
        }
        if(verifyOnly)return "The same private player is already installed";
        progress.update("configure",0,0);
        if(!changes.isEmpty()) {
            incoming.writeReceipt();
            ComponentExchange.publish(target,new File(incoming.directory,"game"),changes,step->{});
            if(afterPublication!=null)afterPublication.run();
            return "Private GK3HD player updated; saves and preferences preserved";
        }
        Path root=target.toPath(),staged=new File(incoming.directory,"game").toPath();
        Map<Path,Path> preserved=new HashMap<>();ArrayList<Path> directories=new ArrayList<>();
        Map<Path,String> copied=new HashMap<>();
        HashSet<String> seen=new HashSet<>();
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            private int visited;
            private void entry(Path path,BasicFileAttributes attrs) throws IOException {
                if(++visited>40000||attrs.isSymbolicLink()||(!attrs.isDirectory()&&!attrs.isRegularFile()))
                    throw new IOException("Unsupported existing player entry preserved: "+path.getFileName());
                Path relative=root.relativize(path);
                if(!relative.toString().isEmpty()&&!seen.add(key(relative.toString())))
                    throw new IOException("Conflicting existing player path case; files preserved");
            }
            @Override public FileVisitResult preVisitDirectory(Path dir,BasicFileAttributes attrs) throws IOException {
                entry(dir,attrs);Files.createDirectories(destination(staged,root.relativize(dir),cases));
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes attrs) throws IOException {
                entry(file,attrs);Path relative=root.relativize(file);String name=relative.toString();
                if(name.equals(MARKER))return FileVisitResult.CONTINUE;
                String owned="game/"+name;Path destination=destination(staged,relative,cases);
                try {
                    boolean oldManaged=oldFiles.has(owned),keep=!oldManaged||mutable(name);
                    // Immutable managed files already have verified incoming bytes.
                    // Only settings and unlisted user files require preservation.
                    if(!keep)return FileVisitResult.CONTINUE;
                    if(Files.exists(destination)) {
                        if(!oldManaged&&!mutable(name))throw new IOException("Unmanaged file conflicts with update: "+name);
                        if(!Files.isRegularFile(destination)||Files.isSymbolicLink(destination))throw new IOException("Preserved file conflicts with updated directory: "+name);
                        Files.delete(destination); // Only the importer's verified incoming copy.
                    }
                    Files.createDirectories(destination.getParent());DurableFiles.syncFile(file.toFile());
                    String digest=preserve(file,destination);
                    if(digest!=null)copied.put(relative,digest);
                    preserved.put(relative,staged.relativize(destination));
                    return FileVisitResult.CONTINUE;
                }catch(IOException error){throw error;}
                catch(Exception error){throw new IOException("Cannot preserve installed file: "+name,error);}
            }
            @Override public FileVisitResult postVisitDirectory(Path dir,IOException error) throws IOException {
                if(error!=null)throw error;directories.add(root.relativize(dir));return FileVisitResult.CONTINUE;
            }
        });
        incoming.writeReceipt();
        File retired=new File(target.getParentFile(),"gk3hd-vr-retired-"+java.util.UUID.randomUUID());
        if(retired.exists()||Files.isSymbolicLink(retired.toPath()))throw new IOException("Retired player path is occupied");
        DurableFiles.exchange(staged.toFile(),target,()->incoming.retirePublishedGame(retired));
        if(afterPublication!=null)afterPublication.run();
        // Never recursively delete this old tree. Unexpected/changed files stay
        // in a stable sibling outside Android's disposable cache.
        for(java.util.Iterator<String> names=oldFiles.keys();names.hasNext();) {
            String name=names.next();Path relative=java.nio.file.Paths.get(name.substring(5));
            if(preserved.containsKey(relative))continue;
            try {
                File old=checkedFile(retired,name.substring(5));
                if(matches(old,oldFiles.getJSONObject(name)))Files.delete(old.toPath());
            }catch(IOException unexpected) { }
        }
        for(Map.Entry<Path,Path> link:preserved.entrySet()) {
            try {
                Path old=checkedFile(retired,link.getKey().toString()).toPath(),live=checkedFile(target,link.getValue().toString()).toPath();
                String digest=copied.get(link.getKey());
                if(Files.isSameFile(old,live)||digest!=null&&
                   digest.equals(StandaloneBundle.hash(old.toFile()))&&digest.equals(StandaloneBundle.hash(live.toFile())))
                    Files.delete(old);
            }catch(Exception unexpected) { }
        }
        try {
            File oldMarker=checkedFile(retired,MARKER);
            if(oldMarker.length()==previousReceipt.length&&java.util.Arrays.equals(previousReceipt,Files.readAllBytes(oldMarker.toPath())))Files.delete(oldMarker.toPath());
        }catch(IOException unexpected) { }
        for(Path relative:directories)try {
            File dir=checkedPath(retired,relative.toString());
            if(dir.isDirectory())Files.delete(dir.toPath());
        }catch(IOException unexpected) { }
        DurableFiles.syncDirectory(target.getParentFile());
        return retired.exists()?"Private player updated; unrecognized previous files preserved at "+retired:
            "Private GK3HD player updated; saves and preferences preserved";
    }
}
