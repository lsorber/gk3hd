package org.gk3hd.standalone;

import android.app.Activity;
import android.content.Intent;
import android.util.Log;
import com.winlator.container.ContainerManager;
import com.winlator.container.Container;
import com.winlator.xserver.XKeycode;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashSet;
import org.json.JSONArray;
import org.json.JSONObject;

/** Debug-only native gameplay/benchmark flow through simulated VR controls.
 * Default flow has no desktop input or scene changes. Explicit scene fixtures
 * use original console commands or Restore controls, never game-memory/camera writes. */
public final class NativeGameFlow {
    private static final String WAIT_TITLE_INTRO="gk3hd_test_wait_title_intro";
    private static final int TITLE_INTRO_SECONDS=230;
    private static final int ROOM=0x67a248,SAVE=0x67ce58,RESTORE=0x67cd40,MOVIE=0x67e550,PAUSE=0x67db04;
    private static final int EDITOR=0x67cf80,TOOLBAR=0x684fa4,OPTIONS=0x684860,CONFIRM=0x67dc14,TITLE_BUTTON=0x668930;
    private static final int INVENTORY=0x67be24,INSPECTION=0x674798,ACTION_MENU=0x692e9c,ITEM=0x683a70;
    private static final int ACTION_SKIP=0x67a34c;

    public static int titleIntroAllowance(Intent intent) {
        // The retail Introduction lasts 213 seconds. Only this explicit
        // fixture receives the extra time at each supervision boundary.
        if(!intent.getBooleanExtra(WAIT_TITLE_INTRO,false))return 0;
        if(!intent.getBooleanExtra("gk3hd_test_title_intro",false)||
                !"benchmark".equals(intent.getStringExtra("gk3hd_scenario")))
            throw new IllegalArgumentException("Natural Introduction playback requires the title Introduction fixture");
        return TITLE_INTRO_SECONDS;
    }
    private final String token,mode;
    private String description;
    private final boolean pauseBeforeQuit,pauseAfterSave,turnAfterRestore,skipSavedTurn,worldMotion,worldAim,cancelSave;
    private String expectedRoom;
    private String expectedTimeblock,benchmarkSave;
    private boolean restoreListCaptured;
    private final boolean restoreFromWorld;
    private final boolean extraWarmup;
    private final boolean sceneNavigationRequested,waitStartupMovies;
    private final boolean testTitleIntro,waitTitleIntro,testInventoryJourney,testSidneyJourney,testJeanView;
    private final boolean testInventoryUse;
    private final boolean testStartupSmoke;
    private final boolean testShortTap;
    private final boolean testLongTravel;
    private final ShortTapProbe shortTap=new ShortTapProbe();
    private long startupRoomFirstFrame,startupRoomLastFrame;
    private long startupRoomFirstAt;
    private boolean startupRoomCaptured;
    private boolean startupStripDone;
    private int startupRoomCaptureCount;
    private final String itemHintWorkload;
    private long itemHintStarted,itemHintStartTick,itemHintEndTick;
    private JSONArray itemHintInputBefore,itemHintInputAfter;
    private final double[] viewPose;
    private final float viewLeanMeters;
    private NativeSceneNavigation.Keyboard viewSetupKeyboard;
    private final boolean[] jeanCaptured=new boolean[3];
    private static final int SIDNEY=0x690540,SIDNEY_HOME=0x68f4d4,SIDNEY_SEARCH=0x69082c,SIDNEY_RESULTS=0x68969c;
    private static final String SIDNEY_QUERY="vampires";
    private boolean sidneyTyped,sidneySearched,sidneyReturned,sidneyDayTwoReady;
    private long sidneyEdits;
    private boolean inventoryCaptured,inventoryMenuCaptured,inspectionCaptured,inventoryReturnCaptured,inventoryReturned,pointReady;
    private boolean inventoryWorldCaptured,inventoryWorldReturnCaptured;
    private boolean inventoryCarriedCancelled,inventoryCancelCaptured;
    private boolean inventoryUseResponse,inventoryUseBackSent,inventoryUseReturned;
    private long inventoryWorldFirstFrame,inventoryWorldLastFrame;
    private long inventoryCancelTick;
    private final String testMovie;
    private boolean introRequested,introSeen;
    private long introAt;
    private long startupMovieFirst,startupMovieEnd;
    private boolean startupMovieSkipped;
    private int startupBackSamples,startupMovieObservations;
    private long startupBackFirstNanos,startupMovieLastNanos;
    private JSONObject startupMovieFirstState,startupMovieLastState;
    private final long startupMovieWaitNanos;
    private final Activity activity;
    private final long restoreHoldNanos;
    private final File game,observation,report;
    private final HashSet<String> originalSaves=new HashSet<>();
    private final JSONArray trace=new JSONArray();
    private final JSONArray aims=new JSONArray();
    private JSONObject state;
    private String failure;
    private JSONObject confirmedScene;
    private JSONObject restoreOrigin;
    private NativeSceneNavigation sceneNavigation;
    private NativeSceneNavigation.Keyboard sidneySetupKeyboard;
    private final NativeCameraReadiness cameraReadiness=new NativeCameraReadiness();
    private com.winlator.xserver.Window previousKeyboardFocus;
    private boolean previousFocusWasGame;
    private JSONArray savedCamera,changedCamera;
    private String saveFile,action="",aimAction="";
    private int phase,typed,menuRecoveries,textEpochRecoveries;
    private long typingEpoch,restoreReadyAt,restoreFirstFrame,restoreHeldFrames;
    private final BenchmarkMotion motion=new BenchmarkMotion();
    private JSONArray motionOriginCamera;
    private double waitingCameraDelta;
    private long phaseAt,actionAt,neutralUntil,nextRead,lastTick,received;
    private boolean saved,restored,quitRequested,saveCancelled,saveFinalized,saveBackRequested;
    boolean quitRequested() {return quitRequested;}
    private JSONArray motionFirstCamera,motionLastCamera;
    private double motionCameraDelta;
    private final boolean[] captured={false,false,false};
    private float[] rightPose={.15f,-.2f,0,0,0,0,1};

