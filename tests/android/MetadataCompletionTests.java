package org.gk3hd.standalone;

/** Completion may precede selection, follow receipt, or arrive out of order. */
public final class MetadataCompletionTests {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("Metadata completion "+checks);}
    private static void fails(Runnable action){boolean failed=false;try{action.run();}catch(IllegalStateException expected){failed=true;}check(failed);}
    private static long[] frame(long snapshot) {
        long[] row=new long[21];row[0]=snapshot;row[1]=0xffffffffL;row[12]=snapshot+100;
        row[13]=0x80000000L;row[14]=2;row[15]=3;row[16]=4;row[18]=10;row[19]=11;row[20]=snapshot+20;return row;
    }
    private static long[] completion(long snapshot) {
        long[] f=frame(snapshot);return new long[]{f[0],f[1],f[12],f[13],f[14],f[15],f[16],100,101,102,103,104,105,f[18],f[19],f[20]};
    }
    public static void main(String[] args) throws Exception {
        MetadataCompletionTrace trace=new MetadataCompletionTrace();
        long[] early=completion(1);early[9]=0;trace.complete(early);early[1]=0;
        trace.issue(frame(1));check(trace.pending()==0&&trace.completed()==1&&trace.rows()[0][1]==0xffffffffL);
        trace.issue(frame(2));trace.issue(frame(3));trace.complete(completion(3));
        check(trace.pending()==1&&trace.completed()==2&&trace.rows()[1][0]==3);
        trace.complete(completion(2));check(trace.pending()==0&&trace.issued()==3);
        long[][] copy=trace.rows();copy[0][0]=99;check(trace.rows()[0][0]==1);
        check(!trace.issue(frame(2)));check(trace.issued()==3&&trace.completed()==3&&trace.repeated()==1);
        long[] relabelled=frame(2);relabelled[12]++;
        fails(()->trace.issue(relabelled));fails(()->trace.complete(completion(2)));
        MetadataCompletionTrace repaint=new MetadataCompletionTrace();
        check(repaint.issue(frame(10)));check(!repaint.issue(frame(10)));
        check(repaint.pending()==1&&repaint.issued()==1&&repaint.repeated()==1);
        repaint.complete(completion(10));check(!repaint.issue(frame(10)));
        check(repaint.pending()==0&&repaint.completed()==1&&repaint.repeated()==2);
        check(repaint.issue(frame(11)));check(repaint.pending()==1&&repaint.issued()==2);
        long[] wrongPose=frame(11);wrongPose[1]--;
        fails(()->repaint.issue(wrongPose));check(repaint.pending()==1);
        MetadataCompletionTrace mismatch=new MetadataCompletionTrace();mismatch.issue(frame(4));
        for(int i:new int[]{1,2,3,4,5,6,13,14,15}) {
            long[] wrong=completion(4);wrong[i]++;fails(()->mismatch.complete(wrong));check(mismatch.pending()==1);
        }
        mismatch.complete(completion(4));check(mismatch.pending()==0);
        for(int i:new int[]{7,8,9,10,11,12}) {
            long[] wrong=completion(5);wrong[i]=i==7 ? 0 : 1;fails(()->trace.complete(wrong));
        }
        MetadataCompletionTrace bounded=new MetadataCompletionTrace();
        for(int i=1;i<=8;i++)bounded.issue(frame(i));fails(()->bounded.issue(frame(9)));
        // Unselected source images are bounded independently of selected outputs.
        MetadataCompletionTrace recent=new MetadataCompletionTrace();
        for(int i=1;i<=100;i++)recent.complete(completion(i));
        recent.issue(frame(100));check(recent.completed()==1);recent.issue(frame(1));check(recent.pending()==1);
        boolean[] denied={false};Thread other=new Thread(()->{try{trace.pending();}catch(IllegalStateException expected){denied[0]=true;}});
        other.start();other.join();check(denied[0]);
        System.out.println(checks+" metadata completion identity/order/time/bound checks passed");
    }
}
