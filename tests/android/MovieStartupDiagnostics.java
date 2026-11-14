package org.gk3hd.standalone;

import android.util.Log;
import java.lang.reflect.Field;

/** Failure-only evidence. Never calls a MediaPlayer method or waits for its Looper. */
final class MovieStartupDiagnostics {
    private MovieStartupDiagnostics() {}

    static void capture(Object source) {
        try {
            Object host=read(source,"movies");
            if(host==null) {
                Log.w("GK3HDXR","Movie failure snapshot: no movie host");
                return;
            }
            Object player=read(host,"player");
            Log.w("GK3HDXR","Movie failure snapshot time_ns="+System.nanoTime()+
                " owner="+read(host,"owner")+" epoch="+read(host,"epoch")+
                " focused="+read(host,"focused")+" play_requested="+read(host,"playRequested")+
                " closed="+read(host,"closed"));
            if(player instanceof AndroidMoviePlayer) {
                AndroidMoviePlayer.Snapshot state=((AndroidMoviePlayer)player).snapshot();
                Log.w("GK3HDXR","Movie cached state generation="+state.generation+" state="+state.state+
                    " width="+state.width+" height="+state.height+" duration_ms="+state.durationMillis+
                    " cached_position_ms="+state.positionMillis+" failure="+state.failure);
                // Capture these explicitly. A busy process can have more threads
                // than the bounded global dump includes.
                dump((Thread)read(player,"thread"));
            } else Log.w("GK3HDXR","Movie failure snapshot: no current player");
            dump((Thread)read(host,"receiver"));
        } catch(ReflectiveOperationException|RuntimeException error) {
            Log.w("GK3HDXR","Movie failure evidence unavailable",error);
        } finally {
            try {
                FrameProgressWatchdog.dumpThreads("Original fixture failure; before activity retirement");
            } catch(RuntimeException error) {
                Log.w("GK3HDXR","Owned-thread evidence unavailable",error);
            }
        }
    }

    private static Object read(Object owner,String name)throws ReflectiveOperationException {
        Field field=owner.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(owner);
    }

    private static void dump(Thread thread) {
        if(thread==null)return;
        StringBuilder text=new StringBuilder("Owned movie thread ").append(thread.getName())
            .append(" id=").append(thread.getId()).append(" state=").append(thread.getState());
        StackTraceElement[] frames=thread.getStackTrace();
        for(int i=0;i<frames.length&&i<20;i++)text.append("\n  ").append(frames[i]);
        Log.w("GK3HDXR",text.toString());
    }
}