    public NativeGameFlow(Activity activity) {
        this.activity=activity;
        testSidneyJourney=activity.getIntent().getBooleanExtra("gk3hd_test_sidney_journey",false);
        testJeanView=activity.getIntent().getBooleanExtra("gk3hd_test_jean_view",false);
        String pose=activity.getIntent().getStringExtra("gk3hd_test_camera");
        viewPose=new double[]{94,0,276.96,72.31,259.56};
        if(pose!=null) {
            String[] values=pose.split(",",-1);
            if(!testJeanView||values.length!=5)throw new IllegalArgumentException("Expected isolated numeric camera fixture");
            for(int i=0;i<5;i++)viewPose[i]=Double.parseDouble(values[i]);
        }
        viewLeanMeters=activity.getIntent().getFloatExtra("gk3hd_test_lean_m",.75f);
        if(!Float.isFinite(viewLeanMeters)||viewLeanMeters<0||viewLeanMeters>4)
            throw new IllegalArgumentException("Unbounded simulated view translation");
        testTitleIntro=activity.getIntent().getBooleanExtra("gk3hd_test_title_intro",false);
        waitTitleIntro=titleIntroAllowance(activity.getIntent())>0;
        testStartupSmoke=activity.getIntent().getBooleanExtra("gk3hd_test_startup_smoke",false);
        testInventoryJourney=activity.getIntent().getBooleanExtra("gk3hd_test_inventory_journey",false);
        testInventoryUse=activity.getIntent().getBooleanExtra("gk3hd_test_inventory_use",false);
        testShortTap=activity.getIntent().getBooleanExtra("gk3hd_test_short_inventory_tap",false);
        testMovie=activity.getIntent().getStringExtra("gk3hd_test_movie");
        try {
            pauseBeforeQuit=activity.getIntent().getBooleanExtra("gk3hd_test_pause_before_quit",false);
            pauseAfterSave=activity.getIntent().getBooleanExtra("gk3hd_test_pause_after_save",false);
            turnAfterRestore=activity.getIntent().getBooleanExtra("gk3hd_test_turn_after_restore",false);
            skipSavedTurn=activity.getIntent().getBooleanExtra("gk3hd_test_skip_saved_turn",false);
            cancelSave=activity.getIntent().getBooleanExtra("gk3hd_test_cancel_save",false);
            worldMotion=activity.getIntent().getBooleanExtra("gk3hd_test_world_motion",false);
            testLongTravel=activity.getIntent().getBooleanExtra("gk3hd_test_long_travel",false);
            worldAim=activity.getIntent().getBooleanExtra("gk3hd_test_world_aim",false);
            itemHintWorkload=activity.getIntent().getStringExtra("gk3hd_test_item_hint_workload");
            if(itemHintWorkload!=null&&!itemHintWorkload.equals("retain")&&!itemHintWorkload.equals("cancel"))
                throw new IllegalArgumentException("Unknown selected-item workload");
            waitStartupMovies=activity.getIntent().getBooleanExtra("gk3hd_test_wait_startup_movies",false);
            int movieWait=activity.getIntent().getIntExtra("gk3hd_test_startup_movie_wait_ms",0);
            if(movieWait<0||movieWait>30000||movieWait>0&&!waitStartupMovies)
                throw new IllegalArgumentException("Invalid bounded startup movie observation");
            startupMovieWaitNanos=movieWait*1_000_000L;
            token=activity.getIntent().getStringExtra("gk3hd_observation_token");
            if(token==null||!token.matches("[0-9a-f]{32}")) throw new IllegalArgumentException("Missing test observation token");
            mode=activity.getIntent().getStringExtra("gk3hd_flow_mode");
            if(!"save".equals(mode)&&!"restore".equals(mode)&&!"benchmark".equals(mode)) throw new IllegalArgumentException("Unknown native fixture mode");
            if(testLongTravel&&(!worldMotion||!"benchmark".equals(mode)))
                throw new IllegalArgumentException("Long travel requires the isolated moving world fixture");
            if(testSidneyJourney&&(!"save".equals(mode)||testInventoryJourney||testMovie!=null||
                    !activity.getIntent().getBooleanExtra("gk3hd_test_capture_game",false)))
                throw new IllegalArgumentException("SIDNEY requires the isolated captured interface journey");
            if(cancelSave&&!"save".equals(mode))throw new IllegalArgumentException("Cancel requires the Save keyboard journey");
            if(testInventoryJourney&&(!"benchmark".equals(mode)||testMovie!=null||testTitleIntro))
                throw new IllegalArgumentException("Inventory journey requires its own bounded world fixture");
            if(testShortTap&&!testInventoryJourney)
                throw new IllegalArgumentException("Short tap requires the isolated inventory journey");
            if(testMovie!=null&&(!testMovie.matches("[A-Z0-9]{1,16}")||!"benchmark".equals(mode)||testTitleIntro))
                throw new IllegalArgumentException("Invalid native story-movie fixture");
            if(worldMotion&&!"benchmark".equals(mode)) throw new IllegalArgumentException("Motion is confined to the world benchmark");
            if(itemHintWorkload!=null&&(!worldMotion||!"benchmark".equals(mode)||testInventoryJourney||
                    testSidneyJourney||testJeanView||testMovie!=null))
                throw new IllegalArgumentException("Selected-item workload requires the isolated moving benchmark");
            int restoreHold=activity.getIntent().getIntExtra("gk3hd_test_restore_hold_ms",0);
            if(restoreHold<0||restoreHold>8000||restoreHold>0&&!"restore".equals(mode))
                throw new IllegalArgumentException("Invalid bounded restored-world hold");
            restoreHoldNanos=restoreHold*1_000_000L;
            Container container=new ContainerManager(activity).getContainerById(activity.getIntent().getIntExtra("container_id",0));
            if(container==null) throw new IllegalArgumentException("Missing owned test container");
            game=new File(container.getRootDir(),".wine/drive_c/gk3hd-vr");
            String room=activity.getIntent().getStringExtra("gk3hd_test_expected_room");
            File savedFixture=new File(game,"gk3hd-benchmark-save.txt");
            String[] savedCatalog=null;
            if(savedFixture.exists()) {
                if(!mode.equals("benchmark")||savedFixture.length()>16)throw new IllegalArgumentException("Unbounded restored benchmark fixture");
                benchmarkSave=new String(Files.readAllBytes(savedFixture.toPath()),StandardCharsets.US_ASCII).trim();
                if(!benchmarkSave.matches("save[0-9]{4}\\.gk3"))throw new IllegalArgumentException("Invalid benchmark save name");
                savedCatalog=NativeSaveFile.catalog(new File(game,benchmarkSave));
            } else benchmarkSave=null;
            File worldRestore=new File(game,"gk3hd-benchmark-world-restore.txt");
            restoreFromWorld=worldRestore.exists();
            if(restoreFromWorld&&(!mode.equals("benchmark")||benchmarkSave==null||
               worldRestore.length()!=8||!new String(Files.readAllBytes(worldRestore.toPath()),
                   StandardCharsets.US_ASCII).equals("restore\n")))
                throw new IllegalArgumentException("Invalid in-world Restore fixture");
            if(testInventoryUse&&(!testInventoryJourney||!restoreFromWorld))
                throw new IllegalArgumentException("Inventory use requires the restored inventory journey");
            File roomFixture=new File(game,"gk3hd-benchmark-room.txt");
            if(roomFixture.exists()) {
                if(room!=null||!mode.equals("benchmark")||roomFixture.length()>16)
                    throw new IllegalArgumentException("Ambiguous or unbounded console fixture");
                room=new String(Files.readAllBytes(roomFixture.toPath()),StandardCharsets.US_ASCII).trim();
            }
            // Optional extra warmup is an explicit debug workload, not a
            // discarded part of an already-started measurement window.
            String[] roomFields=(room==null ? savedCatalog==null ? "R25" : savedCatalog[1].toUpperCase(java.util.Locale.ROOT) : room).split(" ",-1);
            if(roomFields.length>2||roomFields.length==2&&!roomFields[1].equals("30"))
                throw new IllegalArgumentException("Invalid bounded scene warmup");
            expectedRoom=roomFields[0];expectedTimeblock=savedCatalog==null ? "110a" : savedCatalog[2];
            if(testStartupSmoke&&(!mode.equals("benchmark")||benchmarkSave!=null||room!=null||
                    worldMotion||testTitleIntro||testInventoryJourney||testSidneyJourney||testJeanView||testMovie!=null||
                    !activity.getIntent().getBooleanExtra("gk3hd_test_capture_game",false)))
                throw new IllegalArgumentException("Startup smoke requires an isolated captured opening-room journey");
            extraWarmup=roomFields.length==2;sceneNavigationRequested=room!=null&&benchmarkSave==null;
            if(testJeanView&&(!mode.equals("benchmark")||!expectedRoom.equals("LBY")||
                    benchmarkSave==null||!restoreFromWorld||worldMotion||testInventoryJourney||testSidneyJourney||testMovie!=null))
                throw new IllegalArgumentException("Jean view requires its isolated lobby/controller fixture");
            if(savedCatalog!=null&&!expectedRoom.equalsIgnoreCase(savedCatalog[1]))throw new IllegalArgumentException("Save does not match expected scene");
            if(!expectedRoom.matches("R25|LBY|RC1")||room!=null&&!"benchmark".equals(mode))
                throw new IllegalArgumentException("Invalid benchmark scene identity");
            observation=new File(game,"standalone-state.json");
            report=new File(activity.getFilesDir(),"standalone-flow-"+token+".json");
            File[] entries=NativeSaveFile.entries(game);
            if(entries==null||entries.length>1000) throw new IllegalStateException("Cannot enumerate private game saves");
            for(File file:entries) originalSaves.add(file.getName());
            if(mode.equals("restore")) {
                description=activity.getIntent().getStringExtra("gk3hd_expected_description");
                saveFile=activity.getIntent().getStringExtra("gk3hd_expected_save");
                savedCamera=new JSONArray(activity.getIntent().getStringExtra("gk3hd_expected_camera"));
                if(description==null||!description.matches("aio [0-9a-f]{6}")||saveFile==null||
                   !saveFile.matches("(?i)save[0-9]{4}\\.gk3")||!new File(game,saveFile).isFile()||savedCamera.length()!=5)
                    throw new IllegalArgumentException("Invalid owned save restoration fixture");
            } else description=savedCatalog==null ? "aio "+token.substring(0,6) : savedCatalog[0];
            phaseAt=System.nanoTime();writeReport();
            Log.i("GK3HDXR","Game fixture token="+token+" mode="+mode);
        } catch(Exception error) {throw new IllegalStateException("Cannot initialize save fixture",error);}
    }
    private void read(long now) throws Exception {
        if(now<nextRead) return;nextRead=now+50_000_000L;
        if(!observation.isFile()) return;
        if(observation.length()>16384) throw new IllegalStateException("Oversized native observation");
        JSONObject next;
        try {next=new JSONObject(new String(Files.readAllBytes(observation.toPath()),StandardCharsets.US_ASCII));}
        catch(java.io.IOException|org.json.JSONException temporary) {return;}
        if(!token.equals(next.optString("token"))) return;
        long tick=next.getLong("tick_ms");
        if(tick>lastTick) {
            state=next;lastTick=tick;received=now;
            if(phase==0&&!introRequested&&next.optLong("layer_type",-1)==MOVIE) {
                startupMovieObservations++;
                startupMovieLastNanos=now;
                startupMovieLastState=startupInputState(next);
                if(startupMovieFirstState==null)startupMovieFirstState=startupMovieLastState;
            }
        }
    }
    private static JSONObject startupInputState(JSONObject snapshot) throws Exception {
        JSONObject result=new JSONObject().put("native_tick_ms",snapshot.getLong("tick_ms"));
        JSONArray panel=snapshot.optJSONArray("panel_state"),input=snapshot.optJSONArray("input_state");
        // These vectors start at the enabled field in the linked patch ABI.
        if(panel!=null&&panel.length()==18)
            result.put("panel_result",panel.getLong(1)).put("panel_calls",panel.getLong(3))
                .put("completion_result",panel.getLong(9));
        if(input!=null&&input.length()==34)
            result.put("native_input_calls",input.getLong(9)).put("shortcut_valid",input.getLong(16)!=0);
        return result;
    }
    private void advance(int next,long now) throws Exception {
        // Explicit workload variant: a hand held in front of the viewer,
        // rather than the distant pose last used to click a title/save panel.
        // Preserve older benchmark controls unless this variant was selected.
        if(worldAim&&(next==13||next==30)) rightPose=new float[]{.15f,-.2f,-.35f,0,0,0,1};
        trace.put(new JSONObject().put("phase",phase).put("next",next).put("native_tick",lastTick)
            .put("layer_type",state.optLong("layer_type")).put("text",state.optString("text")));
        phase=next;phaseAt=now;neutralUntil=now+200_000_000L;action="";aimAction="";pointReady=false;
        Log.i("GK3HDXR","Game fixture mode="+mode+" phase="+phase+" native="+state.optLong("layer_type"));writeReport();
    }
    public boolean startupMovie() {return (phase==0||phase==38)&&state!=null&&state.optLong("layer_type",-1)==MOVIE;}
    public boolean storyMovieActive() {return phase==38;}
    public boolean titleIntroActive() {return phase==0&&introSeen;}
    private static XrInput.Hand neutral() {return new XrInput.Hand(new float[]{.15f,-.2f,0,0,0,0,1},15,0,0,0,0,0);}
    private XrInput.Hand releasedRight() {return new XrInput.Hand(rightPose,15,0,0,0,0,0);}
    private XrInput empty() {return new XrInput(neutral(),releasedRight());}
    private boolean down(String name,long now,boolean repeat) {
        if(testShortTap&&name.equals("inventory-open"))return shortTap.held(now);
        if(!name.equals(action)) {action=name;actionAt=now;}
        long elapsed=now-actionAt;
        return (repeat ? elapsed%1_000_000_000L : elapsed)<350_000_000L;
    }
    private XrInput menu(long now) {
        return new XrInput(new XrInput.Hand(new float[]{-.15f,-.2f,0,0,0,0,1},15,
            down("menu-"+phase,now,true) ? XrInput.MENU : 0,0,0,0,0),releasedRight());
    }
    private static float f(JSONArray array,int index) throws Exception {return Float.intBitsToFloat((int)array.getLong(index));}
    private static float[] rotate(float[] q,float[] v) {
        float tx=2*(q[1]*v[2]-q[2]*v[1]),ty=2*(q[2]*v[0]-q[0]*v[2]),tz=2*(q[0]*v[1]-q[1]*v[0]);
        return new float[]{v[0]+q[3]*tx+q[1]*tz-q[2]*ty,v[1]+q[3]*ty+q[2]*tx-q[0]*tz,v[2]+q[3]*tz+q[0]*ty-q[1]*tx};
    }
    private XrInput point(String name,double x,double y,boolean keyboard,long now) throws Exception {
        return point(name,x,y,keyboard,false,now);
    }
    private XrInput gameMenuButton(String name,int row,long now) throws Exception {
        JSONArray panel=state.getJSONArray("panel");
        // Menu pixels have their own 960x1000 canvas, on the returned panel
        // plane. Native input is deliberately masked while this menu owns it.
        // Pause becomes observable before its renderer replaces the preceding
        // page geometry. A click through that old aspect can hit Resume while
        // intending Save. Wait for the actual menu plane before aiming.
        float width=f(panel,14),height=f(panel,15);
        if(width<=0||height<=0||Math.abs(width*1000-height*960)>.01f)return empty();
        return point(name,panel.getLong(2)*.5,
            panel.getLong(3)*(150+row*104+44)/1000.0,false,true,now);
    }
    private XrInput point(String name,double x,double y,boolean keyboard,boolean gameMenu,long now) throws Exception {
        return point(name,x,y,keyboard,gameMenu,true,now);
    }
    private XrInput point(String name,double x,double y,boolean keyboard,boolean gameMenu,boolean select,long now) throws Exception {
        pointReady=false;
        JSONArray panel=state.getJSONArray("panel");if(panel.length()!=47) return empty();
        float[] q={f(panel,7),f(panel,8),f(panel,9),f(panel,10)};
        float width=f(panel,14),height=f(panel,15);
        if(width<=0||height<=0) return empty();
        float[] centre={f(panel,11),f(panel,12),f(panel,13)};
        double pixelsX=panel.getLong(2),pixelsY=panel.getLong(3);
        if(keyboard) {
            float keyWidth=Math.min(width,1.2f),keyHeight=keyWidth*456/1200;
            float[] delta=rotate(q,new float[]{0,-(height+keyHeight)/2-.06f,.02f});
            for(int i=0;i<3;i++) centre[i]+=delta[i];
            width=keyWidth;height=keyHeight;pixelsX=1200;pixelsY=456;
        }
        float[] delta=rotate(q,new float[]{(float)(x/pixelsX-.5)*width,(float)(.5-y/pixelsY)*height,1.6f});
        float[] pose={centre[0]+delta[0],centre[1]+delta[1],centre[2]+delta[2],q[0],q[1],q[2],q[3]};
        if(testInventoryJourney) {
            // Aim from a plausible hand position instead of placing the hand
            // on the target's view ray, which can hide the ribbon behind it.
            float[] target=rotate(q,new float[]{(float)(x/pixelsX-.5)*width,(float)(.5-y/pixelsY)*height,0});
            float dx=centre[0]+target[0]-.15f,dy=centre[1]+target[1]+.2f,dz=centre[2]+target[2]+.35f;
            float length=(float)Math.sqrt(dx*dx+dy*dy+dz*dz);dx/=length;dy/=length;dz/=length;
            float w=1-dz,norm=(float)Math.sqrt(dx*dx+dy*dy+w*w);
            if(norm<.00001f)throw new IllegalStateException("Inventory target is behind the controller");
            pose=new float[]{.15f,-.2f,-.35f,dy/norm,-dx/norm,0,w/norm};
        }
        rightPose=pose;
        if(!name.equals(aimAction)) {aimAction=name;action="";}
        boolean arrived=panel.getLong(16)==1&&panel.getLong(29)==1;
        for(int i=0;i<3;i++) arrived&=Math.abs(f(panel,36+i)-pose[i])<.0001;
        if(!keyboard&&!gameMenu) arrived&=panel.getLong(41)==1&&panel.getLong(42)==1&&
            Math.abs(f(panel,43)-x)<2&&Math.abs(f(panel,44)-y)<2;
        // Publish a neutral aim first, and press only after the real renderer
        // returns that ray/hit. Never race a trigger with a moved pointer.
        // Native focus/owner changes can deliberately reject the first press.
        // Retry navigation buttons after a neutral release, never text keys.
        pointReady=arrived;
        boolean held=select&&arrived&&down(name,now,!keyboard);
        if(arrived&&actionAt==now&&aims.length()<32) {
            if(keyboard) typingEpoch=state.getLong("text_epoch");
            aims.put(new JSONObject().put("action",name).put("phase",phase).put("x",x).put("y",y)
                .put("native_tick",lastTick).put("layer_type",state.optLong("layer_type"))
                .put("text_epoch",state.optLong("text_epoch")).put("text_accepted",state.optLong("text_accepted"))
                .put("panel_flags",panel.getLong(4)));
            writeReport();
        }
        return new XrInput(neutral(),new XrInput.Hand(pose,15,held ? XrInput.TRIGGER : 0,0,0,held ? 1 : 0,0));
    }
    private XrInput keyboardCharacter(String name,char character,long now) throws Exception {
        double kx=502,ky=404;
        if(character!=' ') {
            String[] keys={"1234567890-=","qwertyuiop","asdfghjkl'","zxcvbnm,./"};boolean found=false;
            for(int row=0;row<keys.length;row++) {
                int column=keys[row].indexOf(character);
                if(column>=0) {kx=12+(column+(row==3 ? 2 : 0))*98+45;ky=12+row*88+40;found=true;break;}
            }
            if(!found)throw new IllegalStateException("Unsupported fixture character");
        }
        return point(name,kx,ky,true,now);
    }
    private XrInput authoredPoint(String name,double x,double y,long now) throws Exception {
        JSONArray p=state.getJSONArray("panel");double scale=p.getDouble(3)/768;
        return point(name,(p.getDouble(2)-1024*scale)/2+x*scale,y*scale,false,now);
    }
    private int consoleVisibility() throws Exception {
        JSONObject current=state.optJSONObject("console_state");
        return current==null ? -1 : current.getBoolean("visible") ? 1 : 0;
    }
    private XrInput pointRect(String action,JSONArray rect,long now) throws Exception {
        return point(action,(rect.getDouble(0)+rect.getDouble(2))/2,(rect.getDouble(1)+rect.getDouble(3))/2,false,now);
    }
    private JSONObject control(int type) throws Exception {
        JSONArray controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) if(controls.getJSONObject(i).getLong("type")==type) return controls.getJSONObject(i);
        return null;
    }
    private JSONArray inventoryItem() throws Exception {
        JSONArray first=null,controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) {
            JSONObject node=controls.getJSONObject(i);JSONArray r=node.getJSONArray("rect");
            if(node.getLong("type")!=ITEM||node.getLong("parent_type")!=INVENTORY||
               r.getDouble(2)<=r.getDouble(0)||r.getDouble(3)<=r.getDouble(1))continue;
            if(first==null||r.getDouble(1)<first.getDouble(1)||
               r.getDouble(1)==first.getDouble(1)&&r.getDouble(0)<first.getDouble(0))first=r;
        }
        return first;
    }
    private boolean nativeSaveReady(long now) throws Exception {
        // Play exposes the room while its authored arrival action still owns
        // it. The real menu correctly disables Save until that action ends;
        // opening Pause earlier would freeze the very action we await.
        JSONArray controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++)
            if(controls.getJSONObject(i).getLong("type")==ACTION_SKIP)return false;
        JSONArray camera=state.getJSONArray("camera");
        if(camera.length()!=5)return false;
        double[] values=new double[5];for(int i=0;i<5;i++)values[i]=camera.getDouble(i);
        return cameraReadiness.ready(now,state.optLong("scene_frames",0),values);
    }
    private XrInput inventoryPoint(boolean select,long now) throws Exception {
        return inventoryPoint("inventory-item",select,now);
    }
    private XrInput inventoryPoint(String name,boolean select,long now) throws Exception {
        JSONArray r=inventoryItem();if(r==null){pointReady=false;return empty();}
        JSONArray panel=state.getJSONArray("panel");double scale=panel.getDouble(3)/768;
        double left=(panel.getDouble(2)-1024*scale)/2;
        return point(name,left+(r.getDouble(0)+r.getDouble(2))/2*scale,
            (r.getDouble(1)+r.getDouble(3))/2*scale,false,false,select,now);
    }
    private JSONArray inventoryInspectButton() throws Exception {
        JSONArray first=null,controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) {
            JSONObject node=controls.getJSONObject(i);JSONArray r=node.getJSONArray("rect");
            if(node.getLong("type")!=TITLE_BUTTON||node.getLong("parent_type")!=ACTION_MENU||node.getLong("state")==4)continue;
            if(first==null||r.getDouble(0)<first.getDouble(0))first=r;
        }
        return first;
    }
    private JSONArray options() throws Exception {
        if(control(TOOLBAR)==null) return null;
        ArrayList<JSONObject> buttons=new ArrayList<>();JSONArray controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) {
            JSONObject node=controls.getJSONObject(i);JSONArray r=node.getJSONArray("rect");
            double width=r.getDouble(2)-r.getDouble(0),height=r.getDouble(3)-r.getDouble(1);
            if(node.getLong("parent_type")==TOOLBAR&&width==height&&width>=8&&width<=128) buttons.add(node);
        }
        buttons.sort((a,b)->Double.compare(a.optJSONArray("rect").optDouble(0),b.optJSONArray("rect").optDouble(0)));
        return buttons.size()>=6&&buttons.get(5).getLong("state")!=4 ? buttons.get(5).getJSONArray("rect") : null;
    }
    private JSONArray titleButton(int index) throws Exception {
        ArrayList<JSONObject> buttons=new ArrayList<>();JSONArray controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) {JSONObject c=controls.getJSONObject(i);if(c.getLong("type")==TITLE_BUTTON) buttons.add(c);}
        buttons.sort((a,b)->Double.compare(a.optJSONArray("rect").optDouble(0),b.optJSONArray("rect").optDouble(0)));
        if(buttons.size()!=4) return null;
        if(buttons.get(index).getLong("state")==4) return null;
        // Title keeps authored child bounds, then draws each centre through a
        // fitted 4:3 view. Its control extents scale independently by H/768.
        // Raw object coordinates therefore are not rendered button locations.
        JSONArray r=buttons.get(index).getJSONArray("rect"),panel=state.getJSONArray("panel");
        long width=panel.getLong(2),height=panel.getLong(3);
        if(width<=0||height<=0) return null;
        long fitWidth=width*3>=height*4 ? height*4/3 : width;
        long fitHeight=width*3>=height*4 ? height : width*3/4;
        long cx=(width-fitWidth)/2+(r.getLong(0)+r.getLong(2))/2*fitWidth/width;
        long cy=(height-fitHeight)/2+(r.getLong(1)+r.getLong(3))/2*fitHeight/height;
        long w=(r.getLong(2)-r.getLong(0))*fitHeight/768;
        long h=(r.getLong(3)-r.getLong(1))*fitHeight/768;
        return new JSONArray().put(cx-w/2).put(cy-h/2).put(cx-w/2+w).put(cy-h/2+h);
    }
    private JSONArray submenu(boolean quit) throws Exception {
        return submenu(quit ? -1 : 0);
    }
    private JSONArray submenu(int index) throws Exception {
        ArrayList<JSONArray> buttons=new ArrayList<>();JSONArray controls=state.getJSONArray("controls");
        for(int i=0;i<controls.length();i++) {
            JSONObject node=controls.getJSONObject(i);
            if(node.getLong("parent_type")==OPTIONS&&node.getLong("type")==TITLE_BUTTON&&node.getLong("state")!=4)
                buttons.add(node.getJSONArray("rect"));
        }
        buttons.sort((a,b)->{int y=Double.compare(a.optDouble(1),b.optDouble(1));return y!=0 ? y : Double.compare(a.optDouble(0),b.optDouble(0));});
        return buttons.isEmpty()||index>=buttons.size() ? null : buttons.get(index<0 ? buttons.size()-1 : index);
    }
    private XrInput recoverMenu(int retry,long now) throws Exception {
        if(now-phaseAt<1_000_000_000L) return empty();
        if(++menuRecoveries>2) throw new IllegalStateException("Native menu disappeared repeatedly during controller navigation");
        advance(retry,now);return empty();
    }
    private NativeSceneNavigation consoleNavigation() {return consoleNavigation(0);}
    private NativeSceneNavigation consoleNavigation(int setup) {
        if(setup==2&&sidneySetupKeyboard!=null)return NativeSceneNavigation.sidney(sidneySetupKeyboard);
        if(setup==3&&viewSetupKeyboard!=null)return NativeSceneNavigation.jeanCamera(viewPose,viewSetupKeyboard);
        com.winlator.xserver.XServer server=((com.winlator.XServerDisplayActivity)activity).getXServer();
        com.winlator.xserver.Window target;
        try(com.winlator.xserver.XLock lock=server.lock(com.winlator.xserver.XServer.Lockable.WINDOW_MANAGER)) {
            com.winlator.xserver.Window focus=server.windowManager.getFocusedWindow();
            previousKeyboardFocus=focus;
            // Wine foreground and X keyboard focus are independent. The
            // stereo X window can have focus while Wine keeps GK3 foreground.
            previousFocusWasGame=state.optBoolean("game_foreground");
            Log.i("GK3HDXR","Console fixture initial X focus="+(focus==null ? "none" : focus.id+":"+focus.getClassName()+":"+focus.getName()));
            target=findGameWindow(server.windowManager.rootWindow,new int[1],0);
            if(target==null)throw new IllegalStateException("Native game keyboard window unavailable");
            server.windowManager.setFocus(target,com.winlator.xserver.WindowManager.FocusRevertTo.PARENT);
            Log.i("GK3HDXR","Console fixture targets X window="+target.id+" class="+target.getClassName()+" name="+target.getName());
        }
        server.getWinHandler().bringToFront(target.getClassName(),target.getHandle());
        NativeSceneNavigation.Keyboard keyboard=new NativeSceneNavigation.Keyboard() {
            private XKeycode textStroke;
            private boolean textShift;
            private Boolean previousEnabled;
            public boolean ready() {
                try(com.winlator.xserver.XLock lock=server.lock(com.winlator.xserver.XServer.Lockable.WINDOW_MANAGER)) {
                    com.winlator.xserver.Window gameTarget=findGameWindow(server.windowManager.rootWindow,new int[1],0);
                    boolean enabled=gameTarget!=null&&gameTarget.attributes.isEnabled();
                    if(previousEnabled==null||previousEnabled!=enabled) {
                        Log.i("GK3HDXR","Console keyboard enabled="+enabled+" native_tick="+lastTick);
                        previousEnabled=enabled;
                    }
                    return enabled;
                }
            }
            public void press(NativeSceneNavigation.Key key,char character) {
                switch(key) {
                    case TOGGLE:
                        // A scene transition can move X focus independently
                        // of Wine's foreground HWND. Reacquire the actual game
                        // target before closing its console, not just before
                        // opening it. Never send the chord to the stereo view.
                        com.winlator.xserver.Window gameTarget;
                        try(com.winlator.xserver.XLock lock=server.lock(com.winlator.xserver.XServer.Lockable.WINDOW_MANAGER)) {
                            com.winlator.xserver.Window focus=server.windowManager.getFocusedWindow();
                            Log.i("GK3HDXR","Console chord X focus="+(focus==null ? "none" : focus.id+":"+focus.getClassName()+":"+focus.getName()));
                            gameTarget=findGameWindow(server.windowManager.rootWindow,new int[1],0);
                            if(gameTarget==null)throw new IllegalStateException("Console chord lost native keyboard window");
                            server.windowManager.setFocus(gameTarget,com.winlator.xserver.WindowManager.FocusRevertTo.PARENT);
                        }
                        server.getWinHandler().bringToFront(gameTarget.getClassName(),gameTarget.getHandle());
                        server.injectKeyPress(XKeycode.KEY_CTRL_L);server.injectKeyPress(XKeycode.KEY_SHIFT_L);
                        server.injectKeyPress(XKeycode.KEY_GRAVE);
                        break;
                    case TEXT:
                        // A keysym override remaps KEY_A and notifies Wine on
                        // every character. Use fixed physical strokes instead,
                        // preserving the keyboard map used by native hotkeys.
                        textStroke=XKeycode.valueOf(NativeConsoleKeys.key(character));
                        textShift=NativeConsoleKeys.shift(character);
                        if(textShift)server.injectKeyPress(XKeycode.KEY_SHIFT_L);
                        server.injectKeyPress(textStroke);break;
                    case ENTER:server.injectKeyPress(XKeycode.KEY_ENTER);break;
                    case CLEAR:server.injectKeyPress(XKeycode.KEY_ESC);break;
                }
            }
            public void release(NativeSceneNavigation.Key key) {
                switch(key) {
                    case TOGGLE:
                        server.injectKeyRelease(XKeycode.KEY_GRAVE);server.injectKeyRelease(XKeycode.KEY_SHIFT_L);
                        server.injectKeyRelease(XKeycode.KEY_CTRL_L);break;
                    case TEXT:
                        server.injectKeyRelease(textStroke);
                        if(textShift)server.injectKeyRelease(XKeycode.KEY_SHIFT_L);
                        textStroke=null;textShift=false;break;
                    case ENTER:server.injectKeyRelease(XKeycode.KEY_ENTER);break;
                    case CLEAR:server.injectKeyRelease(XKeycode.KEY_ESC);break;
                }
            }
        };
        if(setup==1){sidneySetupKeyboard=keyboard;return new NativeSceneNavigation("R25","205p",keyboard);}
        if(setup==2)return NativeSceneNavigation.sidney(keyboard);
        if(setup==3)return NativeSceneNavigation.jeanCamera(viewPose,keyboard);
        if(setup==4){viewSetupKeyboard=keyboard;return NativeSceneNavigation.jeanLobby(keyboard);}
        return testMovie==null ? NativeSceneNavigation.location(expectedRoom,keyboard) : NativeSceneNavigation.movie(testMovie,keyboard);
    }
    private static com.winlator.xserver.Window findGameWindow(com.winlator.xserver.Window window,int[] visited,int depth) {
        if(depth>12||++visited[0]>128)return null;
        if(window.attributes.isViewable()&&window.getHandle()!=0&&
            (window.getClassName().contains("SierraGEngineWindow")||window.getName().startsWith("Gabriel Knight 3")))return window;
        for(com.winlator.xserver.Window child:window.getChildren()) {
            com.winlator.xserver.Window found=findGameWindow(child,visited,depth+1);
            if(found!=null)return found;
        }
        return null;
    }
    private void restoreKeyboardFocus() {
        com.winlator.xserver.XServer server=((com.winlator.XServerDisplayActivity)activity).getXServer();
        com.winlator.xserver.Window previous=previousKeyboardFocus;
        if(previous==null||!previous.attributes.isViewable()||previous.getHandle()==0)
            throw new IllegalStateException("Original fixture keyboard focus no longer available");
        try(com.winlator.xserver.XLock lock=server.lock(com.winlator.xserver.XServer.Lockable.WINDOW_MANAGER)) {
            server.windowManager.setFocus(previous,com.winlator.xserver.WindowManager.FocusRevertTo.PARENT);
        }
        server.getWinHandler().bringToFront(previous.getClassName(),previous.getHandle());
        Log.i("GK3HDXR","Console fixture restores X focus="+previous.id+":"+previous.getName());
    }
    public XrInput input(long now) throws Exception {
        pointReady=false;
        read(now);
        // The story observation intentionally spans the long caption after
        // 15 seconds, then sends Back at 22 seconds. Leave time for that real
        // input and return to the room before declaring the phase stalled.
        long phaseTimeoutSeconds=phase==0||phase==31||phase==37||phase==60||phase==61||phase==68||phase==74 ? 65 : phase==38 ? 30 : 20;
        if(phase==0&&waitTitleIntro)phaseTimeoutSeconds+=TITLE_INTRO_SECONDS;
        if(phase!=30&&now-phaseAt>phaseTimeoutSeconds*1_000_000_000L) {
            writeReport();
            throw new IllegalStateException("Native fixture timed out at phase "+phase+
                (sceneNavigation==null ? "" : " console="+sceneNavigation.progress()));
        }
        if(state==null||now-received>1_000_000_000L||now<neutralUntil) return empty();
        int layer=state.getInt("layer_type");
        // Slow native construction can publish the destination only after a
        // bounded menu recovery. Recognize it rather than sending Menu again
        // and closing the very page the earlier button successfully opened.
        if(phase>=1&&phase<=3&&layer==SAVE) {advance(4,now);return empty();}
        if(phase>=20&&phase<=22&&layer==CONFIRM) {advance(23,now);return empty();}
        switch(phase) {
            case 0:
                // Only startup movies precede the title route. Use the normal
                // controller Back binding; never pop a story layer directly.
                if(layer==MOVIE) {
                    if(!introRequested&&startupMovieFirst==0)startupMovieFirst=now;
                    if(introRequested) {
                        introSeen=true;if(introAt==0)introAt=now;
                        if(waitTitleIntro||now-introAt<8_000_000_000L)return empty();
                    }
                    // Waiting for startup EOF must not prevent the separately
                    // selected Introduction from testing controller Back.
                    if(!introRequested&&waitStartupMovies&&
                            (startupMovieWaitNanos==0||now-phaseAt<startupMovieWaitNanos))return empty();
                    boolean held=down("startup-movie-back",now,true);
                    if(!introRequested&&held) {
                        startupMovieSkipped=true;
                        startupBackSamples++;
                        if(startupBackFirstNanos==0)startupBackFirstNanos=now;
                    }
                    return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                        held ? XrInput.SECONDARY : 0,0,0,0,0));
                }
                if(startupMovieFirst!=0&&startupMovieEnd==0)startupMovieEnd=now;
                if(layer==ROOM) {
                    if(testStartupSmoke) {
                        if(!nativeWorldReady()||state.optLong("scene_frames",0)<=0)return empty();
                        long frame=state.getLong("scene_frames");
                        if(startupRoomFirstFrame==0){startupRoomFirstFrame=frame;startupRoomFirstAt=now;}
                        startupRoomLastFrame=frame;
                        if(frame-startupRoomFirstFrame>=8&&(startupRoomCaptureCount==6||startupStripDone))advance(20,now);
                        return empty();
                    }
                    if(mode.equals("restore")||benchmarkSave!=null&&!restoreFromWorld) throw new IllegalStateException("Restore fixture unexpectedly started a new game");
                    if(mode.equals("save")&&!nativeSaveReady(now))return empty();
                    advance(testSidneyJourney ? 60 : testInventoryJourney&&!restoreFromWorld ? 39 : testMovie!=null ? 37 : restoreFromWorld ? 33 : mode.equals("benchmark") ? (sceneNavigationRequested ? 31 : 30) : 1,now);return empty();
                }
                if((mode.equals("restore")||benchmarkSave!=null)&&layer==RESTORE) {advance(11,now);return empty();}
                if(testTitleIntro&&!introSeen) {
                    JSONArray intro=titleButton(0);
                    if(intro!=null){introRequested=true;return pointRect("title-intro",intro,now);}
                    return empty();
                }
                JSONArray title=titleButton(mode.equals("restore")||benchmarkSave!=null&&!restoreFromWorld ? 2 : 1);
                return title==null ? empty() : pointRect("title",title,now);
            case 1: case 20:
                // Performance-only fixtures must export their completed
                // window before any new menu/render-ownership transition.
                // Waiting only at confirmation had already opened Quit.
                if(phase==20&&pauseBeforeQuit)return empty();
                if(layer==PAUSE) {
                    // The first press can be retired while Pause takes input
                    // ownership. Give Quit a second neutral-separated attempt.
                    // That same target is empty on the confirmation page, so
                    // repeating it cannot confirm quitting or choose another item.
                    if(phase==20&&action.equals("vr-menu-quit")&&now-actionAt>=1_350_000_000L) {
                        advance(24,now);return empty();
                    }
                    return gameMenuButton(phase==1 ? "vr-menu-save" : "vr-menu-quit",phase==1 ? 1 : 6,now);
                }
                if(options()!=null) {advance(phase==1 ? 2 : 21,now);return empty();}
                return menu(now);
            case 2: case 21:
                JSONArray option=options();
                if(submenu(phase==21)!=null) {advance(phase==2 ? 3 : 22,now);return empty();}
                return option==null ? recoverMenu(phase==2 ? 1 : 20,now) : pointRect("options",option,now);
            case 3: case 22:
                JSONArray sub=submenu(phase==22);
                return sub==null ? recoverMenu(phase==3 ? 1 : 20,now) : pointRect("submenu",sub,now);
            case 4:
                if(state.getInt("editor_type")==EDITOR&&state.getLong("text_epoch")!=0) {advance(5,now);return empty();}
                JSONArray rows=state.getJSONArray("rows");
                if(rows.length()==0) return empty();
                JSONObject last=rows.getJSONObject(rows.length()-1);
                // The layer and its first rows become observable before list
                // population completes. Never mistake that prefix for the
                // appended slot, or overwrite an existing save by selecting it.
                if(rows.length()<originalSaves.size()+1) return empty();
                if(rows.length()>originalSaves.size()+1) throw new IllegalStateException("Unexpected additional native save rows");
                return pointRect("new-slot",last.getJSONArray("rect"),now);
            case 5:
                String text=state.getString("text");
                if(!description.startsWith(text)) throw new IllegalStateException("Unexpected native editor contents: "+text);
                if(text.length()>typed) {typed=text.length();typingEpoch=0;neutralUntil=now+200_000_000L;action="";return empty();}
                if(text.equals(description)) {advance(6,now);return empty();}
                // A native focus change invalidates the old keyboard intent.
                // Re-arm through a real neutral release, never repeat an
                // unacknowledged key in the same epoch or edit native memory.
                if(typingEpoch!=0&&typingEpoch!=state.getLong("text_epoch")) {
                    if(++textEpochRecoveries>8) throw new IllegalStateException("Native editor focus changes repeatedly during typing");
                    typingEpoch=0;action="";neutralUntil=now+200_000_000L;writeReport();return empty();
                }
                return keyboardCharacter("key-"+typed,description.charAt(typed),now);
            case 6:
                // Exercise Back after editing without writing a save. This
                // separates page/keyboard retirement from native serialization.
                if(cancelSave) {
                    if(layer==ROOM) {saveCancelled=true;advance(20,now);return empty();}
                    if(layer!=SAVE)throw new IllegalStateException("Unexpected owner while cancelling Save");
                    return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                        down("save-cancel-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
                }
                if(!saveFinalized) {
                    File[] files=NativeSaveFile.entries(game);if(files==null) return empty();
                    for(File file:files) if(!originalSaves.contains(file.getName())&&NativeSaveFile.finalized(file)) {
                        if(saveFile!=null&&!saveFile.equals(file.getName())) throw new IllegalStateException("Unexpected additional save");
                        String[] catalog=NativeSaveFile.catalog(file);
                        if(!description.equals(catalog[0])||!expectedRoom.equalsIgnoreCase(catalog[1])||
                           !expectedTimeblock.equalsIgnoreCase(catalog[2]))
                            throw new IllegalStateException("Unexpected finalized save identity");
                        saveFile=file.getName();saveFinalized=true;
                    }
                }
                if(saveFinalized) {
                    // Finalization proves disk output, not that the engine has
                    // resumed. Stop clicking Save; if its page remains open,
                    // exercise the user's Back binding and still require ROOM.
                    if(layer==ROOM) {saved=true;advance(7,now);return empty();}
                    if(layer!=SAVE)throw new IllegalStateException("Unexpected owner after finalizing Save");
                    saveBackRequested=true;
                    return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                        down("save-complete-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
                }
                if(savedCamera==null&&state.getJSONArray("camera").length()==5) savedCamera=state.getJSONArray("camera");
                return point("save",875,203,false,now);
            case 7:
                if(pauseAfterSave) return empty();
                if(saved&&skipSavedTurn) {advance(20,now);return empty();}
                JSONArray camera=state.getJSONArray("camera");
                if(savedCamera!=null&&camera.length()==5&&Math.abs(camera.getDouble(0)-savedCamera.getDouble(0))>.1) {
                    changedCamera=camera;advance(20,now);return empty();
                }
                boolean turn=down("snap",now,true);
                return new XrInput(neutral(),new XrInput.Hand(new float[]{.15f,-.2f,0,0,0,0,1},15,0,turn ? 1 : 0,0,0,0));
            case 11:
                JSONArray restoreRows=state.getJSONArray("rows");JSONArray selected=null;
                for(int i=0;i<restoreRows.length();i++) {JSONObject row=restoreRows.getJSONObject(i);if(row.getString("name").equals(description)) {if(selected!=null) throw new IllegalStateException("Ambiguous restore description");selected=row.getJSONArray("rect");}}
                // The layer is registered before its asynchronous save list is
                // populated. Wait on the existing phase deadline, not a sleep
                // or an immediate false corruption/missing-save verdict.
                if(selected==null) return empty();
                if(!action.isEmpty()&&now-actionAt>600_000_000L) {advance(12,now);return empty();}
                return pointRect("restore-row",selected,now);
            case 12:
                if(layer==ROOM) {if(benchmarkSave!=null)restored=true;advance(testJeanView ? 73 : testInventoryJourney ? 39 : benchmarkSave!=null ? 30 : 13,now);return empty();}
                return point("restore",875,203,false,now);
            case 13:
                JSONArray actual=state.getJSONArray("camera");boolean equal=actual.length()==5;
                if(equal) for(int i=0;i<5;i++) equal&=Math.abs(actual.getDouble(i)-savedCamera.getDouble(i))<.0001;
                // Camera fields can be deserialized before a later read error
                // opens a native modal dialog. Require actual world rendering,
                // not just a populated camera, before accepting restoration.
                if(equal&&state.optLong("scene_frames",0)>0) {
                    if(restoreReadyAt==0) {restoreReadyAt=now;restoreFirstFrame=state.optLong("scene_frames",0);}
                    restoreHeldFrames=state.optLong("scene_frames",0)-restoreFirstFrame;
                    if(now-restoreReadyAt>=restoreHoldNanos) {restored=true;advance(turnAfterRestore ? 7 : 20,now);}
                } else restoreReadyAt=0;
                return empty();
            case 23:
                // Diagnostic boundary only. Never report native Quit success.
                if(pauseBeforeQuit) return empty();
                quitRequested=true;writeReport();
                return point("quit-yes",(1280-1024*800.0/768)/2+516*800.0/768,421*800.0/768,false,now);
            case 24:
                if(pauseBeforeQuit) return empty();
                if(layer!=PAUSE) return empty();
                // A single neutral packet at a page transition can be skipped
                // by the producer. Observe a release interval before confirming.
                if(now-phaseAt<500_000_000L) return empty();
                quitRequested=true;writeReport();
                return gameMenuButton("vr-menu-confirm-quit",3,now);
            case 60:
                if(sceneNavigation==null) {
                    if(layer!=ROOM||!nativeSaveReady(now))return empty();
                    sceneNavigation=consoleNavigation(1);
                }
                if(!state.optBoolean("game_foreground"))return empty();
                JSONObject sidneyScene=state.optJSONObject("scene");
                boolean dayTwo=sidneyScene!=null&&"r25".equalsIgnoreCase(sidneyScene.optString("location"))&&
                    "205p".equalsIgnoreCase(sidneyScene.optString("timeblock"));
                if(sceneNavigation.tick(now,lastTick,dayTwo,consoleVisibility())&&dayTwo) {
                    sidneyDayTwoReady=true;
                    // SetLocationTime legitimately opens the retail chapter
                    // card. Dismiss it before a synchronous stereo PNG capture
                    // can outlive the input observation's freshness deadline.
                    if(layer==0x67df90)return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                        down("sidney-chapter-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
                    if(layer!=ROOM)throw new IllegalStateException("Unexpected day-two entry owner");
                    if(!captured[0])return empty();
                    confirmedScene=new JSONObject(sidneyScene.toString());sceneNavigation=null;advance(61,now);
                }
                return empty();
            case 61:
                if(sceneNavigation==null) {
                    if(layer!=ROOM||!nativeSaveReady(now))return empty();
                    sceneNavigation=consoleNavigation(2);
                }
                if(!state.optBoolean("game_foreground"))return empty();
                if(sceneNavigation.tick(now,lastTick,layer==SIDNEY&&control(SIDNEY_HOME)!=null,consoleVisibility())) {
                    restoreKeyboardFocus();sceneNavigation=null;advance(62,now);
                }
                return empty();
            case 62:
                if(layer!=SIDNEY)throw new IllegalStateException("SIDNEY home lost its owner");
                if(control(SIDNEY_SEARCH)!=null&&state.optLong("editor_type")!=0&&state.optLong("text_epoch")!=0) {
                    sidneyEdits=state.getLong("text_accepted");typed=0;typingEpoch=0;advance(63,now);return empty();
                }
                return authoredPoint("sidney-search",232,175,now);
            case 63:
                String query=state.getString("text");
                if(layer!=SIDNEY||control(SIDNEY_SEARCH)==null||!SIDNEY_QUERY.startsWith(query))
                    throw new IllegalStateException("Unexpected SIDNEY text owner or contents: "+query);
                if(query.length()>typed) {
                    if(query.length()!=typed+1||state.getLong("text_accepted")!=sidneyEdits+query.length())
                        throw new IllegalStateException("SIDNEY keyboard edit was lost or repeated");
                    typed=query.length();typingEpoch=0;action="";neutralUntil=now+200_000_000L;return empty();
                }
                if(query.equals(SIDNEY_QUERY)) {sidneyTyped=true;advance(64,now);return empty();}
                if(typingEpoch!=0&&typingEpoch!=state.getLong("text_epoch"))
                    throw new IllegalStateException("SIDNEY editor changed during a pending key");
                return keyboardCharacter("sidney-key-"+typed,SIDNEY_QUERY.charAt(typed),now);
            case 64:
                if(!captured[1])return empty();
                if(control(SIDNEY_RESULTS)!=null) {sidneySearched=true;advance(65,now);return empty();}
                return authoredPoint("sidney-submit",718,256,now);
            case 65:
                if(layer!=SIDNEY||control(SIDNEY_RESULTS)==null)throw new IllegalStateException("SIDNEY results owner changed before capture");
                if(captured[2])advance(66,now);
                return empty();
            case 66:
                if(control(SIDNEY_HOME)!=null&&state.optLong("editor_type")==0) {sidneyReturned=true;advance(67,now);return empty();}
                return authoredPoint("sidney-home",762,604,now);
            case 67:
                if(layer==ROOM) {advance(20,now);return empty();}
                if(layer!=SIDNEY)throw new IllegalStateException("Unexpected layer while leaving SIDNEY");
                return authoredPoint("sidney-exit",762,604,now);
            case 31:
                if(sceneNavigation==null) {
                    if(layer!=ROOM||state.optLong("scene_frames",0)==0||state.optJSONArray("camera").length()!=5)return empty();
                    sceneNavigation=consoleNavigation();
                }
                // Winlator's native focus request is asynchronous. A host-side
                // X focus update alone does not prove Wine activated GK3.
                if(!state.optBoolean("game_foreground"))return empty();
                JSONObject destination=state.optJSONObject("scene");
                boolean matches=destination!=null&&expectedRoom.equalsIgnoreCase(destination.optString("location"))&&
                    expectedTimeblock.equalsIgnoreCase(destination.optString("timeblock"));
                JSONObject consoleState=state.optJSONObject("console_state");
                int consoleVisible=consoleState==null ? -1 : consoleState.getBoolean("visible") ? 1 : 0;
                if(sceneNavigation.tick(now,lastTick,matches,consoleVisible)&&layer==ROOM) {
                    restoreKeyboardFocus();advance(32,now);
                }
                return empty();
            case 73:
                if(layer!=ROOM||!nativeSaveReady(now))return empty();
                // Re-establish Jean's scripted whereabouts before reloading
                // the opening lobby. A timeblock change alone retains them.
                sceneNavigation=consoleNavigation(4);advance(74,now);return empty();
            case 74:
                JSONObject resetScene=state.optJSONObject("scene");
                boolean atOpening=resetScene!=null&&"lby".equalsIgnoreCase(resetScene.optString("location"))&&
                    "110a".equalsIgnoreCase(resetScene.optString("timeblock"));
                if(sceneNavigation.tick(now,lastTick,atOpening,consoleVisibility())&&atOpening) {
                    if(layer==0x67df90||layer==MOVIE)return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                        down("jean-chapter-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
                    if(layer!=ROOM)throw new IllegalStateException("Unexpected opening-lobby owner");
                    sceneNavigation=consoleNavigation(3);advance(68,now);
                }
                return empty();
            case 68:
                double[] cameraPose=new double[5];JSONArray observedCamera=state.optJSONArray("camera");
                if(observedCamera==null||observedCamera.length()!=5)return empty();
                for(int i=0;i<5;i++)cameraPose[i]=observedCamera.getDouble(i);
                if(sceneNavigation.tick(now,lastTick,sceneNavigation.matchesCamera(cameraPose),consoleVisibility())&&layer==ROOM) {
                    confirmedScene=new JSONObject(state.getJSONObject("scene").toString());
                    restoreKeyboardFocus();advance(69,now);
                }
                return empty();
            case 69:
                if(state.optBoolean("game_foreground")==previousFocusWasGame&&nativeSaveReady(now))advance(70,now);
                return empty();
            case 70:case 71:case 72:
                if(layer!=ROOM)throw new IllegalStateException("Jean probe lost its native room owner");
                if(jeanCaptured[phase-70])advance(phase==72 ? 20 : phase+1,now);
                return empty();
            case 32:
                if(state.optBoolean("game_foreground")==previousFocusWasGame)advance(30,now);
                return empty();
            case 33:
                // Exercise an actual live source before replacing it through
                // the game's Restore UI. A title-to-Restore flow cannot prove
                // retirement of already prepared room geometry.
                JSONObject origin=state.optJSONObject("scene");
                if(layer!=ROOM||origin==null||state.optLong("scene_frames",0)<3||
                   state.optJSONArray("camera").length()!=5)return empty();
                if(!"r25".equalsIgnoreCase(origin.optString("location"))||
                   !"110a".equalsIgnoreCase(origin.optString("timeblock")))
                    throw new IllegalStateException("Play did not reach the expected Restore origin");
                restoreOrigin=new JSONObject(origin.toString());advance(34,now);return empty();
            case 34:
                if(layer==RESTORE) {advance(11,now);return empty();}
                if(layer==PAUSE) return gameMenuButton("vr-menu-load",2,now);
                if(options()!=null) {advance(35,now);return empty();}
                return menu(now);
            case 35:
                if(layer==RESTORE) {advance(11,now);return empty();}
                if(submenu(1)!=null) {advance(36,now);return empty();}
                JSONArray restoreOption=options();
                return restoreOption==null ? recoverMenu(34,now) : pointRect("restore-options",restoreOption,now);
            case 36:
                if(layer==RESTORE) {advance(11,now);return empty();}
                JSONArray restoreSubmenu=submenu(1);
                return restoreSubmenu==null ? recoverMenu(34,now) : pointRect("restore-submenu",restoreSubmenu,now);
            case 37:
                if(sceneNavigation==null) {
                    if(layer!=ROOM||state.optLong("scene_frames",0)==0||state.optJSONArray("camera").length()!=5)return empty();
                    sceneNavigation=consoleNavigation();
                }
                if(!state.optBoolean("game_foreground"))return empty();
                JSONObject movieConsole=state.optJSONObject("console_state");
                int movieConsoleVisible=movieConsole==null ? -1 : movieConsole.getBoolean("visible") ? 1 : 0;
                if(sceneNavigation.tick(now,lastTick,layer==MOVIE,movieConsoleVisible)) {
                    restoreKeyboardFocus();advance(38,now);
                }
                return empty();
            case 38:
                // Story playback is an interaction check. Quit after Back
                // returns to the room instead of adding a timing workload.
                if(layer==ROOM) {advance(20,now);return empty();}
                // The story control includes a silent gap and overlapping
                // speakers after eleven seconds. Short controls reach EOF;
                // longer movies still leave through the real Back action.
                if(layer!=MOVIE||now-phaseAt<22_000_000_000L)return empty();
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    down("story-movie-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
            case 39:
                if(layer==INVENTORY) {advance(40,now);return empty();}
                if(layer!=ROOM)return empty();
                if(restoreFromWorld) {
                    if(!nativeWorldReady()||state.optLong("scene_frames",0)==0)return empty();
                    long frame=state.getLong("scene_frames");
                    if(inventoryWorldFirstFrame==0)inventoryWorldFirstFrame=frame;
                    inventoryWorldLastFrame=frame;
                    // Qualify content reuse before a real interface transition,
                    // using observed native frames rather than a fixed warmup.
                    if(frame-inventoryWorldFirstFrame<8||!inventoryWorldCaptured)return empty();
                }
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    down("inventory-open",now,true) ? XrInput.PRIMARY : 0,0,0,0,0));
            case 40:
                if(layer!=INVENTORY)throw new IllegalStateException("Inventory owner changed before capture");
                if(!inventoryCaptured)return inventoryPoint(false,now);
                advance(testInventoryUse ? 80 : restoreFromWorld ? 47 : 41,now);return empty();
            case 80:
                if(layer!=INVENTORY||control(ACTION_MENU)!=null)
                    throw new IllegalStateException("Direct inventory use opened an unexpected menu");
                if(control(ACTION_SKIP)!=null) {
                    if(!"inventory-use-target".equals(action)||now-actionAt<350_000_000L)
                        throw new IllegalStateException("Inventory response preceded trigger release");
                    inventoryUseResponse=true;advance(81,now);return empty();
                }
                // This probe gets one press and release. A navigation retry
                // could otherwise hide a dropped or duplicate use action.
                if(!action.isEmpty()&&now-actionAt>=350_000_000L) {
                    if(now-actionAt>5_000_000_000L)
                        throw new IllegalStateException("Inventory use produced no native response");
                    return empty();
                }
                return inventoryPoint("inventory-use-target",true,now);
            case 81:
                if(layer!=INVENTORY||control(ACTION_MENU)!=null)
                    throw new IllegalStateException("Inventory response changed its owner");
                if(control(ACTION_SKIP)==null) {
                    inventoryUseReturned=true;advance(47,now);return empty();
                }
                boolean skipInventoryResponse=down("inventory-use-response-back",now,false);
                inventoryUseBackSent|=skipInventoryResponse;
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    skipInventoryResponse ? XrInput.SECONDARY : 0,0,0,0,0));
            case 47:
                if(layer!=INVENTORY)throw new IllegalStateException("Carried-item cancellation left inventory");
                if(!action.isEmpty()&&now-actionAt>=600_000_000L&&lastTick>inventoryCancelTick) {
                    inventoryCarriedCancelled=true;
                    if(!inventoryCancelCaptured)return empty();
                    advance(41,now);return empty();
                }
                // A restored carried item makes Select mean "use on". Cancel
                // it through the real Back action before requesting Inspect.
                if(action.isEmpty())inventoryCancelTick=lastTick;
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    down("inventory-cancel-carried",now,false) ? XrInput.SECONDARY : 0,0,0,0,0));
            case 41:
                if(layer!=INVENTORY)throw new IllegalStateException("Inventory owner changed before its action menu");
                if(inventoryInspectButton()!=null){advance(42,now);return empty();}
                return inventoryPoint(true,now);
            case 42:
                if(layer==INSPECTION){advance(43,now);return empty();}
                JSONArray inspectButton=inventoryInspectButton();
                if(inspectButton!=null&&!inventoryMenuCaptured)return point("inventory-inspect-hover",
                    (inspectButton.getDouble(0)+inspectButton.getDouble(2))/2,
                    (inspectButton.getDouble(1)+inspectButton.getDouble(3))/2,false,false,false,now);
                return inspectButton==null ? empty() : pointRect("inventory-inspect",inspectButton,now);
            case 43:
                if(layer!=INSPECTION)throw new IllegalStateException("Inspection owner changed before capture");
                if(!inspectionCaptured)return point("inspection-hover",state.getJSONArray("panel").getDouble(2)/2,
                    state.getJSONArray("panel").getDouble(3)/2,false,false,false,now);
                advance(44,now);return empty();
            case 44:
                if(layer==INVENTORY){advance(45,now);return empty();}
                if(layer!=INSPECTION)throw new IllegalStateException("Unexpected owner while leaving inspection");
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    down("inspection-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
            case 45:
                if(layer!=INVENTORY)throw new IllegalStateException("Inventory return owner changed before capture");
                if(!inventoryReturnCaptured)return inventoryPoint(false,now);
                advance(46,now);return empty();
            case 46:
                // This is a correctness journey, not a timing workload. Quit
                // after the acknowledged return instead of benchmarking 30 s.
                if(layer==ROOM) {
                    if(restoreFromWorld&&!inventoryWorldReturnCaptured)return empty();
                    inventoryReturned=true;advance(20,now);return empty();
                }
                if(layer!=INVENTORY)throw new IllegalStateException("Unexpected owner while returning from inventory");
                return new XrInput(neutral(),new XrInput.Hand(rightPose,15,
                    down("inventory-back",now,true) ? XrInput.SECONDARY : 0,0,0,0,0));
            case 30:
                if(!worldMotion||!sceneReady()) return empty();
                JSONArray motionCamera=state.getJSONArray("camera");
                // ROOM ownership precedes camera initialization. A transition
                // from the all-zero construction snapshot is not movement.
                if(state.optLong("scene_frames",0)<=0||
                    Math.abs(motionCamera.getDouble(2))+Math.abs(motionCamera.getDouble(3))+
                    Math.abs(motionCamera.getDouble(4))<.000001) return empty();
                if(motionFirstCamera==null) {
                    double[] values=new double[5];
                    for(int i=0;i<5;i++)values[i]=motionCamera.getDouble(i);
                    if(!cameraReadiness.ready(now,state.optLong("scene_frames",0),values))return empty();
                    if(itemHintWorkload!=null&&itemHintEndTick==0) {
                        // Compare the original selected item with a normal Back
                        // cancellation. Both arms settle before motion and timing
                        // start. No item, camera or puzzle field is written.
                        JSONArray input=state.optJSONArray("input_state");
                        // Versioned observation: world mode, valid shortcut
                        // owner, and no held shortcut blocked by that owner.
                        boolean inputReady=input!=null&&input.length()==34&&input.optLong(19)==1&&
                            input.optLong(16)==1&&input.optLong(15)==0;
                        boolean cancel=itemHintWorkload.equals("cancel");
                        if(itemHintStarted==0) {
                            // Camera/ROOM readiness precedes interactive world
                            // input during a cut fade.
                            if(!inputReady)return empty();
                            itemHintInputBefore=new JSONArray(input.toString());
                            if(!cancel&&input.getLong(26)==0)
                                throw new IllegalStateException("No selected item to retain");
                            itemHintStarted=now;itemHintStartTick=lastTick;
                        }
                        long preparation=now-itemHintStarted;
                        if(preparation>=3_000_000_000L)
                            throw new IllegalStateException("Native game did not acknowledge selected-item preparation");
                        if(!inputReady)return empty();
                        long originalItem=itemHintInputBefore.getLong(26),item=input.getLong(26);
                        if(cancel&&item!=0&&item==originalItem) return new XrInput(neutral(),
                            new XrInput.Hand(rightPose,15,down("benchmark-cancel-item",now,true) ? XrInput.SECONDARY : 0,
                                0,0,0,0));
                        if(item!=(cancel ? 0 : originalItem))
                            throw new IllegalStateException("Unexpected selected item during benchmark preparation");
                        if(preparation<900_000_000L||lastTick<=itemHintStartTick)return empty();
                        itemHintInputAfter=new JSONArray(input.toString());
                        itemHintEndTick=lastTick;writeReport();
                    }
                    motionFirstCamera=new JSONArray(motionCamera.toString());
                    motion.prepare(now);
                }
                motionLastCamera=new JSONArray(motionCamera.toString());
                for(int i=2;i<5;i++) motionCameraDelta=Math.max(motionCameraDelta,
                    Math.abs(motionCamera.getDouble(i)-motionFirstCamera.getDouble(i)));
                if(!motion.active())waitingCameraDelta=motionCameraDelta;
                // Repeat a short forward/back step with neutral gaps. The
                // original controller adapter moves the camera, never a memory
                // write or scene jump. Start only after the destination camera
                // has settled; authored scene transitions are not movement.
                float step=motion.step(now);
                if(testLongTravel&&motion.active())step=LongTravelMotion.step(motion.seconds(now));
                return new XrInput(new XrInput.Hand(new float[]{-.15f,-.2f,0,0,0,0,1},15,0,0,step,0,0),releasedRight());
            default: throw new IllegalStateException("Unknown save fixture phase");
        }
    }
    private boolean sceneReady() {
        return phase==30&&nativeWorldReady();
    }
    private boolean nativeWorldReady() {
        JSONObject scene=state==null ? null : state.optJSONObject("scene");
        boolean ready=state!=null&&state.optInt("layer_type")==ROOM&&state.optJSONArray("camera").length()==5&&
            scene!=null&&expectedRoom.equalsIgnoreCase(scene.optString("location"))&&
            expectedTimeblock.equalsIgnoreCase(scene.optString("timeblock"));
        if(ready&&benchmarkSave!=null) {
            JSONObject console=state.optJSONObject("console_state");
            if(!Boolean.FALSE.equals(state.opt("console_present"))&&
                !(console!=null&&Boolean.FALSE.equals(console.opt("visible"))))
                throw new IllegalStateException("Restored benchmark requires a known absent or hidden native console");
        }
        if(ready&&confirmedScene==null) {
            try {confirmedScene=new JSONObject(scene.toString());}
            catch(org.json.JSONException error){throw new IllegalStateException(error);}
        }
        return ready;
    }
    /** Select a staged fixture through the original Restore UI, never memory writes. */
    public void restoreScene(String location,long now)throws Exception {
        if(!mode.equals("benchmark")||!restoreFromWorld||!worldReady()||
                location==null||!location.matches("R25|LBY|RC1"))
            throw new IllegalStateException("Restore transition requires the current benchmark world");
        String slot=location.equals("LBY") ? "save0098.gk3" : location.equals("R25") ? "save0097.gk3" : "save0099.gk3";
        String[] catalog=NativeSaveFile.catalog(new File(game,slot));
        if(!location.equalsIgnoreCase(catalog[1]))throw new IllegalStateException("Restore slot differs from destination");
        benchmarkSave=slot;description=catalog[0];expectedRoom=location;expectedTimeblock=catalog[2];
        sceneNavigation=null;confirmedScene=null;motion.reset();motionFirstCamera=null;
        motionOriginCamera=null;waitingCameraDelta=0;
        motionLastCamera=null;motionCameraDelta=0;restored=false;restoreListCaptured=false;
        itemHintStarted=0;itemHintStartTick=0;itemHintEndTick=0;
        itemHintInputBefore=null;itemHintInputAfter=null;
        restoreOrigin=new JSONObject(state.getJSONObject("scene").toString());advance(34,now);
    }
    public boolean wantsRestoreListCapture(long now) {
        return phase==11&&!restoreListCaptured&&now-phaseAt>=2_000_000_000L&&state!=null&&
            state.optLong("rows_expected",0)>0&&!"complete".equals(state.optString("rows_status"));
    }
    public void didRestoreListCapture(int image,int pose,long snapshot,long sampled,long received)throws Exception {
        if(!wantsRestoreListCapture(received))throw new IllegalStateException("Restore observation no longer pending");
        restoreListCaptured=true;
        JSONObject record=new JSONObject().put("token",token).put("image",image).put("pose",pose)
            .put("snapshot",snapshot).put("sampled_ns",sampled).put("received_ns",received)
            .put("requested_description",description).put("state",state)
            .put("scope","Fresh matched source UI image beside unreadable row observation; not a successful Restore");
        FixtureReport.write(new File(activity.getFilesDir(),"restore-list-observation-"+token+"-"+image+".json"),record.toString());
    }
    public boolean worldReady() {return sceneReady()&&(!worldMotion||motion.prepared());}
    public boolean motionActive(){return worldReady()&&motion.active();}
    public void alignMeasurementMotion() {
        if(!mode.equals("benchmark")||!worldMotion)throw new IllegalStateException("Aligned motion requires the moving benchmark");
        motion.alignToMeasurement();
    }
    public void beginPreparedMotion(long now)throws Exception {
        if(!motion.aligned())return;
        if(!worldReady())throw new IllegalStateException("Motion requires the prepared native world");
        motion.beginMeasurement(now);
        motionOriginCamera=new JSONArray(state.getJSONArray("camera").toString());
    }
    public long extraWarmupNanos() {return extraWarmup ? 30_000_000_000L : 0;}
    public double motionSeconds(long now) {return worldReady()?motion.seconds(now):0;}
    public boolean longTravel() {return testLongTravel;}
    public JSONObject travelState(long now)throws Exception {
        return new JSONObject().put("expected_scene",expectedRoom).put("native_tick_ms",lastTick)
            .put("state_received_ns",received).put("native_scene",state.getJSONObject("scene"))
            .put("camera",state.getJSONArray("camera")).put("motion_seconds",motion.seconds(now));
    }
    public long[] producedFrames() {
        return worldReady()&&!state.isNull("scene_frames") ? new long[]{lastTick,state.optLong("scene_frames",-1)} : null;
    }
    public void finishBenchmark(long now) throws Exception {
        if(!mode.equals("benchmark")||!worldReady()) throw new IllegalStateException("Benchmark is not in the native world");
        advance(20,now);
    }
    // Capture only a current image acknowledged after restoring the native
    // camera, never a stale menu buffer or a timer-selected title screenshot.
    public boolean wantsRestoredCapture(long sampledNanos) {
        return mode.equals("restore") && phase==13 && !captured[0] &&
            restoreReadyAt!=0 && restoreHeldFrames>=3 && sampledNanos>=restoreReadyAt;
    }
    public boolean wantsCapture(int captures) {
        return captures<(testSidneyJourney ? 3 : 2)&&!captured[captures]&&(testSidneyJourney ?
            (captures==0 ? phase==60&&sidneyDayTwoReady&&state!=null&&state.optLong("layer_type")==ROOM : captures==1 ? phase==64&&sidneyTyped : phase==65&&sidneySearched) :
            (captures==0 ? phase==4 : phase==6));
    }
    public boolean wantsStartupCapture(long sampled) {
        return testStartupSmoke&&phase==0&&startupRoomCaptureCount<6&&startupRoomFirstAt>0&&
            sampled>=startupRoomFirstAt+startupRoomCaptureCount*1_000_000_000L&&startupRoomLastFrame-startupRoomFirstFrame>=3&&
            state!=null&&state.optLong("layer_type")==ROOM;
    }
    public boolean startupCaptureSequence() {return testStartupSmoke&&phase==0;}
    public boolean startupStripReady(long sampled) {
        return startupCaptureSequence()&&startupRoomFirstAt>0&&sampled>=startupRoomFirstAt&&
            startupRoomLastFrame-startupRoomFirstFrame>=3&&state!=null&&state.optLong("layer_type")==ROOM;
    }
    public void didStartupStrip() throws Exception {startupStripDone=true;writeReport();}
    public void didStartupCapture(int image,int poseId,long snapshot,long sampled,long now) throws Exception {
        if(!wantsStartupCapture(sampled))throw new IllegalStateException("Startup capture has no current opening-room owner");
        JSONObject record=new JSONObject().put("token",token).put("image",image).put("pose_id",poseId)
            .put("snapshot",snapshot).put("sampled_ns",sampled).put("capture_finished_ns",now)
            .put("sequence",startupRoomCaptureCount+1).put("target_offset_ns",startupRoomCaptureCount*1_000_000_000L)
            .put("room_first_observed_ns",startupRoomFirstAt).put("native_state",state)
            .put("scope","Actual source image matched to a pose sampled after observed opening-room readiness; no headset presentation");
        FixtureReport.write(new File(activity.getFilesDir(),"startup-room-capture-"+token+"-"+(++startupRoomCaptureCount)+".json"),record.toString());
        startupRoomCaptured=true;writeReport();
    }
    public boolean wantsInventoryCapture() throws Exception {
        if(!testInventoryJourney||state==null)return false;
        if(restoreFromWorld&&state.optLong("layer_type")==ROOM&&(
            phase==39&&!inventoryWorldCaptured&&inventoryWorldLastFrame-inventoryWorldFirstFrame>=8||
            phase==46&&!inventoryWorldReturnCaptured))return true;
        if(phase==47&&inventoryCarriedCancelled&&!inventoryCancelCaptured&&
            state.optLong("layer_type")==INVENTORY)return true;
        return pointReady&&(
            phase==40&&!inventoryCaptured&&state.optLong("layer_type")==INVENTORY||
            phase==42&&!inventoryMenuCaptured&&state.optLong("layer_type")==INVENTORY&&inventoryInspectButton()!=null||
            phase==43&&!inspectionCaptured&&state.optLong("layer_type")==INSPECTION||
            phase==45&&!inventoryReturnCaptured&&state.optLong("layer_type")==INVENTORY);
    }
    public boolean sparseInterfaceCapture() {
        return testInventoryJourney&&phase==43;
    }
    public float probeHeadForward(long now) {
        if(!testJeanView||phase<71||phase>72)return 0;
        float progress=Math.max(0,Math.min(1,(now-phaseAt)/1_000_000_000f));
        return viewLeanMeters*(phase==71 ? progress : 1-progress);
    }
    public boolean wantsJeanCapture(long sampled) {
        return testJeanView&&phase>=70&&phase<=72&&!jeanCaptured[phase-70]&&
            state!=null&&state.optLong("layer_type")==ROOM&&sampled>=phaseAt+1_200_000_000L;
    }
    public boolean allowsBlackCapture() {return testJeanView&&phase>=70&&phase<=72;}
    public void didJeanCapture(int image,int poseId,long snapshot,long sampled,long now,int renderEye,int reviewEye,long[] visible) throws Exception {
        if(!wantsJeanCapture(sampled))throw new IllegalStateException("Jean capture has no matched settled pose");
        int stage=phase-70;jeanCaptured[stage]=true;
        JSONObject record=new JSONObject().put("token",token).put("image",image).put("stage",stage)
            .put("native_state",state).put("pose_id",poseId).put("snapshot",snapshot)
            .put("sampled_ns",sampled).put("capture_finished_ns",now).put("head_forward_m",probeHeadForward(sampled))
            .put("render_eye",renderEye).put("review_eye",reviewEye).put("full_source_visible",new JSONArray(visible))
            .put("scope","Actual native game and simulated lean/retreat, no headset delivery or performance acceptance");
        FixtureReport.write(new File(activity.getFilesDir(),"jean-capture-"+stage+"-"+token+".json"),record.toString());
        writeReport();
    }
    public void didInventoryCapture(int image,int poseId,long snapshot,long sampledNanos,long now) throws Exception {
        if(!wantsInventoryCapture())throw new IllegalStateException("Inventory capture has no current owner");
        String stage;
        if(phase==39){inventoryWorldCaptured=true;stage="retained-world";}
        else if(phase==47){inventoryCancelCaptured=true;stage="inventory-cancel";}
        else if(phase==46){inventoryWorldReturnCaptured=true;stage="world-return";}
        else if(phase==40){inventoryCaptured=true;stage="inventory";}
        else if(phase==42){inventoryMenuCaptured=true;stage="inventory-menu";}
        else if(phase==43){inspectionCaptured=true;stage="inspection";}
        else {inventoryReturnCaptured=true;stage="inventory-return";}
        JSONObject record=new JSONObject().put("token",token).put("image",image).put("native_state",state)
            .put("stage",stage)
            .put("pose_id",poseId).put("snapshot",snapshot).put("sampled_ns",sampledNanos).put("capture_finished_ns",now)
            .put("scope","Actual game with simulated controllers; no headset delivery");
        FixtureReport.write(new File(activity.getFilesDir(),stage+"-capture-"+token+".json"),record.toString());
        writeReport();
    }
    public void didCapture(int captures,long now) {if(captures>0&&captures<=(testSidneyJourney ? 3 : 2)) captured[captures-1]=true;neutralUntil=now+500_000_000L;}
    public void failed(Exception error) throws Exception {
        failure=error.getClass().getName()+": "+error.getMessage();
        writeReport();
    }
    private void writeReport() throws Exception {
        JSONObject result=new JSONObject().put("scope","native game with simulated viewer/controllers; no physical acceptance")
            .put("token",token).put("mode",mode).put("phase",phase).put("description",description)
            .put("world_aim",worldAim)
            .put("startup_smoke",testStartupSmoke)
            .put("startup_room_captured",startupRoomCaptured)
            .put("startup_strip_complete",startupStripDone)
            .put("startup_capture_count",startupRoomCaptureCount)
            .put("startup_room_first_frame",startupRoomFirstFrame).put("startup_room_last_frame",startupRoomLastFrame)
            .put("wait_startup_movies",waitStartupMovies)
            .put("startup_movie_wait_ms",startupMovieWaitNanos/1_000_000L)
            .put("startup_movie_observed_ms",startupMovieEnd>startupMovieFirst ?
                (startupMovieEnd-startupMovieFirst)/1_000_000L : 0)
            .put("startup_movie_skipped",startupMovieSkipped)
            .put("startup_movie_finished",startupMovieFirst!=0&&startupMovieEnd>startupMovieFirst)
            .put("startup_movie_input",new JSONObject()
                .put("prepared_back_samples",startupBackSamples)
                .put("first_prepared_back_ns",startupBackFirstNanos)
                .put("guest_observations",startupMovieObservations)
                .put("last_guest_observation_ns",startupMovieLastNanos)
                .put("first_guest_state",startupMovieFirstState==null ? JSONObject.NULL : startupMovieFirstState)
                .put("last_guest_state",startupMovieLastState==null ? JSONObject.NULL : startupMovieLastState))
            .put("wait_title_intro",waitTitleIntro).put("title_intro_seen",introSeen)
            .put("story_movie",testMovie==null ? JSONObject.NULL : testMovie)
            .put("sidney_journey",testSidneyJourney).put("sidney_typed",sidneyTyped).put("sidney_searched",sidneySearched).put("sidney_returned",sidneyReturned)
            .put("sidney_query",sidneyTyped ? SIDNEY_QUERY : JSONObject.NULL)
            .put("jean_view",testJeanView).put("jean_captures",new JSONArray(jeanCaptured))
            .put("jean_camera",new JSONArray(viewPose)).put("jean_lean_m",viewLeanMeters)
            .put("inventory_journey",testInventoryJourney).put("inventory_captured",inventoryCaptured)
            .put("inventory_use_response",inventoryUseResponse).put("inventory_use_back_sent",inventoryUseBackSent)
            .put("inventory_use_returned",inventoryUseReturned)
            .put("short_tap_probe",testShortTap).put("short_tap_fallback",shortTap.fallback())
            .put("short_tap_started_ns",shortTap.started()).put("short_tap_released_ns",shortTap.released())
            .put("short_tap_last_down_ns",shortTap.lastDown()).put("short_tap_down_samples",shortTap.downSamples())
            .put("inventory_world_captured",inventoryWorldCaptured)
            .put("inventory_world_return_captured",inventoryWorldReturnCaptured)
            .put("inventory_world_first_frame",inventoryWorldFirstFrame)
            .put("inventory_world_last_frame",inventoryWorldLastFrame)
            .put("inventory_carried_cancelled",inventoryCarriedCancelled)
            .put("inventory_cancel_captured",inventoryCancelCaptured)
            .put("inventory_menu_captured",inventoryMenuCaptured)
            .put("inspection_captured",inspectionCaptured).put("inventory_return_captured",inventoryReturnCaptured)
            .put("inventory_returned",inventoryReturned)
            .put("expected_room",expectedRoom)
            .put("expected_timeblock",expectedTimeblock).put("benchmark_save",benchmarkSave==null ? JSONObject.NULL : benchmarkSave)
            .put("console_free_benchmark",benchmarkSave!=null)
            .put("restore_from_world",restoreFromWorld).put("restore_origin",restoreOrigin)
            .put("extra_warmup_seconds",extraWarmup ? 30 : 0)
            .put("scene_navigation_requested",sceneNavigationRequested)
            .put("console_navigation",sceneNavigation==null ? JSONObject.NULL : sceneNavigation.progress())
            .put("native_scene",confirmedScene!=null ? confirmedScene : JSONObject.NULL)
            .put("saved",saved).put("save_cancelled",saveCancelled).put("restored",restored).put("native_quit_requested",quitRequested)
            .put("menu_recoveries",menuRecoveries).put("aims",aims)
            .put("world_motion",worldMotion).put("motion_camera_delta",motionCameraDelta)
            .put("motion_aligned_to_measurement",motion.aligned()).put("motion_prepared_ns",motion.preparedAt())
            .put("motion_origin_ns",motion.origin()).put("motion_origin_camera",motionOriginCamera)
            .put("motion_waiting_camera_delta",waitingCameraDelta)
            .put("item_hint_workload",itemHintWorkload==null ? JSONObject.NULL : itemHintWorkload)
            .put("item_hint_start_tick",itemHintStartTick).put("item_hint_end_tick",itemHintEndTick)
            .put("item_hint_input_before",itemHintInputBefore).put("item_hint_input_after",itemHintInputAfter)
            .put("motion_first_camera",motionFirstCamera).put("motion_last_camera",motionLastCamera)
            .put("restore_hold_ms",restoreHoldNanos/1_000_000L).put("restore_held_frames",restoreHeldFrames)
            .put("text_epoch_recoveries",textEpochRecoveries)
            .put("save_file",saveFile).put("save_finalized",saveFinalized).put("save_back_requested",saveBackRequested)
            .put("saved_camera",savedCamera).put("changed_camera",changedCamera).put("trace",trace);
        if(failure!=null) {
            result.put("failure",failure).put("failure_state",state==null ? JSONObject.NULL : state)
                .put("failure_state_received_ns",received).put("failure_observed_ns",System.nanoTime());
        }
        FixtureReport.write(report,result.toString());
    }
}
