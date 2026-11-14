package org.gk3hd.standalone;

import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import java.io.File;
import java.io.FileDescriptor;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.FileVisitResult;

/** Persist verified private installation bytes and directory entries before success. */
public final class DurableFiles {
    private DurableFiles() { }

    private static void sync(File file,boolean directory) throws IOException {
        FileDescriptor descriptor;
        try {
            descriptor=Os.open(file.getPath(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW,0);
        } catch(ErrnoException error) {throw error.rethrowAsIOException();}
        try {
            if(directory&&!OsConstants.S_ISDIR(Os.fstat(descriptor).st_mode))
                throw new IOException("Expected a private installation directory");
            Os.fsync(descriptor);
        }
        catch(ErrnoException error) {throw error.rethrowAsIOException();}
        finally {
            try {Os.close(descriptor);}
            catch(ErrnoException error) {throw error.rethrowAsIOException();}
        }
    }
    public static void syncFile(File file) throws IOException {sync(file,false);}
    public static void syncDirectory(File file) throws IOException {sync(file,true);}

    private static void syncTree(File staged) throws IOException {
        Files.walkFileTree(staged.toPath(),new SimpleFileVisitor<Path>() {
            private int visited;
            @Override public FileVisitResult preVisitDirectory(Path dir,java.nio.file.attribute.BasicFileAttributes attrs) throws IOException {
                if(++visited>40000) throw new IOException("Private installation directory count exceeded");
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult postVisitDirectory(Path dir,IOException error) throws IOException {
                if(error!=null) throw error;
                sync(dir.toFile(),true);return FileVisitResult.CONTINUE;
            }
        });
    }

    /** Files were synced by extraction; now persist their names, then the move. */
    public static void publish(File staged,File target) throws IOException {
        if(!staged.isDirectory()||Files.isSymbolicLink(staged.toPath())||target.exists()||Files.isSymbolicLink(target.toPath())||
           !target.getParentFile().isDirectory())
            throw new IOException("Cannot publish the verified private player; existing files preserved");
        syncTree(staged);
        File oldParent=staged.getParentFile();
        if(!staged.renameTo(target)) throw new IOException("Cannot publish the verified private player atomically");
        sync(target.getParentFile(),true);
        sync(oldParent,true);
    }

    private static native void renamePaths(String staged,String target,boolean exchange) throws IOException;

    /** Caller verifies both trees and keeps the game closed. Transfer cleanup
     * ownership immediately after exchange, before a parent sync can throw. */
    public static void exchange(File staged,File target,Runnable transferred) throws IOException {
        if(transferred==null||!staged.isDirectory()||!target.isDirectory()||
           Files.isSymbolicLink(staged.toPath())||Files.isSymbolicLink(target.toPath())||
           staged.getCanonicalFile().equals(target.getCanonicalFile()))
            throw new IOException("Cannot exchange the verified private player; existing files preserved");
        syncTree(staged);
        rename(staged,target,true);
        transferred.run();
        sync(target.getParentFile(),true);
        sync(staged.getParentFile(),true);
    }

    static void exchangeFiles(File staged,File target) throws IOException {
        if(!Files.isRegularFile(staged.toPath(),LinkOption.NOFOLLOW_LINKS)||
           !Files.isRegularFile(target.toPath(),LinkOption.NOFOLLOW_LINKS)||
           Files.isSameFile(staged.toPath(),target.toPath()))
            throw new IOException("Cannot exchange managed player files");
        rename(staged,target,true);
        syncDirectory(target.getParentFile());
        syncDirectory(staged.getParentFile());
    }

    static void moveNewFile(File staged,File target) throws IOException {
        if(!Files.isRegularFile(staged.toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Missing managed player file");
        rename(staged,target,false);
        syncDirectory(target.getParentFile());
        syncDirectory(staged.getParentFile());
    }

    private static void rename(File staged,File target,boolean exchange) throws IOException {
        try {System.loadLibrary("gk3hd_files");}
        catch(LinkageError error) {throw new IOException("This app build cannot atomically update a player",error);}
        renamePaths(staged.getAbsolutePath(),target.getAbsolutePath(),exchange);
    }
}
