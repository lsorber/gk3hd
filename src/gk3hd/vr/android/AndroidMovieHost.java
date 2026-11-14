package org.gk3hd.standalone;

import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.os.Handler;
import android.util.Log;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Session-owned movie control. Only small commands/status cross the guest boundary. */
public final class AndroidMovieHost implements AutoCloseable {
    // Leave time to answer the guest's 6.5-second socket deadline.
    private static final long OPEN_TIMEOUT_NANOS=TimeUnit.SECONDS.toNanos(6);
    private final File directory,endpoint;
    private final byte[] description;
    private final String token=UUID.randomUUID().toString().replace("-","");
    private final Consumer<Runnable> graphics;
    private final Handler callbacks;
    private final ServerSocket server;
    private final Thread receiver;
    private volatile boolean closed;
    private volatile Socket client;
    private volatile long owner;
    private volatile long epoch;
    private volatile AndroidMoviePlayer player;
    // The movie clock waits until a focused headset can present stereo.
    private boolean focused,trackingReady,renderable=true,playRequested;
    // Layer/canvas/tracking belong exclusively to the graphics thread.
    private NativeMovieLayer layer;
    private MovieCanvas canvas;
    private float[] head;
    private StereoViews views;
    private Integer frame;
    private long snapshots;
    private boolean rendered;
    private long inspectedAt;

