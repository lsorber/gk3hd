package org.gk3hd.standalone;

import android.media.MediaDataSource;
import android.media.MediaPlayer;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.view.Surface;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.concurrent.CompletableFuture;

/** Android movie lifecycle, shared by headset adapters. No eye or guest ownership. */
public final class AndroidMoviePlayer {
    private static final long PLAYBACK_CHECK_MILLIS=1000;
    private static final long PLAYBACK_STALL_NANOS=8_000_000_000L;
    public enum State { CLOSED, PREPARING, READY, PLAYING, PAUSED, ENDED, FAILED }
    public static final class Snapshot {
        public final long generation;
        public final State state;
        public final int width,height,durationMillis,positionMillis;
        public final String failure,metrics;
        Snapshot(long generation,State state,int width,int height,int duration,int position,
                String failure,String metrics) {
            this.generation=generation;this.state=state;this.width=width;this.height=height;
            durationMillis=duration;positionMillis=position;this.failure=failure;this.metrics=metrics;
        }
    }
    private static final class FileSource extends MediaDataSource {
        private final RandomAccessFile input;
        FileSource(File file)throws IOException {input=new RandomAccessFile(file,"r");}
        @Override public synchronized int readAt(long position,byte[] bytes,int offset,int size)throws IOException {
            if(position<0)throw new IOException("Negative movie position");
            if(size==0)return 0;
            input.seek(position);return input.read(bytes,offset,size);
        }
        @Override public synchronized long getSize()throws IOException {return input.length();}
        @Override public synchronized void close()throws IOException {input.close();}
    }
    private final HandlerThread thread=new HandlerThread("GK3HDMovies");
    private final Handler handler;
    private volatile Snapshot snapshot=new Snapshot(0,State.CLOSED,0,0,0,0,"","");
    private volatile long latestGeneration;
    private boolean shuttingDown;
    private CompletableFuture<Void> retirement;
    // Only the movie Looper may access these fields or MediaPlayer methods.
    private MediaPlayer player;
    private FileSource source;
    private long owner;
    private State state=State.CLOSED;
    private boolean playWhenReady;
    private int width,height,duration;
    private String failure="";
    private Runnable prepareTimeout;
    private final Runnable playbackCheck=this::checkPlayback;
    private long playbackDeadline;
    private long firstPictureDeadline;
    private int lastPlaybackPosition;
    private boolean firstPicture;

