package org.gk3hd.standalone;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import com.winlator.container.Container;
import com.winlator.container.ContainerManager;
import com.winlator.ManagedPlayerAccess;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Diagnostics and save transfers for ADB-authorized callers. */
public final class SetupMetadataProvider extends ContentProvider {
    public static final String STATUS_FILE="gk3hd-setup.json";
    private static final int MAX_REPORT=64*1024;

    @Override public boolean onCreate() {return true;}

    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!"r".equals(mode)||uri.getEncodedQuery()!=null||uri.getEncodedFragment()!=null)
            throw new FileNotFoundException("Only setup metadata reads are supported");
        try {
            String path=uri.getEncodedPath();
            if("/status".equals(path))
                return openMetadata(new File(getContext().getFilesDir(),STATUS_FILE),MAX_REPORT);
            if("/session".equals(path))
                return openMetadata(new File(getContext().getFilesDir(),NativeSessionReport.FILE_NAME),MAX_REPORT);
            if("/last-graphics-stall".equals(path))
                return openMetadata(new File(getContext().getFilesDir(),NativeSessionReport.LAST_STALL_FILE),MAX_REPORT);
            if("/last-game-outage".equals(path))
                return openMetadata(new File(getContext().getFilesDir(),NativeSessionReport.LAST_GAME_OUTAGE_FILE),MAX_REPORT);
            if("/last-startup-without-image".equals(path))
                return openMetadata(new File(getContext().getFilesDir(),NativeSessionReport.LAST_STARTUP_FILE),MAX_REPORT);
            if("/inventory".equals(path))
                return installedInventory();
            if("/runtime".equals(path))
                return openMetadata(RuntimeAssets.installedReceipt(getContext()),256);
            if("/saves".equals(path))return exportSaves();
            throw new FileNotFoundException("Unknown setup metadata");
        } catch(IOException|ErrnoException error) {
            FileNotFoundException unavailable=new FileNotFoundException(error.getMessage());
            unavailable.initCause(error);
            throw unavailable;
        }
    }

    private File managedContainerRoot() throws IOException {
        Container selected=null;
        for(Container container:new ContainerManager(getContext()).getContainers()) {
            if(selected!=null||!"1".equals(container.getExtra("gk3hdManaged")))
                throw new IOException("No unique managed container");
            selected=container;
        }
        if(selected==null)throw new FileNotFoundException("No managed container");
        return selected.getRootDir();
    }

    private ParcelFileDescriptor installedInventory() throws IOException,ErrnoException {
        File root=managedContainerRoot();
        if(StandaloneInstallation.updatePending(root))return pendingInventory();
        ParcelFileDescriptor receipt=openMetadata(StandaloneInstallation.ownershipReceipt(root),
            StandaloneBundle.MAX_MANIFEST+512);
        if(!StandaloneInstallation.updatePending(root))return receipt;
        receipt.close();
        return pendingInventory();
    }

    private File playerForSaves() throws IOException {
        OwnedGuestShutdown.requirePlayerStopped();
        File root=managedContainerRoot();
        if(StandaloneInstallation.updatePending(root))
            throw new IOException("Finish the interrupted GK3HD VR update first.");
        return StandaloneInstallation.ownershipReceipt(root).getParentFile();
    }

    private ParcelFileDescriptor exportSaves() throws IOException,ErrnoException {
        try (ManagedPlayerAccess.Lease lease=ManagedPlayerAccess.tryInstall()) {
            if(lease==null)throw new IOException("Close GK3HD VR and wait for any installation to finish.");
            File player=playerForSaves();
            File archive=File.createTempFile("gk3hd-saves-", ".zip", getContext().getCacheDir());
            try {
                try (FileOutputStream output=new FileOutputStream(archive)) {
                    SaveArchive.exportSaves(player,output);
                }
                return openMetadata(archive,SaveArchive.MAX_ARCHIVE);
            } finally {Files.deleteIfExists(archive.toPath());}
        }
    }

    @Override public Bundle call(String method,String argument,Bundle extras) {
        getContext().enforceCallingOrSelfPermission(android.Manifest.permission.DUMP,"GK3HD save restore");
        Bundle result=new Bundle();
        if(!"restore-saves".equals(method)||argument==null||!argument.matches("[0-9a-f]{32}:[0-9a-f]{64}")) {
            result.putString("error","Invalid save restore request");
            return result;
        }
        try (ManagedPlayerAccess.Lease lease=ManagedPlayerAccess.tryInstall()) {
            if(lease==null)throw new IOException("Close GK3HD VR and wait for any installation to finish.");
            File player=playerForSaves();
            String[] request=argument.split(":",2);
            File staged=Files.createTempDirectory(getContext().getCacheDir().toPath(),"gk3hd-saves-").toFile();
            try {
                File source=new File("/sdcard/Download","gk3hd-restore-"+request[0]+".zip");
                File archive=new File(staged,"backup.zip");
                try (ParcelFileDescriptor.AutoCloseInputStream input=new ParcelFileDescriptor.AutoCloseInputStream(
                        openMetadata(source,SaveArchive.MAX_ARCHIVE))) {
                    byte[] bytes=new byte[64*1024];int size;long total=0;
                    try(FileOutputStream output=new FileOutputStream(archive)) {
                        while((size=input.read(bytes))!=-1) {
                            total+=size;
                            if(total>SaveArchive.MAX_ARCHIVE)throw new IOException("Save transfer exceeds the supported size");
                            output.write(bytes,0,size);
                        }
                    }
                }
                if(!StandaloneBundle.hash(archive).equals(request[1]))
                    throw new IOException("The transferred backup failed verification. Retry the restore.");
                result.putInt("restored",SaveArchive.restoreSaves(player,archive,staged));
            } finally {
                File[] stagedFiles=staged.listFiles();
                if(stagedFiles!=null)for(File file:stagedFiles)Files.deleteIfExists(file.toPath());
                Files.deleteIfExists(staged.toPath());
            }
        } catch(Exception error) {
            result.putString("error",error.getMessage()==null?"Could not restore saves":error.getMessage());
        }
        return result;
    }

    private static ParcelFileDescriptor pendingInventory() throws IOException {
        ParcelFileDescriptor[] pipe=ParcelFileDescriptor.createPipe();
        try(ParcelFileDescriptor.AutoCloseOutputStream stream=new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])) {
            stream.write("{\"component_update_pending\":true}".getBytes(StandardCharsets.UTF_8));
        } catch(IOException error) {
            pipe[0].close();
            throw error;
        }
        return pipe[0];
    }

    private static ParcelFileDescriptor openMetadata(File file,int limit) throws IOException,ErrnoException {
        FileDescriptor fd=Os.open(file.getPath(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_NONBLOCK,0);
        try {
            StructStat stat=Os.fstat(fd);
            if(!OsConstants.S_ISREG(stat.st_mode)||stat.st_size<1||stat.st_size>limit)
                throw new IOException("Invalid setup metadata file");
            return ParcelFileDescriptor.dup(fd);
        } finally {Os.close(fd);}
    }

    @Override public String getType(Uri uri) {return null;}
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String order) {
        throw new UnsupportedOperationException();
    }
    @Override public Uri insert(Uri uri,ContentValues values) {throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String selection,String[] args) {
        throw new UnsupportedOperationException();
    }
    @Override public int delete(Uri uri,String selection,String[] args) {throw new UnsupportedOperationException();}
}