    public AndroidMovieHost(File game,String session,Handler callbacks,Consumer<Runnable> graphics)throws IOException {
        if(session==null||!session.matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Movie host requires a launch session");
        directory=new File(game,"gk3hd/videos/installed").getCanonicalFile();
        if(!directory.isDirectory())throw new IOException("Installed movie directory is unavailable");
        endpoint=new File(game,"gk3hd-movie-"+session+".txt");this.callbacks=callbacks;this.graphics=graphics;
        server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"));
        description=("GK3HD-MOVIE1\n"+server.getLocalPort()+"\n"+token+"\n").getBytes(StandardCharsets.US_ASCII);
        try {Files.write(endpoint.toPath(),description,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);}
        catch(IOException error){server.close();throw error;}
        receiver=new Thread(this::receive,"GK3HDMovieControl");receiver.start();
    }
    private <T> T onGraphics(Callable<T> action)throws Exception {
        CompletableFuture<T> done=new CompletableFuture<>();
        graphics.accept(()-> {try {if(closed)throw new IOException("Movie host is closing");done.complete(action.call());}catch(Exception e){done.completeExceptionally(e);}});
        return done.get(5,TimeUnit.SECONDS);
    }
    private static String line(InputStream input)throws IOException {
        StringBuilder text=new StringBuilder();
        for(int i=0;i<256;i++){int c=input.read();if(c<0)throw new EOFException();if(c=='\n')return text.toString();if(c<32||c>126)throw new IOException("Invalid movie control character");text.append((char)c);}
        throw new IOException("Oversized movie command");
    }
    private static void reply(OutputStream output,String text)throws IOException {output.write((text+"\n").getBytes(StandardCharsets.US_ASCII));output.flush();}
    private void receive() {
        while(!closed) {
            try(Socket peer=server.accept()) {
                client=peer;peer.setSoTimeout(8000);peer.setTcpNoDelay(true);
                InputStream input=peer.getInputStream();OutputStream output=peer.getOutputStream();
                if(!line(input).equals("HELLO "+token))throw new IOException("Invalid movie session");
                reply(output,"OK 1");peer.setSoTimeout(0); // A paused movie may legitimately be idle indefinitely.
                while(!closed) {
                    String[] words=line(input).split(" ");
                    if(words.length<2)throw new IOException("Malformed movie command");
                    long generation=Long.parseLong(words[1]);if(generation<=0)throw new IOException("Invalid movie owner");
                    if(words[0].equals("OPEN")&&words.length==3)reply(output,open(generation,words[2]));
                    else if(words.length==2&&words[0].equals("STATE"))reply(output,status(generation));
                    else if(words.length==2&&words[0].equals("CLOCK")) {
                        if(owner!=generation)reply(output,"STALE "+generation);
                        else {
                            AndroidMoviePlayer.Snapshot s=player.clock(epoch).get(2,TimeUnit.SECONDS);
                            reply(output,"CLOCK "+generation+" "+s.positionMillis+" "+s.durationMillis);
                        }
                    }
                    else if(words.length==2&&words[0].equals("PLAY")) {requestPlayback(generation,true);reply(output,status(generation));}
                    else if(words.length==2&&words[0].equals("PAUSE")) {requestPlayback(generation,false);reply(output,status(generation));}
                    else if(words.length==2&&words[0].equals("CLOSE")) {if(owner==generation)closeMovie();reply(output,"CLOSED "+generation);}
                    else throw new IOException("Unknown movie command");
                }
            }catch(Exception error){if(!closed)Log.i("GK3HDMovies","Control retired: "+error.getClass().getSimpleName());}
            finally {
                client=null;
                if(!closed)try{closeMovie();}catch(Exception error){Log.e("GK3HDMovies","Movie retirement failed",error);}
            }
        }
    }
    private String open(long generation,String name)throws Exception {
        long deadline=System.nanoTime()+OPEN_TIMEOUT_NANOS;
        if(!name.matches("GK3HD-[A-Za-z0-9_-]{1,20}\\.AVI"))return "UNSUPPORTED "+generation;
        File movie=new File(directory,name).getCanonicalFile();
        if(!movie.getParentFile().equals(directory)||!movie.isFile())return "UNSUPPORTED "+generation;
        // Existing AV1 High/4:4:4 assets must keep the qualified Windows path.
        // Native eligibility is based on media content, never a renamed extension.
        MediaExtractor extractor=new MediaExtractor();boolean hevc=false;
        try {
            extractor.setDataSource(movie.getPath());
            for(int i=0;i<extractor.getTrackCount();i++)if("video/hevc".equals(extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME)))hevc=true;
        }catch(IOException|IllegalArgumentException invalid){return "UNSUPPORTED "+generation;}
        finally {extractor.release();}
        if(!hevc)return "UNSUPPORTED "+generation;
        closeMovie();long next=++epoch;
        if(!attachMovie(generation,next,movie,deadline))return "UNSUPPORTED "+generation;
        while(System.nanoTime()<deadline) {
            AndroidMoviePlayer.Snapshot state=player.snapshot();
            if(state.generation==next&&state.state==AndroidMoviePlayer.State.READY){Log.i("GK3HDMovies","Prepared native movie "+name);return status(generation);}
            if(state.generation==next&&state.state==AndroidMoviePlayer.State.FAILED){closeMovie();return "UNSUPPORTED "+generation;}
            Thread.sleep(2);
        }
        closeMovie();return "UNSUPPORTED "+generation;
    }
    private boolean attachMovie(long generation,long next,File movie,long deadline)throws Exception {
        CompletableFuture<Boolean> attached=new CompletableFuture<>();
        graphics.accept(()-> {
            if(closed||attached.isDone()||System.nanoTime()-deadline>=0) {
                attached.complete(false);return;
            }
            NativeMovieLayer candidate=null;
            try {
                candidate=new NativeMovieLayer(callbacks);
                // Cancellation and publishing ownership must be mutually exclusive.
                // Construct the GL resources outside this lock.
                synchronized(attached) {
                    if(closed||attached.isDone()||System.nanoTime()-deadline>=0) {
                        attached.complete(false);return;
                    }
                    if(player==null)player=new AndroidMoviePlayer();
                    player.open(next,movie,candidate.surface());
                    layer=candidate;candidate=null;canvas=null;owner=generation;
                    attached.complete(true);
                }
            }catch(RuntimeException error){attached.completeExceptionally(error);}
            finally {if(candidate!=null)candidate.close();}
        });
        try {
            return attached.get(Math.max(0,deadline-System.nanoTime()),TimeUnit.NANOSECONDS);
        }catch(TimeoutException timeout) {
            synchronized(attached) {attached.complete(false);}
            return attached.get();
        }catch(InterruptedException interrupted) {
            synchronized(attached) {attached.complete(false);}
            throw interrupted;
        }
    }
    private String status(long generation) {
        if(owner!=generation||player==null)return "STALE "+generation;
        if(Log.isLoggable("GK3HDMovies",Log.DEBUG)&&System.nanoTime()-inspectedAt>2_000_000_000L) {
            inspectedAt=System.nanoTime();
            player.inspect().thenAccept(current->Log.i("GK3HDMovies","Native clock "+current.state+" "+current.positionMillis+"/"+current.durationMillis));
        }
        AndroidMoviePlayer.Snapshot s=player.snapshot();
        return "STATE "+generation+" "+s.state.name()+" "+s.width+" "+s.height+" "+s.durationMillis;
    }
    private void closeMovie()throws Exception {
        if(owner==0)return;
        Log.i("GK3HDMovies","Retiring native movie owner="+owner+" state="+player.snapshot().state);
        CompletableFuture<Void> retiring;
        synchronized(this) {playRequested=false;retiring=player.close(epoch);}
        retiring.get(5,TimeUnit.SECONDS);
        onGraphics(()-> {owner=0;canvas=null;rendered=false;if(layer!=null){layer.close();layer=null;}return null;});
    }
    // Publish intent and queue the corresponding media command under one lock.
    // The guest socket and native focus callbacks run on different threads.
    private synchronized void requestPlayback(long generation,boolean requested) {
        if(closed||owner!=generation)return;
        playRequested=requested;
        if(!requested)player.pause(epoch);
        else if(focused&&trackingReady&&renderable)player.play(epoch);
    }
    public synchronized void focused(boolean value) {
        if(closed||focused==value)return;focused=value;
        if(!value)trackingReady=false;
        updatePlayback();
    }
    public synchronized void presentation(boolean value) {
        if(renderable==value)return;
        renderable=value;
        updatePlayback();
    }
    public void tracking(float[] pose,int flags,int id,StereoViews optics) {
        rendered=false;
        boolean valid=(flags&3)==3&&optics!=null;
        synchronized(this) {
            boolean ready=focused&&valid;
            if(trackingReady!=ready) {
                trackingReady=ready;
                updatePlayback();
            }
        }
        if(!valid){head=null;views=null;frame=null;return;}
        head=pose.clone();views=optics;frame=id;
    }
    private void updatePlayback() {
        AndroidMoviePlayer current=player;
        if(closed||owner==0||current==null)return;
        if(focused&&trackingReady&&renderable&&playRequested)current.play(epoch);
        else current.pause(epoch);
    }
    public boolean active() {return owner!=0&&layer!=null&&head!=null&&views!=null;}
    public long owner() {return owner;}
    public boolean draw(int eyeWidth,int eyeHeight,boolean linearOutput) {
        rendered=false;if(!active())return false;
        AndroidMoviePlayer.Snapshot s=player.snapshot();
        if(s.generation!=epoch||s.width<=0||s.height<=0)return false;
        if(s.state!=AndroidMoviePlayer.State.PLAYING&&s.state!=AndroidMoviePlayer.State.PAUSED&&
           s.state!=AndroidMoviePlayer.State.ENDED)return false;
        if(canvas==null)canvas=new MovieCanvas(head,s.width,s.height);
        if(!layer.draw(canvas,head,views,eyeWidth,eyeHeight,linearOutput))return false;
        snapshots++;rendered=true;return true;
    }
    public Integer renderedFrame() {return rendered?frame:null;}
    public long renderedSnapshot() {return rendered?Long.MIN_VALUE+snapshots:0;}
    /** Graphics-thread retirement, after the guest has stopped using the channel. */
    @Override public void close()throws Exception {
        if(closed)return;closed=true;server.close();Socket peer=client;if(peer!=null)peer.close();receiver.interrupt();receiver.join(1000);
        if(player!=null)player.shutdown().get(3,TimeUnit.SECONDS);
        owner=0;if(layer!=null){layer.close();layer=null;}
        if(endpoint.isFile()&&java.util.Arrays.equals(Files.readAllBytes(endpoint.toPath()),description))Files.delete(endpoint.toPath());
    }
}
