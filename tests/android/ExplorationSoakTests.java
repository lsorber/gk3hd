package org.gk3hd.standalone;

public final class ExplorationSoakTests {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError(checks);}
    public static void main(String[] args) {
        check(new ExplorationSoak(0).complete());
        ExplorationSoak soak=new ExplorationSoak(600);
        check(!soak.complete());soak.observe(1);soak.observe(599_000_000_001L);
        check(!soak.complete());soak.observe(600_000_000_001L);
        check(soak.complete()&&soak.frames()==3&&soak.elapsedNanos()==600_000_000_000L);
        check(soak.maximumGapNanos()==599_000_000_000L);
        // A long gap is retained as evidence, rather than silently restarting
        // the reliability interval and extending the owned game's lifetime.
        boolean invalid=false;try{soak.observe(600_000_000_001L);}catch(IllegalStateException expected){invalid=true;}
        check(invalid);
        for(int seconds:new int[]{-1,601}) {
            invalid=false;try{new ExplorationSoak(seconds);}catch(IllegalArgumentException expected){invalid=true;}
            check(invalid);
        }
        System.out.println(checks+" exploration duration/progress/gap/bound checks passed");
    }
}
