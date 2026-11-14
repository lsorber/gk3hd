package org.gk3hd.standalone;

/** Deterministic keyboard/ownership sequence, not evidence of game navigation. */
public final class NativeSceneNavigationTests {
    private static int checks;
    private static void check(boolean value){if(!value)throw new AssertionError("Console navigation check "+checks);checks++;}
    private static final class Keyboard implements NativeSceneNavigation.Keyboard {
        boolean console,focused,ready,held,enabled=true,openAllowed=true;int toggles,presses;char text;
        NativeSceneNavigation.Key active;final StringBuilder typed=new StringBuilder();
        public boolean ready(){return enabled;}
        public void press(NativeSceneNavigation.Key key,char character){check(!held);held=true;active=key;text=character;presses++;}
        public void release(NativeSceneNavigation.Key key) {
            check(held&&active==key);held=false;
            if(key==NativeSceneNavigation.Key.TOGGLE){if(!openAllowed){toggles++;return;}console=!console;focused=console;toggles++;}
            if(key==NativeSceneNavigation.Key.CLEAR){check(console);typed.setLength(0);focused=false;}
            if(key==NativeSceneNavigation.Key.TEXT){check(console);typed.append(text);}
            if(key==NativeSceneNavigation.Key.ENTER){check(console);ready=true;focused=false;}
        }
    }
    public static void main(String[] args) {
        Keyboard sceneKeys=new Keyboard();
        NativeSceneNavigation sceneOnly=NativeSceneNavigation.location("LBY",sceneKeys);
        boolean sceneDone=false;long sceneTick=1;
        for(long now=1;now<20_000_000_000L&&!sceneDone;now+=50_000_000L)
            sceneDone=sceneOnly.tick(now,++sceneTick,sceneKeys.ready,sceneKeys.console ? 1 : 0);
        check(sceneDone&&!sceneKeys.held&&!sceneKeys.console&&sceneKeys.ready);
        check(sceneKeys.typed.toString().equals("SetLocation(\"LBY\");"));
        for(String invalid:new String[]{null,"", "LBY;", "r25", "R25\""}) {
            try {NativeSceneNavigation.location(invalid,sceneKeys);throw new AssertionError("Invalid location accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        Keyboard keys=new Keyboard();keys.typed.append("RetainedCommand();");NativeSceneNavigation navigation=new NativeSceneNavigation("LBY",keys);
        boolean done=false;long tick=1;
        for(long now=1;now<20_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console&&keys.ready);
        check(keys.typed.toString().equals("SetLocationTime(\"LBY\",\"110a\");"));
        check(!keys.typed.toString().contains("RetainedCommand"));
        keys=new Keyboard();navigation=new NativeSceneNavigation("RC1",keys);
        check(!navigation.tick(1,1,false,-1)&&keys.held);
        check(!navigation.tick(500_000_001L,1,false,-1)&&keys.held&&keys.toggles==0);
        check(!navigation.tick(600_000_001L,2,false,-1)&&!keys.held&&keys.toggles==1);
        try {navigation.tick(61_000_000_001L,3,false,-1);throw new AssertionError("Missing destination accepted");}
        catch(IllegalStateException expected){check(!keys.held&&keys.typed.length()==0);}
        keys=new Keyboard();navigation=new NativeSceneNavigation("R25",keys);navigation.tick(1,1,false,-1);
        try {navigation.tick(61_000_000_001L,1,false,-1);throw new AssertionError("Held chord survived timeout");}
        catch(IllegalStateException expected){check(!keys.held);}
        keys=new Keyboard();navigation=new NativeSceneNavigation("LBY",keys);done=false;tick=1;
        for(long now=1;now<20_000_000_000L;now+=50_000_000L)
            done|=navigation.tick(now,++tick,keys.ready,-1);
        check(!done); // Missing native observation is never closed-console proof.
        keys=new Keyboard();keys.enabled=false;navigation=new NativeSceneNavigation("LBY",keys);
        check(!navigation.tick(1,1,false,-1)&&keys.presses==0&&!keys.held);
        keys.enabled=true;check(!navigation.tick(2,2,false,-1)&&keys.presses==1&&keys.held);
        for(String invalid:new String[]{"", "LBY;", "r25", "R25\""}) {
            try {new NativeSceneNavigation(invalid,keys);throw new AssertionError("Invalid console target accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        keys=new Keyboard();navigation=NativeSceneNavigation.movie("205PEND",keys);done=false;tick=1;
        for(long now=1;now<20_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        check(keys.typed.toString().equals("PlayFullScreenMovie(\"205PEND\");"));
        for(String invalid:new String[]{"", "../205PEND", "205PEND.BIK", "205PEND\");Quit();", "a", "12345678901234567"}) {
            try {NativeSceneNavigation.movie(invalid,keys);throw new AssertionError("Invalid movie target accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        keys=new Keyboard();navigation=new NativeSceneNavigation("R25","205p",keys);done=false;tick=1;
        for(long now=1;now<20_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        check(keys.typed.toString().equals("SetLocationTime(\"R25\",\"205p\");"));
        int completedPresses=keys.presses;
        check(navigation.tick(120_000_000_000L,++tick,true,0));
        check(keys.presses==completedPresses&&!keys.held);
        keys=new Keyboard();navigation=NativeSceneNavigation.sidney(keys);done=false;tick=1;
        for(long now=1;now<20_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        check(keys.typed.toString().equals("CallSheep(\"r25_all\",\"GraceStartSidney\");"));
        for(String invalid:new String[]{"", "205p;Quit();", "205p\"", "205x", "205P"}) {
            try {new NativeSceneNavigation("R25",invalid,keys);throw new AssertionError("Invalid timeblock accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        keys=new Keyboard();keys.openAllowed=false;navigation=NativeSceneNavigation.sidney(keys);boolean openingRejected=false;tick=1;
        try {
            for(long now=1;now<8_000_000_000L;now+=50_000_000L)navigation.tick(now,++tick,false,0);
        } catch(IllegalStateException expected){openingRejected=true;}
        check(openingRejected&&keys.toggles==3&&!keys.held&&keys.typed.length()==0);
        keys=new Keyboard();navigation=NativeSceneNavigation.jeanLobby(keys);done=false;tick=1;
        for(long now=1;now<35_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        check(keys.typed.toString().equals("SetActorLocation(\"Jean\",\"LBY\");SetLocationTime(\"LBY\",\"110a\");"));
        keys=new Keyboard();double[] pose={90,0,401.65,72.31,254.96};
        navigation=NativeSceneNavigation.camera(pose,keys);pose[2]=0;
        double[] actual={Math.PI/2,0,401.65,72.31,254.96};
        check(navigation.matchesCamera(actual));
        actual[0]+=2*Math.PI;check(navigation.matchesCamera(actual));
        actual[2]+=.1;check(!navigation.matchesCamera(actual));actual[2]-=.1;
        actual[0]+=.01;check(!navigation.matchesCamera(actual));
        check(!navigation.matchesCamera(null)&&!navigation.matchesCamera(new double[4]));
        actual[0]=Double.NaN;check(!navigation.matchesCamera(actual));
        done=false;tick=1;
        for(long now=1;now<25_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        String typed=keys.typed.toString();check(typed.startsWith("CutToCameraAngleX(")&&typed.endsWith(");"));
        String[] arguments=typed.substring(18,typed.length()-2).split(",");
        double[] requested={90,0,401.65,72.31,254.96};check(arguments.length==5);
        for(int i=0;i<5;i++)check(Math.abs(Double.parseDouble(arguments[i])-requested[i])<.0001&&arguments[i].contains("."));
        for(double[] invalid:new double[][]{null,new double[4],{181,0,0,0,0},{0,90,0,0,0},{0,0,Double.NaN,0,0},{0,0,0,Double.POSITIVE_INFINITY,0},{0,0,10001,0,0}}) {
            try {NativeSceneNavigation.camera(invalid,keys);throw new AssertionError("Invalid camera accepted");}
            catch(IllegalArgumentException expected){checks++;}
        }
        keys=new Keyboard();navigation=NativeSceneNavigation.jeanCamera(requested,keys);done=false;tick=1;
        for(long now=1;now<40_000_000_000L&&!done;now+=50_000_000L)
            done=navigation.tick(now,++tick,keys.ready,keys.console ? 1 : 0);
        check(done&&!keys.held&&!keys.console);
        check(keys.typed.toString().startsWith("SetActorPosition(\"Jean\",\"JEAN_INIT\");CutToCameraAngleX("));
        check(navigation.matchesCamera(new double[]{Math.PI/2,0,401.65,72.31,254.96}));
        System.out.println(checks+" console input ordering/acknowledgement/timeout/validation checks passed");
    }
}
