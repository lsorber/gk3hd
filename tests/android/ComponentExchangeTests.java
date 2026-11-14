package org.gk3hd.standalone;

import android.system.Os;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Map;
import java.util.function.IntConsumer;
import org.json.JSONObject;

/** Isolated fixture data. The runner may terminate the process at any checkpoint. */
public final class ComponentExchangeTests {
    private static final String RECEIPT=".gk3hd-standalone.json";
    private static final String FIRST="ddraw.dll",SECOND="Data/renderer.txt",UNCHANGED="Data/TEST.BRN";
    private static final String ADDED="Data/backdrop.BSP";

    private ComponentExchangeTests() {}

    private static void check(boolean ok,String message) {
        if(!ok)throw new AssertionError(message);
    }

    private static void write(File directory,String name,String value) throws IOException {
        File file=new File(directory,name);
        Files.createDirectories(file.getParentFile().toPath());
        Files.write(file.toPath(),value.getBytes(StandardCharsets.UTF_8));
    }

    private static String read(File directory,String name) throws IOException {
        return new String(Files.readAllBytes(new File(directory,name).toPath()),StandardCharsets.UTF_8);
    }

    private static void receipt(File directory,String tag) throws Exception {
        JSONObject files=new JSONObject();
        for(String name:new String[]{FIRST,SECOND,UNCHANGED,ADDED}) {
            File file=new File(directory,name);
            if(!file.exists())continue;
            files.put("game/"+name,new JSONObject().put("size",file.length()).put("sha256",StandaloneBundle.hash(file)));
        }
        String archive=tag.equals("old")?"0123456789abcdef":"fedcba9876543210";
        write(directory,RECEIPT,new JSONObject().put("schema",1)
            .put("bundle_sha256",archive+archive+archive+archive).put("files",files).toString());
    }

    private static File prepare(File root) throws Exception {
        File player=new File(root,"player"),incoming=new File(root,"incoming");
        Files.createDirectory(root.toPath());
        for(File directory:new File[]{player,incoming}) {
            String tag=directory.equals(player)?"old":"new";
            write(directory,FIRST,tag+" renderer");
            write(directory,SECOND,tag+" details");
            write(directory,UNCHANGED,"original game data");
            if(!directory.equals(player))write(directory,ADDED,"new backdrop");
            receipt(directory,tag);
        }
        write(player,"GK3.ini","user settings");
        write(player,"save0001.gk3","user save");
        write(root,"original-inode",Long.toString(Os.stat(new File(player,UNCHANGED).getPath()).st_ino));
        return player;
    }

    public static void publish(File root,IntConsumer checkpoint) throws Exception {
        File player=prepare(root);
        check(!ComponentExchange.isPending(player),"fresh fixture is pending");
        ComponentExchange.publish(player,new File(root,"incoming"),Arrays.asList(FIRST,SECOND,ADDED),step-> {
            check(ComponentExchange.isPending(player),"transaction is visible while incomplete");
            checkpoint.accept(step);
        });
    }

    public static void recover(File root,boolean committed,boolean interrupted) throws Exception {
        File player=new File(root,"player");
        check(ComponentExchange.isPending(player)==interrupted,"unexpected pending state before recovery");
        ComponentExchange.recover(player);
        ComponentExchange.recover(player);
        check(!ComponentExchange.isPending(player),"recovered update still pending");
        String tag=committed?"new":"old";
        check(read(player,FIRST).equals(tag+" renderer")&&read(player,SECOND).equals(tag+" details"),
            "recovery left mixed component bytes");
        check(committed?read(player,ADDED).equals("new backdrop"):!new File(player,ADDED).exists(),
            "recovery left the wrong added files");
        JSONObject receipt=new JSONObject(read(player,RECEIPT));
        check(receipt.getString("bundle_sha256").startsWith(committed?"fedc":"0123"),"recovery left wrong receipt");
        check(read(player,"GK3.ini").equals("user settings")&&read(player,"save0001.gk3").equals("user save"),
            "recovery changed preferences or saves");
        check(read(player,UNCHANGED).equals("original game data")&&
            Long.toString(Os.stat(new File(player,UNCHANGED).getPath()).st_ino).equals(read(root,"original-inode")),
            "recovery replaced unchanged game data");
    }

    public static void preserveUnknown(File root) throws Exception {
        try {
            publish(root,step->{if(step==1)throw new IllegalStateException("interrupted");});
            throw new AssertionError("expected interruption");
        } catch(IllegalStateException stopped) {
            check(stopped.getMessage().equals("interrupted"),"unexpected interruption");
        }
        File player=new File(root,"player");
        write(player,SECOND,"unknown changed bytes");
        try {
            ComponentExchange.recover(player);
            throw new AssertionError("unknown component accepted");
        } catch(IOException unknown) {
            check(unknown.getMessage().contains("Unrecognized component bytes"),"unexpected recovery failure");
        }
        check(ComponentExchange.isPending(player)&&read(player,FIRST).equals("new renderer")&&
            read(player,SECOND).equals("unknown changed bytes"),"failed recovery touched component files");
    }