    public AndroidMoviePlayer() {thread.start();handler=new Handler(thread.getLooper());}
    public Snapshot snapshot() {return snapshot;}
    /** Caller validates the installed asset and retains its Surface until Close acknowledges. */
    public synchronized void open(long generation,File file,Surface surface) {
        if(shuttingDown)throw new IllegalStateException("Movie player is closed");
        if(generation<=latestGeneration||generation<=0)throw new IllegalArgumentException("Movie generation must increase");
        if(file==null||surface==null)throw new IllegalArgumentException("Movie source and Surface required");
        latestGeneration=generation;
        handler.post(()-> {
            if(generation!=latestGeneration)return;
            try {
                owner=generation;state=State.PREPARING;failure="";
                release();
                width=height=duration=0;playWhenReady=false;firstPicture=false;
                source=new FileSource(file);player=new MediaPlayer();MediaPlayer active=player;
                player.setOnInfoListener((p,what,extra)-> {
                    if(what==MediaPlayer.MEDIA_INFO_VIDEO_RENDERING_START&&owns(generation,p)) {
                        firstPicture=true;
                        return true;
                    }
                    return false;
                });
                player.setOnPreparedListener(p-> {
                    if(!owns(generation,p))return;
                    try {
                        cancelTimeout();width=p.getVideoWidth();height=p.getVideoHeight();duration=p.getDuration();
                        if(width<=0||height<=0||duration<=0)throw new IllegalStateException("Invalid movie dimensions or duration");
                        state=State.READY;
                        if(playWhenReady)startPlayback();
                        publish();
                    } catch(Exception error){fail(error);}
                });
                player.setOnCompletionListener(p-> {
                    if(owns(generation,p)){handler.removeCallbacks(playbackCheck);state=State.ENDED;publish();}
                });
                player.setOnErrorListener((p,what,extra)-> {
                    if(owns(generation,p))fail(new IOException("Movie decoder error "+what+"/"+extra));
                    return true;
                });
                player.setDataSource(source);player.setSurface(surface);player.prepareAsync();
                prepareTimeout=()-> {if(owns(generation,active)&&state==State.PREPARING)fail(new IOException("Movie preparation timed out"));};
                handler.postDelayed(prepareTimeout,5000);publish();
            }catch(Exception error){fail(error);}
        });
    }
    public synchronized void play(long generation) {
        if(shuttingDown)return;
        handler.post(()-> {
            if(generation!=owner||generation!=latestGeneration)return;
            try {
                if(state==State.PREPARING){playWhenReady=true;return;}
                if(state==State.READY||state==State.PAUSED){startPlayback();publish();}
            }catch(Exception error){fail(error);}
        });
    }
    public synchronized void pause(long generation) {
        if(shuttingDown)return;
        handler.post(()-> {
            if(generation!=owner||generation!=latestGeneration)return;
            try {
                playWhenReady=false;
                if(state==State.PLAYING){player.pause();handler.removeCallbacks(playbackCheck);state=State.PAUSED;publish();}
            }catch(Exception error){fail(error);}
        });
    }
    /** Close is acknowledged in snapshot only after media and file resources retire. */
    public synchronized CompletableFuture<Void> close(long generation) {
        CompletableFuture<Void> done=new CompletableFuture<>();
        if(shuttingDown)return retirement;
        handler.post(()-> {
            try {if(generation==owner){release();state=State.CLOSED;publish();}done.complete(null);}
            catch(Exception error){done.completeExceptionally(error);}
        });return done;
    }
    /** Diagnostic boundary: query clock/codec metrics on the same owner thread. */
    public synchronized CompletableFuture<Snapshot> inspect() {
        return capture(0,true);
    }
    /** Native game caption timing follows the audio clock, never elapsed wall time. */
    public synchronized CompletableFuture<Snapshot> clock(long generation) {
        if(generation<=0)throw new IllegalArgumentException("Movie clock requires an owner");
        return capture(generation,false);
    }
    private CompletableFuture<Snapshot> capture(long generation,boolean includeMetrics) {
        CompletableFuture<Snapshot> done=new CompletableFuture<>();
        if(shuttingDown){done.completeExceptionally(new IllegalStateException("Movie player is closed"));return done;}
        handler.post(()-> {
            try {
                if(generation!=0&&(generation!=owner||generation!=latestGeneration||state==State.CLOSED))
                    throw new IllegalStateException("Movie clock owner has retired");
                int position=player!=null&&state!=State.PREPARING?player.getCurrentPosition():0;
                position=Math.max(0,Math.min(position,duration));
                String metrics=includeMetrics&&player!=null?player.getMetrics().toString():"";
                done.complete(new Snapshot(owner,state,width,height,duration,position,failure,metrics));
            }catch(Exception error){done.completeExceptionally(error);}
        });return done;
    }
    public synchronized CompletableFuture<Void> shutdown() {
        if(retirement!=null)return retirement;
        CompletableFuture<Void> done=new CompletableFuture<>();retirement=done;
        shuttingDown=true;
        handler.post(()-> {
            try {release();state=State.CLOSED;publish();done.complete(null);}
            catch(Exception error){done.completeExceptionally(error);}
            finally {thread.quitSafely();}
        });return done;
    }
    private boolean owns(long generation,MediaPlayer active) {
        return generation==owner&&generation==latestGeneration&&active==player;
    }
    private void startPlayback() {
        lastPlaybackPosition=player.getCurrentPosition();
        player.start();state=State.PLAYING;
        playbackDeadline=firstPictureDeadline=System.nanoTime()+PLAYBACK_STALL_NANOS;
        handler.postDelayed(playbackCheck,PLAYBACK_CHECK_MILLIS);
    }
    private void checkPlayback() {
        if(state!=State.PLAYING||!owns(owner,player))return;
        try {
            long now=System.nanoTime();
            if(!firstPicture&&now-firstPictureDeadline>=0)
                throw new IOException("Movie did not start sending video frames");
            int position=player.getCurrentPosition();
            now=System.nanoTime();
            if(position>lastPlaybackPosition) {
                lastPlaybackPosition=position;playbackDeadline=now+PLAYBACK_STALL_NANOS;
            } else if(now-playbackDeadline>=0) {
                throw new IOException("Movie playback clock stopped at "+lastPlaybackPosition+"/"+duration+" ms");
            }
            handler.postDelayed(playbackCheck,PLAYBACK_CHECK_MILLIS);
        } catch(Exception error) {
            Log.w("GK3HDMovies","Native movie playback failed",error);
            fail(error);
        }
    }
    private void publish() {
        if(owner==latestGeneration)snapshot=new Snapshot(owner,state,width,height,duration,0,failure,"");
    }
    private void cancelTimeout() {
        if(prepareTimeout!=null){handler.removeCallbacks(prepareTimeout);prepareTimeout=null;}
    }
    private void release()throws IOException {
        cancelTimeout();handler.removeCallbacks(playbackCheck);playWhenReady=false;
        MediaPlayer old=player;player=null;
        FileSource oldSource=source;source=null;
        try {if(old!=null)old.release();}
        finally {if(oldSource!=null)oldSource.close();}
    }
    private void fail(Exception error) {
        failure=error.toString();
        try {release();}catch(Exception cleanup){failure+="; cleanup: "+cleanup;}
        state=State.FAILED;publish();
    }
}
