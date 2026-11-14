package org.gk3hd.standalone;

/** Pure policy checks: never infer pixel completion from a pose ID or target age. */
public final class OutputCompletionTests {
    private static int checks;
    private static void check(boolean value,String message) {
        checks++;if(!value) throw new AssertionError(message);
    }
    private static void checkRepeatedSubmissionSpacing() {
        OutputCompletion output=new OutputCompletion(3);
        int[] lastRead={-3,-3,-3};
        long[] snapshots={7,7,7,8,9,9,9,0,0,10,10,11};
        int writes=0;
        for(int frame=0;frame<snapshots.length;frame++) {
            long snapshot=snapshots[frame];
            int previous=output.lastSubmitted();
            boolean repeat=snapshot!=0&&previous>=0&&output.retained(previous)==snapshot;
            int target=repeat?previous:output.writableTarget();
            if(repeat) {
                check(!output.required(target,snapshot,true),"Repeated output lost its completed pixels");
            } else {
                check(frame-lastRead[target]>=3,"Writable target was submitted too recently");
                check(target==output.writableTarget(),"Selecting a target consumed a submission");
                if(snapshot==0)output.completedBlank(target);
                else output.completed(target,snapshot);
                writes++;
            }
            output.submitted(target);
            lastRead[target]=frame;
        }
        check(writes==7,"Repeating a completed image requested another write");
        output.reset();
        check(output.lastSubmitted()==-1&&output.writableTarget()==0,"A new context kept prior submissions");
    }
    public static void main(String[] args) {
        checkRepeatedSubmissionSpacing();
        OutputCompletion output=new OutputCompletion(3);
        check(output.required(0,7,true),"Fresh target assumed completed");
        check(output.retained(0)==0,"Fresh target offered stale pixels");
        output.completed(0,7);
        check(output.retained(0)==7,"Completed identity was lost");
        check(!output.required(0,7,true),"Exact untouched completed image waited again");
        check(output.required(0,7,false),"A rewritten image skipped completion");
        check(output.required(1,7,true),"One target borrowed another target's completion");
        check(output.required(0,8,true),"Different pixels sharing a pose skipped completion");
        check(output.required(0,0,true),"Unknown image identity skipped completion");
        output.completedBlank(0);
        check(output.hasCompletedBlank(0)&&!output.hasCompletedBlank(1),"Completed black pixels escaped their target");
        check(output.retained(0)==0&&output.required(0,7,true),"Black clear retained an old image");
        output.completed(0,8);
        check(!output.hasCompletedBlank(0)&&output.retained(0)==8,"Stereo write retained old black pixels");
        output.completedBlank(0);
        output.completed(1,9);output.completed(2,10);output.reset();
        check(!output.hasCompletedBlank(0),"Context recreation retained a black clear");
        for(int i=0;i<3;i++) check(output.retained(i)==0,"Context recreation retained old pixels");
        for(int iteration=1;iteration<=1000;iteration++) {
            int slot=iteration%3;long snapshot=100+iteration;
            check(output.required(slot,snapshot,false),"New image skipped its write wait");
            output.completed(slot,snapshot);
            for(int duplicate=0;duplicate<3;duplicate++)
                check(!output.required(slot,snapshot,true),"Repeated completed output waited again");
            check(output.required(slot,snapshot,false),"Later target write was ignored");
        }
        System.out.println("Output completion policy passed "+checks+" checks");
    }
}