    public static void preserveForeignAddition(File root) throws Exception {
        try {
            publish(root,step->{if(step==3)throw new IllegalStateException("interrupted");});
            throw new AssertionError("expected interruption");
        } catch(IllegalStateException stopped) {
            check(stopped.getMessage().equals("interrupted"),"unexpected interruption");
        }
        File player=new File(root,"player");
        Files.delete(new File(player,ADDED).toPath());
        write(player,ADDED,"new backdrop");
        try {
            ComponentExchange.recover(player);
            throw new AssertionError("foreign inode accepted");
        } catch(IOException unknown) {
            check(unknown.getMessage().contains("Unrecognized component bytes"),"unexpected recovery failure");
        }
        check(ComponentExchange.isPending(player)&&read(player,ADDED).equals("new backdrop")&&
            read(player,FIRST).equals("new renderer"),"failed recovery touched component files");
    }

    public static void preserveCaseAlias(File root) throws Exception {
        File player=prepare(root);
        File incoming=new File(root,"incoming");
        try {
            DurableFiles.moveNewFile(new File(incoming,FIRST),new File(player,FIRST));
            throw new AssertionError("exclusive move overwrote a live component");
        } catch(IOException expected) {
            check(read(player,FIRST).equals("old renderer")&&read(incoming,FIRST).equals("new renderer"),
                "exclusive move touched the occupied destination or the source");
        }
        String alias="Data/BACKDROP.BSP";
        write(player,alias,"user file");
        try {
            ComponentExchange.publish(player,new File(root,"incoming"),Arrays.asList(FIRST,ADDED),step->{});
            throw new AssertionError("case alias accepted");
        } catch(IOException conflict) {
            check(conflict.getMessage().contains("Unmanaged file conflicts"),"unexpected conflict failure");
        }
        check(!ComponentExchange.isPending(player)&&read(player,alias).equals("user file")&&
            read(player,FIRST).equals("old renderer"),"case conflict touched component files");
        String[] stages=root.list((directory,name)->name.startsWith("gk3hd-components-"));
        check(stages!=null&&stages.length==0,"rejected update left a private staging directory");
        Files.delete(new File(incoming,ADDED).toPath());
        receipt(incoming,"new");
        ComponentExchange.publish(player,incoming,Arrays.asList(FIRST,SECOND),step->{});
        check(!ComponentExchange.isPending(player)&&read(player,FIRST).equals("new renderer")&&
            read(player,SECOND).equals("new details")&&read(player,alias).equals("user file")&&
            read(player,"save0001.gk3").equals("user save")&&read(player,"GK3.ini").equals("user settings"),
            "retry did not preserve the original user files and install the replacement components");
    }

    public static void installAdditions(File root) throws Exception {
        Files.createDirectory(root.toPath());
        File player=new File(root,"player");
        Map<String,byte[]> desired=StandaloneBundleTests.files();
        File full=StandaloneBundleTests.zip(root,desired,"");
        StandaloneBundle.Progress quiet=(phase,done,total)->{};
        try(StandaloneBundle initial=StandaloneBundle.extract(full,root,StandaloneBundle.hash(full),quiet)) {
            initial.writeReceipt();
            DurableFiles.publish(new File(initial.directory,"game"),player);
        }
        write(player,"GK3.ini","user settings");
        write(player,"save0001.gk3","user save");
        File barn=new File(player,UNCHANGED);
        long inode=Os.stat(barn.getPath()).st_ino;
        Map<String,byte[]> payload=new java.util.LinkedHashMap<>();
        payload.put("game/"+FIRST,new byte[]{5});
        payload.put("game/"+ADDED,new byte[]{6});
        desired.putAll(payload);
        File missing=StandaloneBundleTests.additionsZip(root,desired,
            java.util.Collections.singletonMap("game/"+FIRST,payload.get("game/"+FIRST)));
        try(StandaloneBundle incoming=StandaloneBundle.extract(missing,root,StandaloneBundle.hash(missing),quiet)) {
            try {
                StandaloneInstallation.update(incoming,player,quiet);
                throw new AssertionError("missing addition accepted");
            } catch(IOException rejected) {
                check(rejected.getMessage().contains("Missing or changed player file"),"unexpected update rejection");
            }
        }
        check(!new File(player,ADDED).exists()&&!ComponentExchange.isPending(player),
              "incomplete update touched the player");
        File delta=StandaloneBundleTests.additionsZip(root,desired,payload);
        String identity=StandaloneBundle.hash(delta);
        for(int attempt=0;attempt<2;attempt++) {
            try(StandaloneBundle incoming=StandaloneBundle.extract(delta,root,identity,quiet)) {
                String result=StandaloneInstallation.update(incoming,player,quiet);
                check(result.contains(attempt==0?"updated":"already installed"),"update or retry failed");
            }
        }
        check(Arrays.equals(Files.readAllBytes(new File(player,FIRST).toPath()),payload.get("game/"+FIRST))&&
              Arrays.equals(Files.readAllBytes(new File(player,ADDED).toPath()),payload.get("game/"+ADDED)),
              "installed payload differs");
        check(read(player,"GK3.ini").equals("user settings")&&read(player,"save0001.gk3").equals("user save"),
              "install changed preferences or saves");
        check(Os.stat(barn.getPath()).st_ino==inode&&!ComponentExchange.isPending(player),
              "install replaced unchanged data or left a transaction pending");
    }
}
