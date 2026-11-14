package org.gk3hd.standalone;

import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.function.IntConsumer;
import org.json.JSONArray;
import org.json.JSONObject;

/** Durable file swaps. Call only with exclusive player access and verified inventories. */
final class ComponentExchange {
    private static final String PENDING=".gk3hd-component-pending";
    private static final String RECEIPT=".gk3hd-standalone.json";
    private static final String JOURNAL="journal.json";
    private static final String ADDITION_OWNER="user.gk3hd.component";
    private static final int MAX_CHANGES=32,MAX_JOURNAL=32*1024;
    private static final long MAX_BYTES=64L*1024*1024;

    private ComponentExchange() {}

    private static File pending(File player) {return new File(player.getParentFile(),PENDING);}

    static boolean isPending(File player) {
        // Treat an unreadable path as occupied too.
        return !Files.notExists(pending(player).toPath(),LinkOption.NOFOLLOW_LINKS);
    }

    static boolean eligible(int changes,long bytes) {
        return changes>0&&changes<=MAX_CHANGES&&bytes<=2*MAX_BYTES;
    }

    private static boolean regular(File file) {
        return Files.isRegularFile(file.toPath(),LinkOption.NOFOLLOW_LINKS);
    }

    private static boolean allowed(String relative) {
        return StandaloneBundle.safeName("game/"+relative)&&
            !relative.equalsIgnoreCase("GK3.ini")&&!relative.equalsIgnoreCase("conf.txt");
    }

