package org.gk3hd.standalone;

import java.nio.ByteBuffer;

/** Synthetic protocol/history tests, never injected as physical tracking. */
public final class FramePosesTests {
    private static void check(boolean value,String text) {if(!value) throw new AssertionError(text);}
    private static ByteBuffer marker(int id) {
        ByteBuffer out=ByteBuffer.allocate(FramePoses.PIXELS*4);
        int[] words={FramePoses.MAGIC,id,~id};
        for(int i=0;i<FramePoses.PIXELS;i++) {
            byte b=(byte)((words[i/32]&(1<<(i%32)))!=0 ? 255 : 0);
            out.put(b).put(b).put(b).put((byte)255);
        }
        out.flip();return out;
    }
    public static void main(String[] args) {
        for(int id:new int[]{0,1,255,256,0x87654321,Integer.MAX_VALUE,Integer.MIN_VALUE,-1})
            check(FramePoses.decode(marker(id))==id,"Full 32-bit frame identity");
        ByteBuffer corrupt=marker(42);corrupt.put(32*4,(byte)128);
        check(FramePoses.decode(corrupt)==null,"Reject interpolated pixels");
        corrupt=marker(42);for(int c=0;c<3;c++) corrupt.put(64*4+c,(byte)0);
        check(FramePoses.decode(corrupt)==null,"Reject torn ID/inverse");
        corrupt=marker(42);corrupt.put(3,(byte)0);
        check(FramePoses.decode(corrupt)==null,"Reject missing alpha");
        check(FramePoses.decode(ByteBuffer.allocate(4))==null,"Reject incomplete strip");
        FramePoses<String> history=new FramePoses<>();
        history.remember(42,"original pose",15,10);
        history.remember(43,"newer pose",15,20);
        check("original pose".equals(history.match(42,30)),"Delayed image keeps its original pose");
        check("original pose".equals(history.match(42,40)),"Repeated image keeps its original pose");
        check(history.match(298,40)==null,"No 8-bit wrap alias");
        check("newer pose".equals(history.match(43,40)),"Advance to newer image");
        check(history.match(42,41)==null,"Reject out-of-order image");
        check(history.match(43,250_000_021L)==null,"Reject stale image");
        history.remember(44,"orientation only",5,50);
        check("orientation only".equals(history.match(44,60)),"Real 3DoF orientation can still be matched");
        history.remember(46,"valid prediction",3,61);
        check("valid prediction".equals(history.match(46,62)),"Valid prediction was confused with active tracking");
        history.remember(45,null,0,70);
        check(history.match(44,71)==null,"Tracking loss discards prior valid samples");
        history.remember(-1,"wrapped ID",15,80);
        history.remember(Integer.MIN_VALUE,"next ID",15,90);
        check("next ID".equals(history.match(Integer.MIN_VALUE,100)),"Signed boundary doesn't reorder history");
        history.clear();check(history.match(Integer.MIN_VALUE,101)==null,"Session reset discards prior samples");
        for(int i=0;i<300;i++) history.remember(i,"bounded",15,200+i);
        check(history.match(0,600)==null&&"bounded".equals(history.match(299,600)),"Bounded ring evicts old samples");
        history.clear();history.focused(true);
        check(!history.inputsCurrent(1),"Unknown pixels enabled game actions");
        history.remember(1,"held original",15,1);
        check("held original".equals(history.matchImage(1,101,2)),"Fresh immutable image did not qualify");
        check(history.inputsCurrent(2),"Fresh focused image disabled game actions");
        for(int i=2;i<302;i++)history.remember(i,"new sample "+i,15,i*1_000_000L);
        check("held original".equals(history.matchImage(1,101,1_000_000_000L)),"History eviction lost a verified immutable image");
        check(!history.inputsCurrent(1_000_000_000L),"A held image refreshed stale input time");
        history.remember(302,"recovery",15,1_000_000_001L);
        check("recovery".equals(history.matchImage(302,102,1_000_000_002L)),"Fresh source did not replace the hold");
        check(history.inputsCurrent(1_000_000_002L),"Fresh source did not restore input freshness");
        check(history.matchImage(1,101,1_000_000_003L)==null,"Reordered image revived an older pose");
        history.clear();history.remember(1,"unseen",15,1);
        check(history.matchImage(1,10,300_000_001L)==null,"Previously unseen expired image qualified");
        history.clear();history.remember(1,"original",15,1);
        history.matchImage(1,10,2);
        check(history.matchImage(1,11,300_000_001L)==null,"Changed image reused an expired association");
        check(history.matchImage(1,10,300_000_002L)==null,"Rejected image retained a fallback hold");
        history.clear();history.remember(1,"first",15,1);history.remember(2,"second",15,2);
        history.matchImage(1,10,3);
        check(history.matchImage(2,10,4)==null,"Immutable snapshot changed its frame ID");
        history.clear();history.remember(1,"unidentified",15,1);history.matchImage(1,0,2);
        check(history.matchImage(1,0,300_000_001L)==null,"Zero snapshot bypassed strict age matching");
        history.clear();history.remember(-1,"movie",15,1);history.matchImage(-1,Long.MIN_VALUE+1,2);
        check("movie".equals(history.matchImage(-1,Long.MIN_VALUE+1,300_000_001L)),"Negative movie identity was confused with unknown pixels");
        check(history.matchImage(-1,Long.MIN_VALUE+1,3)==null,"Clock rollback kept a held image");
        check(history.matchImage(-1,Long.MIN_VALUE+1,300_000_002L)==null,"Clock rollback revived the discarded association");
        history.clear();history.remember(1,"old epoch",15,1);history.matchImage(1,10,2);history.beginEpoch(4);
        check(history.matchImage(1,10,3)==null,"Reference change retained old pixels");
        history.remember(2,"before focus loss",15,4);history.matchImage(2,11,5);history.focused(false);
        check(history.matchImage(2,11,6)==null&&!history.inputsCurrent(6),"Focus loss retained an image or game actions");
        history.focused(true);history.remember(3,"before tracking loss",15,7);history.matchImage(3,12,8);
        history.remember(4,null,0,9);
        check(history.matchImage(3,12,10)==null&&!history.inputsCurrent(10),"Tracking loss retained an image or game actions");
        history.remember(5,"six degrees",3,11);history.matchImage(5,13,12);
        history.remember(6,"orientation only",1,13);
        check(history.matchImage(5,13,14)==null,"Position-validity loss retained a prior 6DoF image");
        check("orientation only".equals(history.matchImage(6,14,15)),"Real orientation-only mode did not recover");
        System.out.println("Frame association passed: full IDs, corruption, delay, repeat, ordering, age, tracking loss and reset");
    }
}
