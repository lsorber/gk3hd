package org.gk3hd.standalone;

/** Debug-only original-console keyboard navigation. Never writes engine state. */
public final class NativeSceneNavigation {
    public enum Key {TOGGLE,CLEAR,TEXT,ENTER}
    public interface Keyboard {boolean ready();void press(Key key,char character);void release(Key key);}
    private enum Step {OPEN,SETTLE_OPEN,CLEAR,SETTLE_CLEAR,UNFOCUS,WAIT_REOPEN,REFOCUS,SETTLE_REFOCUS,TYPE,EXECUTE,WAIT_SCENE,HIDE,SETTLE_HIDDEN,DONE}
    private final Keyboard keyboard;
    private final String command;
    private final double[] camera;
    private Step step=Step.OPEN;
    private boolean held;
    private Key heldKey;
    private int character,closeAttempts,openAttempts;
    private long started,pressedAt,pressedTick;
    public NativeSceneNavigation(String location,Keyboard keyboard) {
        this(location,"110a",keyboard);
    }
    public NativeSceneNavigation(String location,String timeblock,Keyboard keyboard) {
        this(keyboard,sceneCommand(location,timeblock));
    }
    private NativeSceneNavigation(Keyboard keyboard,String command) {
        this(keyboard,command,null);
    }
    private NativeSceneNavigation(Keyboard keyboard,String command,double[] camera) {
        if(keyboard==null)throw new IllegalArgumentException("Missing native keyboard");
        // Reject an unsupported setup stroke before opening the console.
        for(char value:command.toCharArray())NativeConsoleKeys.key(value);
        this.keyboard=keyboard;this.command=command;this.camera=camera==null ? null : camera.clone();
    }
    private static void validateLocation(String location) {
        if(location==null||!location.matches("[A-Z0-9]{3}"))
            throw new IllegalArgumentException("Invalid native console fixture");
    }
    /** Change scenes without starting a new timeblock or showing its chapter card. */
    public static NativeSceneNavigation location(String location,Keyboard keyboard) {
        validateLocation(location);
        return new NativeSceneNavigation(keyboard,"SetLocation(\""+location+"\");");
    }
    private static String sceneCommand(String location,String timeblock) {
        validateLocation(location);
        if(timeblock==null||!timeblock.matches("[123][0-9]{2}[ap]"))
            throw new IllegalArgumentException("Invalid native timeblock fixture");
        return "SetLocationTime(\""+location+"\",\""+timeblock+"\");";
    }
    public static NativeSceneNavigation sidney(Keyboard keyboard) {
        return new NativeSceneNavigation(keyboard,"CallSheep(\"r25_all\",\"GraceStartSidney\");");
    }
    public static NativeSceneNavigation jeanLobby(Keyboard keyboard) {
        // SetLocationTime retains saved actor whereabouts. Prepare the actor
        // through the original scripting API before the new scene loads.
        return new NativeSceneNavigation(keyboard,
            "SetActorLocation(\"Jean\",\"LBY\");SetLocationTime(\"LBY\",\"110a\");");
    }
    public static NativeSceneNavigation camera(double[] pose,Keyboard keyboard) {
        if(pose==null||pose.length!=5)throw new IllegalArgumentException("Expected authored camera angles/position");
        for(double value:pose)if(!Double.isFinite(value)||Math.abs(value)>10000)
            throw new IllegalArgumentException("Unbounded authored camera");
        if(Math.abs(pose[0])>180||Math.abs(pose[1])>=90)
            throw new IllegalArgumentException("Invalid authored camera angles");
        String command=String.format(java.util.Locale.ROOT,
            "CutToCameraAngleX(%.2f,%.2f,%.2f,%.2f,%.2f);",pose[0],pose[1],pose[2],pose[3],pose[4]);
        return new NativeSceneNavigation(keyboard,command,pose);
    }
    public boolean matchesCamera(double[] actual) {
        if(camera==null||actual==null||actual.length!=5)return false;
        for(int i=0;i<5;i++) {
            if(!Double.isFinite(actual[i]))return false;
            double delta=actual[i]-(i<2 ? Math.toRadians(camera[i]) : camera[i]);
            if(i<2)delta=Math.atan2(Math.sin(delta),Math.cos(delta));
            if(Math.abs(delta)>(i<2 ? .0001 : .02))return false;
        }
        return true;
    }
    public static NativeSceneNavigation jeanCamera(double[] pose,Keyboard keyboard) {
        NativeSceneNavigation view=camera(pose,keyboard);
        // Idle scripts can move Jean after scene entry. Use the original
        // authored standing position for this declared NPC-contact fixture.
        return new NativeSceneNavigation(keyboard,
            "SetActorPosition(\"Jean\",\"JEAN_INIT\");"+view.command,pose);
    }
    public String progress() {
        return step+" characters="+character+"/"+command.length()+" held="+(held ? heldKey : "none")+
            " open_attempts="+openAttempts+" close_attempts="+closeAttempts;
    }
    public static NativeSceneNavigation movie(String name,Keyboard keyboard) {
        if(name==null||!name.matches("[A-Z0-9]{1,16}"))
            throw new IllegalArgumentException("Invalid native movie fixture");
        return new NativeSceneNavigation(keyboard,"PlayFullScreenMovie(\""+name+"\");");
    }
    private boolean tap(Key key,char value,long now,long tick) {
        if(!held) {
            if(!keyboard.ready())return false;
            keyboard.press(key,value);held=true;heldKey=key;pressedAt=now;pressedTick=tick;
        } else if(now-pressedAt>=120_000_000L&&tick>pressedTick) {
            keyboard.release(heldKey);held=false;return true;
        }
        return false;
    }
    public boolean tick(long now,long nativeTick,boolean sceneMatches,int consoleVisible) {
        // Completion is immutable even when the native caller is still
        // dismissing a retail chapter card after the command has finished.
        if(step==Step.DONE)return true;
        if(started==0)started=now;
        if(now-started>60_000_000_000L) {
            if(held){keyboard.release(heldKey);held=false;}
            throw new IllegalStateException("Native console navigation timed out: "+progress());
        }
        if(nativeTick<=0)return false;
        switch(step) {
            // A developer-console overlay need not replace UIManager's root.
            // Open once. Closing is separately acknowledged by a freshly read
            // native visibility flag, never inferred from this input sequence.
            // Wait for native input updates, not a guessed root-layer vtable.
            case OPEN:if(tap(Key.TOGGLE,'\0',now,nativeTick)){openAttempts++;step=Step.SETTLE_OPEN;}break;
            case SETTLE_OPEN:
                if(nativeTick>pressedTick&&now-pressedAt>=400_000_000L&&consoleVisible==1)step=Step.CLEAR;
                else if(now-pressedAt>=1_000_000_000L&&consoleVisible==0) {
                    if(openAttempts>=3)throw new IllegalStateException("Native console did not acknowledge opening");
                    step=Step.OPEN;
                }
                break;
            // GK3 retains the executed prompt, including in saved games.
            // Match the desktop capture route: Escape clears it, then reopen
            // the editor. Never append a command to unknown retained text.
            case CLEAR:if(tap(Key.CLEAR,'\0',now,nativeTick))step=Step.SETTLE_CLEAR;break;
            case SETTLE_CLEAR:
                if(nativeTick>pressedTick&&now-pressedAt>=400_000_000L)step=Step.UNFOCUS;
                break;
            case UNFOCUS:if(tap(Key.TOGGLE,'\0',now,nativeTick))step=Step.WAIT_REOPEN;break;
            case WAIT_REOPEN:
                if(nativeTick>pressedTick&&now-pressedAt>=400_000_000L)step=Step.REFOCUS;
                break;
            case REFOCUS:if(tap(Key.TOGGLE,'\0',now,nativeTick))step=Step.SETTLE_REFOCUS;break;
            case SETTLE_REFOCUS:
                if(nativeTick>pressedTick&&now-pressedAt>=400_000_000L&&consoleVisible==1)step=Step.TYPE;
                break;
            case TYPE:
                if(character==command.length())step=Step.EXECUTE;
                else if(tap(Key.TEXT,command.charAt(character),now,nativeTick))character++;
                break;
            case EXECUTE:if(tap(Key.ENTER,'\0',now,nativeTick))step=Step.WAIT_SCENE;break;
            case WAIT_SCENE:
                if(sceneMatches&&now-pressedAt>=400_000_000L)step=Step.SETTLE_HIDDEN;
                break;
            case HIDE:
                if(tap(Key.TOGGLE,'\0',now,nativeTick)){closeAttempts++;step=Step.SETTLE_HIDDEN;}
                break;
            case SETTLE_HIDDEN:
                if(sceneMatches&&nativeTick>pressedTick&&now-pressedAt>=400_000_000L) {
                    if(consoleVisible==0)step=Step.DONE;
                    else if(consoleVisible==1) {
                        if(closeAttempts>=3)throw new IllegalStateException("Native console did not close after three acknowledged chords");
                        step=Step.HIDE;
                    }
                    // Unknown is not hidden. Await a freshly read native
                    // object or fail at the overall navigation deadline.
                }
                break;
            case DONE:return true;
        }
        return step==Step.DONE;
    }
}