    private static File checkedFile(File root,String relative) throws IOException {
        if(!Files.isDirectory(root.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid component directory");
        File file=root;
        for(String part:relative.split("/")) {
            file=new File(file,part);
            if(Files.isSymbolicLink(file.toPath()))throw new IOException("Symbolic component path preserved");
        }
        if(!regular(file))throw new IOException("Missing or invalid component file preserved");
        return file;
    }

    private static File additionPath(File root,String relative) throws IOException {
        File file=root;
        for(String part:relative.split("/")) {
            if(!Files.isDirectory(file.toPath(),LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Invalid component directory");
            String[] siblings=file.list();
            if(siblings==null)throw new IOException("Cannot read component directory");
            for(String sibling:siblings)if(sibling.equalsIgnoreCase(part)&&!sibling.equals(part))
                throw new IOException("Unmanaged file conflicts with update: "+relative);
            file=new File(file,part);
        }
        return file;
    }

    static File requireVacant(File root,String relative) throws IOException {
        File file=additionPath(root,relative);
        if(!absent(file))throw new IOException("Unmanaged file conflicts with update: "+relative);
        return file;
    }

    private static boolean absent(File file) {
        return Files.notExists(file.toPath(),LinkOption.NOFOLLOW_LINKS);
    }

    private static void markAddition(File file,String owner) throws IOException {
        try {Os.setxattr(file.getPath(),ADDITION_OWNER,owner.getBytes(StandardCharsets.US_ASCII),0);}
        catch(ErrnoException error) {throw error.rethrowAsIOException();}
    }

    private static boolean ownsAddition(File file,String owner) throws IOException {
        try {
            return Arrays.equals(Os.getxattr(file.getPath(),ADDITION_OWNER),owner.getBytes(StandardCharsets.US_ASCII));
        } catch(ErrnoException error) {
            if(error.errno==OsConstants.ENODATA)return false;
            throw error.rethrowAsIOException();
        }
    }

    private static JSONObject inventory(File receipt) throws Exception {
        if(receipt.length()>StandaloneBundle.MAX_MANIFEST+512)
            throw new IOException("Oversized component receipt preserved");
        JSONObject record=new JSONObject(new String(Files.readAllBytes(receipt.toPath()),StandardCharsets.UTF_8));
        if(record.getInt("schema")!=1||!record.getString("bundle_sha256").matches("[0-9a-f]{64}"))
            throw new IOException("Invalid component receipt preserved");
        return record.getJSONObject("files");
    }

    private static void verifyOwned(JSONObject inventory,String name,File file,String digest) throws Exception {
        JSONObject expected=inventory.optJSONObject("game/"+name);
        if(expected==null||file.length()!=expected.getLong("size")||!digest.equals(expected.getString("sha256")))
            throw new IOException("Changed or unowned component preserved: "+name);
    }

    static void publish(File player,File incoming,List<String> changes,IntConsumer checkpoint) throws Exception {
        if(isPending(player)||changes.isEmpty()||changes.size()>MAX_CHANGES)
            throw new IOException("Invalid or pending component update");
        ArrayList<String> names=new ArrayList<>(changes);
        HashSet<String> seen=new HashSet<>();
        for(String name:names)if(!allowed(name)||!seen.add(name.toLowerCase(Locale.ROOT)))
            throw new IOException("Invalid component update path");
        names.add(RECEIPT);
        JSONObject oldFiles=inventory(checkedFile(player,RECEIPT)),newFiles=inventory(checkedFile(incoming,RECEIPT));
        File parent=player.getParentFile();
        File stage=Files.createTempDirectory(parent.toPath(),"gk3hd-components-").toFile();
        File pending=pending(player);
        JSONArray entries=new JSONArray();
        try {
            long bytes=0;
            for(int i=0;i<names.size();i++) {
                String name=names.get(i);
                boolean added=i<names.size()-1&&!oldFiles.has("game/"+name);
                File live=added?requireVacant(player,name):checkedFile(player,name);
                File replacement=checkedFile(incoming,name),saved=new File(stage,Integer.toString(i));
                bytes+=live.length()+replacement.length();
                if(bytes>2*(MAX_BYTES+StandaloneBundle.MAX_MANIFEST+512))
                    throw new IOException("Component transaction exceeds its storage limit");
                Files.copy(replacement.toPath(),saved.toPath(),LinkOption.NOFOLLOW_LINKS);
                String old=added?"":StandaloneBundle.hash(live),next=StandaloneBundle.hash(saved);
                if(old.equals(next)||!next.equals(StandaloneBundle.hash(replacement)))
                    throw new IOException("Component bytes do not match the prepared update");
                if(i<names.size()-1) {
                    if(!added)verifyOwned(oldFiles,name,live,old);
                    verifyOwned(newFiles,name,saved,next);
                }
                JSONObject entry=new JSONObject().put("path",name).put("old",old).put("new",next);
                if(added) {
                    // The marker follows the file and distinguishes it from a byte-identical foreign file.
                    String owner=UUID.randomUUID().toString().replace("-","");
                    markAddition(saved,owner);
                    entry.put("owner",owner);
                }
                DurableFiles.syncFile(saved);
                entries.put(entry);
            }
            File journal=new File(stage,JOURNAL);
            Files.write(journal.toPath(),new JSONObject().put("player",player.getName()).put("entries",entries)
                .toString().getBytes(StandardCharsets.UTF_8),java.nio.file.StandardOpenOption.CREATE_NEW);
            DurableFiles.syncFile(journal);
            DurableFiles.syncDirectory(stage);
            move(stage,pending);
        } catch(Exception error) {
            // The rename may have succeeded before its parent sync failed.
            // Only the original temporary name is ours to discard here.
            try {discardPreparation(stage,names.size());}
            catch(IOException cleanup) {error.addSuppressed(cleanup);}
            throw error;
        }
        checkpoint.accept(0);
        for(int i=0;i<names.size();i++) {
            File saved=checkedFile(pending,Integer.toString(i));
            JSONObject expected=entries.getJSONObject(i);
            String old=expected.getString("old");
            if(!StandaloneBundle.hash(saved).equals(expected.getString("new")))
                throw new IOException("Component changed before publication");
            if(old.isEmpty()) {
                File live=requireVacant(player,names.get(i));
                DurableFiles.moveNewFile(saved,live);
            } else {
                File live=checkedFile(player,names.get(i));
                if(!StandaloneBundle.hash(live).equals(old))
                    throw new IOException("Component changed before publication");
                DurableFiles.exchangeFiles(saved,live);
            }
            checkpoint.accept(i+1);
        }
        recover(player);
    }

    private static void discardPreparation(File stage,int count) throws IOException {
        if(absent(stage))return;
        if(!Files.isDirectory(stage.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid component staging directory preserved");
        for(int i=0;i<count;i++)Files.deleteIfExists(new File(stage,Integer.toString(i)).toPath());
        Files.deleteIfExists(new File(stage,JOURNAL).toPath());
        Files.delete(stage.toPath());
        DurableFiles.syncDirectory(stage.getParentFile());
    }

    /** The live receipt decides whether to finish publication or roll back. */
    static void recover(File player) throws Exception {
        if(!isPending(player))return;
        File pending=pending(player);
        File journal=checkedFile(pending,JOURNAL);
        if(journal.length()>MAX_JOURNAL)throw new IOException("Oversized component journal preserved");
        JSONObject record=new JSONObject(new String(Files.readAllBytes(journal.toPath()),StandardCharsets.UTF_8));
        JSONArray entries=record.getJSONArray("entries");
        int count=entries.length();
        if(!player.getName().equals(record.getString("player"))||count<2||count>MAX_CHANGES+1)
            throw new IOException("Invalid component journal preserved");
        String[] files=pending.list();
        if(files==null)throw new IOException("Cannot read component journal directory");
        HashSet<String> unrecognized=new HashSet<>(Arrays.asList(files));
        unrecognized.remove(JOURNAL);
        File[] live=new File[count],saved=new File[count];
        boolean[] swapped=new boolean[count],added=new boolean[count];
        HashSet<String> seen=new HashSet<>();
        long bytes=0;
        for(int i=0;i<count;i++) {
            JSONObject entry=entries.getJSONObject(i);
            String name=entry.getString("path"),old=entry.getString("old"),next=entry.getString("new");
            added[i]=i<count-1&&old.isEmpty();
            if((i==count-1?!name.equals(RECEIPT):!allowed(name))||!seen.add(name.toLowerCase(Locale.ROOT))||
               (!added[i]&&!old.matches("[0-9a-f]{64}"))||!next.matches("[0-9a-f]{64}")||old.equals(next))
                throw new IOException("Invalid component journal entry preserved");
            live[i]=added[i]?additionPath(player,name):checkedFile(player,name);
            String slot=Integer.toString(i);
            saved[i]=new File(pending,slot);
            unrecognized.remove(slot);
            if(added[i]) {
                String owner=entry.getString("owner");
                swapped[i]=absent(saved[i]);
                File present=swapped[i]?live[i]:saved[i],missing=swapped[i]?saved[i]:live[i];
                if(!owner.matches("[0-9a-f]{32}")||!absent(missing)||!regular(present)||
                   !ownsAddition(present,owner))
                    throw new IOException("Unrecognized component bytes preserved: "+name);
            } else saved[i]=checkedFile(pending,slot);
            bytes+=live[i].length()+saved[i].length();
            if(bytes>2*(MAX_BYTES+StandaloneBundle.MAX_MANIFEST+512))
                throw new IOException("Oversized component files preserved");
            if(added[i]) {
                if(!StandaloneBundle.hash(swapped[i]?live[i]:saved[i]).equals(next))
                    throw new IOException("Unrecognized component bytes preserved: "+name);
                continue;
            }
            String staged=StandaloneBundle.hash(saved[i]);
            String active=StandaloneBundle.hash(live[i]);
            swapped[i]=active.equals(next)&&staged.equals(old);
            if(!swapped[i]&&!(active.equals(old)&&staged.equals(next)))
                throw new IOException("Unrecognized component bytes preserved: "+name);
        }
        if(!unrecognized.isEmpty())throw new IOException("Unrecognized component files preserved");
        boolean committed=swapped[count-1];
        JSONObject oldFiles=inventory(committed?saved[count-1]:live[count-1]);
        JSONObject newFiles=inventory(committed?live[count-1]:saved[count-1]);
        for(int i=0;i<count-1;i++) {
            JSONObject entry=entries.getJSONObject(i);
            String name=entry.getString("path");
            if(added[i]) {
                if(oldFiles.has("game/"+name))
                    throw new IOException("Invalid added component ownership: "+name);
            } else verifyOwned(oldFiles,name,swapped[i]?saved[i]:live[i],entry.getString("old"));
            verifyOwned(newFiles,name,swapped[i]?live[i]:saved[i],entry.getString("new"));
        }
        if(committed) {
            for(boolean moved:swapped)if(!moved)
                throw new IOException("Inconsistent published component transaction preserved");
        } else {
            for(int i=count-2;i>=0;i--)if(swapped[i]) {
                if(added[i])DurableFiles.moveNewFile(live[i],saved[i]);
                else DurableFiles.exchangeFiles(saved[i],live[i]);
            }
        }
        // If a previous fsync failed after the receipt exchange, retry it before unblocking launch.
        for(File file:live)DurableFiles.syncDirectory(file.getParentFile());
        DurableFiles.syncDirectory(pending);
        File retired=new File(player.getParentFile(),"gk3hd-components-retired-"+UUID.randomUUID());
        move(pending,retired);
        for(int i=0;i<count;i++)if(!committed||!added[i])
            Files.delete(new File(retired,Integer.toString(i)).toPath());
        Files.delete(new File(retired,JOURNAL).toPath());
        Files.delete(retired.toPath());
        DurableFiles.syncDirectory(player.getParentFile());
    }

    private static void move(File from,File to) throws IOException {
        if(!Files.notExists(to.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Component transaction destination occupied");
        Files.move(from.toPath(),to.toPath(),StandardCopyOption.ATOMIC_MOVE);
        DurableFiles.syncDirectory(to.getParentFile());
    }
}
