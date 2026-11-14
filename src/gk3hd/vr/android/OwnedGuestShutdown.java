package org.gk3hd.standalone;

import android.os.Process;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;
import com.winlator.core.ProcessHelper;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AccessDeniedException;
import java.nio.file.Files;
import java.nio.file.NoSuchFileException;
import java.util.ArrayList;

/** Retire an owned Wine guest even when Android suspended it during shutdown. */
public final class OwnedGuestShutdown {
    private static final class GuestProcess {
        final int pid;
        final String start;
        final boolean stopped;
        GuestProcess(int pid,String start,boolean stopped) {
            this.pid=pid;
            this.start=start;
            this.stopped=stopped;
        }
    }
    private OwnedGuestShutdown() {}
    private static String basename(String command) {
        if(command==null)return "";
        int separator=Math.max(command.lastIndexOf('/'),command.lastIndexOf('\\'));
        return command.substring(separator+1);
    }
    static boolean launcherName(String command) {
        return basename(command).equalsIgnoreCase("gk3hd-wine-launcher.exe");
    }
    private static boolean playerName(String command) {
        return launcherName(command)||basename(command).equalsIgnoreCase("GK3-VR.exe");
    }
    static boolean playerCommand(byte[] command) {
        String[] arguments=new String(command,StandardCharsets.ISO_8859_1).split("\u0000",-1);
        if(playerName(arguments[0]))return true;
        String program=basename(arguments[0]);
        if(program.equals("wine")||program.equals("wine64")||program.equals("wine-preloader")||
           program.equals("wine64-preloader")||program.equals("box64"))
            for(int i=1;i<arguments.length;i++)if(playerName(arguments[i]))return true;
        return false;
    }
    private static boolean liveOwner(String status,int uid) throws IOException {
        String state=null;boolean owned=false,uidFound=false;
        for(String line:status.split("\n")) {
            if(line.startsWith("State:"))state=line.substring(6).trim();
            if(line.startsWith("Uid:")) {
                String[] ids=line.substring(4).trim().split("\\s+");
                if(ids.length!=4)break;
                uidFound=true;
                owned=ids[0].equals(Integer.toString(uid))||ids[1].equals(Integer.toString(uid));
                break;
            }
        }
        if(!uidFound||state==null||state.isEmpty())throw new IOException("Cannot identify a guest process");
        return owned&&"ZXx".indexOf(state.charAt(0))<0;
    }
    /** Called under setup admission. Inspect, but never signal, a surviving player. */
    public static void requirePlayerStopped() throws IOException {
        File proc=new File("/proc");
        String[] entries=proc.list((directory,name)->name.matches("[1-9][0-9]*"));
        if(entries==null)throw new IOException("Cannot verify that the standalone game is closed");
        int uid=Process.myUid();
        for(String entry:entries) {
            if(entry.equals(Integer.toString(Process.myPid())))continue;
            File directory=new File(proc,entry);
            int directoryUid;
            try {directoryUid=Os.stat(directory.getPath()).st_uid;}
            catch(ErrnoException error) {
                if(error.errno==OsConstants.ENOENT||error.errno==OsConstants.ESRCH||
                   error.errno==OsConstants.EACCES||error.errno==OsConstants.EPERM)continue;
                throw error.rethrowAsIOException();
            }
            // A non-dumpable process's proc directory can be owned by root.
            if(directoryUid!=uid&&directoryUid!=0)continue;
            try {
                String status;
                try {status=new String(read(new File(directory,"status"),16384),StandardCharsets.US_ASCII);}
                catch(AccessDeniedException denied) {
                    if(directoryUid==0)continue;
                    throw denied;
                }
                if(liveOwner(status,uid)&&playerCommand(read(new File(directory,"cmdline"),65536)))
                    throw new IOException("Close the standalone game before installing");
            } catch(NoSuchFileException exited) {
                // It left /proc between enumeration and the read.
            }
        }
    }
    static boolean sessionMatches(byte[] environment,String session) {
        if(session==null||!session.matches("[a-f0-9]{32}"))return false;
        String wanted="GK3HD_FRAME_SESSION="+session;
        for(String item:new String(environment,StandardCharsets.ISO_8859_1).split("\u0000",-1))
            if(item.equals(wanted))return true;
        return false;
    }
    private static byte[] read(File path,int maximum) throws IOException {
        try(InputStream input=Files.newInputStream(path.toPath());ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] block=new byte[1024];int count;
            while((count=input.read(block))!=-1) {
                if(output.size()+count>maximum)throw new IOException("Oversized owned-process metadata");
                output.write(block,0,count);
            }
            return output.toByteArray();
        }
    }
    private static GuestProcess guestState(int pid,File directory) throws IOException, ErrnoException {
        if(Os.stat(directory.getPath()).st_uid!=Process.myUid())return null;
        String stat=new String(read(new File(directory,"stat"),4096),StandardCharsets.US_ASCII);
        int end=stat.lastIndexOf(')');
        if(end<0)return null;
        String[] fields=stat.substring(end+2).split(" +");
        return fields.length>19 ? new GuestProcess(pid,fields[19],fields[0].equals("T")) : null;
    }
    private static File processDirectory(int pid) {
        return new File("/proc/"+pid);
    }
    public static void stop(String session) {
        if(session==null||!session.matches("[a-f0-9]{32}"))return;
        String[] entries=new File("/proc").list((directory,name)->name.matches("[1-9][0-9]*"));
        if(entries==null)return;
        ArrayList<GuestProcess> stopped=new ArrayList<>();
        GuestProcess launcher=null;
        for(String entry:entries) {
            int pid=Integer.parseInt(entry);
            if(pid==Process.myPid())continue;
            File directory=processDirectory(pid);
            try {
                GuestProcess before=guestState(pid,directory);
                if(before==null)continue;
                String name=ProcessHelper.getProcessName(pid);
                boolean isLauncher=launcherName(name);
                if(!isLauncher&&(!before.stopped||(!name.contains("wine")&&!name.contains(".exe"))))continue;
                if(!sessionMatches(read(new File(directory,"environ"),65536),session))continue;
                GuestProcess after=guestState(pid,directory);
                if(after==null||!before.start.equals(after.start))continue;
                if(after.stopped)stopped.add(after);
                if(isLauncher) {
                    if(launcher!=null)throw new IllegalStateException("More than one launcher owns this session");
                    launcher=after;
                }
            } catch(IOException|ErrnoException unavailable) {
                // An inaccessible or exited process cannot establish ownership.
            } catch(Exception error) {Log.e("GK3HDGuest","Owned process inspection failed",error);return;}
        }
        // A normal Quit can race with Android pause after the launcher exits.
        // Let suspended Wine tasks finish the exit already queued by the server.
        int resumed=0;
        for(GuestProcess guest:stopped)try {
            GuestProcess now=guestState(guest.pid,processDirectory(guest.pid));
            if(now!=null&&now.stopped&&guest.start.equals(now.start)) {
                Os.kill(guest.pid,OsConstants.SIGCONT);
                resumed++;
            }
        } catch(IOException|ErrnoException error) {
            Log.w("GK3HDGuest","Could not resume an owned guest task during shutdown",error);
        }
        if(resumed>0)Log.i("GK3HDGuest","Resumed "+resumed+" owned guest tasks during shutdown; launcher present="+(launcher!=null));
        if(launcher==null)return;
        // For an interrupted launch, closing the launcher still retires its Windows job.
        try {
            GuestProcess now=guestState(launcher.pid,processDirectory(launcher.pid));
            if(now!=null&&launcher.start.equals(now.start)) {
                Process.killProcess(launcher.pid);
                Log.i("GK3HDGuest","Stopped session launcher; its Windows job owns child cleanup");
            }
        } catch(IOException|ErrnoException error) {Log.e("GK3HDGuest","Owned launcher shutdown failed",error);}
    }
}
