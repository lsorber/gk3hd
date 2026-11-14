package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** CPU labels never replace completed GPU evidence, backing ownership or epochs. */
public final class FrameIdentityTests {
    private static int checks;
    private static void check(boolean okay,String reason) {checks++;if(!okay)throw new AssertionError(reason);}
    private static void rejects(Runnable operation,String reason) {
        boolean rejected=false;try {operation.run();}catch(IllegalStateException expected) {rejected=true;}
        check(rejected,reason);
    }
    private static ImageIdentity.Snapshot packet(int epoch,int serial,int pose) {
        return packet(epoch,serial,pose,0);
    }
    private static ImageIdentity.Snapshot packet(int epoch,int serial,int pose,int movie) {
        ByteBuffer bytes=ByteBuffer.allocate(320).order(ByteOrder.LITTLE_ENDIAN);
        bytes.put(new byte[]{'G','P','M','P','0','0','0','2'});
        bytes.putInt(2).putInt(320).putInt(640).putInt(64).putInt(2).putInt(serial);
        bytes.putInt(epoch).putInt(2).putInt(3).putInt(4);
        bytes.position(64);bytes.putInt(0).putInt(serial).putInt(pose).putInt(movie).putInt(1);
        return ImageIdentity.decode((ByteBuffer)bytes.position(0));
    }
    private static ByteBuffer gpu(int epoch,int serial,int pose) {
        ByteBuffer bytes=ByteBuffer.allocate(FrameIdentity.PIXELS*4);
        for(int value:new int[]{pose,epoch,2,3,4,serial})
            for(int word:new int[]{FramePoses.MAGIC,value,~value})
                for(int bit=0;bit<32;bit++) {
                    byte channel=(byte)((word&(1<<bit))==0 ? 0 : 255);
                    bytes.put(channel).put(channel).put(channel).put((byte)255);
                }
        return (ByteBuffer)bytes.flip();
    }
    private static final class Source implements FrameIdentity.Source {
        ImageIdentity.Snapshot value;
        @Override public ImageIdentity.Snapshot read() {return value;}
    }
    public static void main(String[] args) {
        Source source=new Source();FrameIdentity identities=new FrameIdentity(source);
        Object owner=new Object(),backing=new Object();
        source.value=packet(1,1,Integer.MIN_VALUE);
        FrameIdentity.Captured first=identities.acquire(owner,backing,640,64,1);
        check(first.predicted==null&&first.flip==null,"An unverified backing cannot predict its identity or orientation");
        source.value=packet(1,2,-1);
        ImageIdentity.Resolved completed=identities.complete(first,gpu(1,1,Integer.MIN_VALUE),0);
        check(completed.pose==Integer.MIN_VALUE&&completed.composition==1,"Completion uses the captured packet, not latest CPU state");
        rejects(()->identities.complete(first,gpu(1,1,Integer.MIN_VALUE),0),"A completion is consumed once");
        FrameIdentity.Captured second=identities.acquire(owner,backing,640,64,2);
        check(second.predicted!=null&&second.predicted.pose==-1&&!second.flip,"A verified backing predicts its next acquired lease");
        source.value=packet(1,3,17);
        check(identities.complete(second,gpu(1,2,-1),0).pose==-1,"A later publication cannot relabel an early-selected image");
        FrameIdentity.Captured corrupt=identities.acquire(owner,backing,640,64,3);
        rejects(()->identities.complete(corrupt,gpu(1,3,18),0),"Predictions still require independent GPU pose agreement");
        source.value=packet(1,4,19);
        FrameIdentity.Captured incomplete=identities.acquire(owner,backing,640,64,4);
        rejects(()->identities.complete(incomplete,ByteBuffer.allocate(4),0),"Missing GPU evidence must not silently accept a predicted image");
        source.value=null;
        FrameIdentity.Captured absent=identities.acquire(owner,backing,640,64,5);
        check(absent.predicted==null&&identities.complete(absent,gpu(1,5,20),0)==null,"An unavailable metadata packet keeps GPU-only fallback");

        // A generation is invalidated even if a stale writer reuses its epoch.
        source.value=packet(1,6,21);
        FrameIdentity.Captured old=identities.acquire(owner,new Object(),640,64,6);
        identities.invalidate();identities.complete(old,gpu(1,6,21),0);
        source.value=packet(1,7,22);
        check(identities.acquire(owner,old.backing,640,64,7).predicted==null,"Late completion after invalidation cannot repopulate bindings");

        // Complete newer work first, then an older bootstrap on the same backing.
        FrameIdentity ordered=new FrameIdentity(source);Object reused=new Object();
        source.value=packet(2,1,41);FrameIdentity.Captured older=ordered.acquire(owner,reused,640,64,10);
        source.value=packet(2,2,42);FrameIdentity.Captured newer=ordered.acquire(owner,reused,640,64,11);
        ordered.complete(newer,gpu(2,2,42),0);ordered.complete(older,gpu(2,1,41),0);
        source.value=packet(2,2,42);
        check(ordered.acquire(owner,reused,640,64,12).predicted==null,"An old bootstrap cannot roll a newer binding backwards");
        source.value=packet(2,3,43);
        FrameIdentity.Captured third=ordered.acquire(owner,reused,640,64,12);
        check(third.predicted!=null&&third.predicted.composition==3,"The preserved new binding accepts a genuine new composition");
        rejects(()->identities.complete(third,gpu(2,3,43),0),"Another tracker cannot consume a foreign captured lease");
        check(ordered.complete(third,gpu(2,3,43),0).pose==43,"Foreign rejection did not consume the actual owner's completion");
        source.value=packet(3,1,44);
        check(ordered.acquire(owner,reused,640,64,13).predicted==null,"Pool recreation requires a new GPU bootstrap");

        Source flippedSource=new Source();flippedSource.value=packet(4,1,51);
        FrameIdentity flipped=new FrameIdentity(flippedSource);Object flippedBacking=new Object();
        FrameIdentity.Captured upsideDown=flipped.acquire(owner,flippedBacking,640,64,1);
        ByteBuffer both=ByteBuffer.allocate(FrameIdentity.PIXELS*8);both.position(FrameIdentity.PIXELS*4);both.put(gpu(4,1,51));
        flipped.complete(upsideDown,both,FrameIdentity.PIXELS*4);
        flippedSource.value=packet(4,2,52);FrameIdentity.Captured wrongFlip=flipped.acquire(owner,flippedBacking,640,64,2);
        check(wrongFlip.predicted!=null&&wrongFlip.flip,"Orientation belongs to the exact verified backing");
        rejects(()->flipped.complete(wrongFlip,gpu(4,2,52),0),"A changing orientation cannot silently invert early-selected output");

        Source boundedSource=new Source();FrameIdentity bounded=new FrameIdentity(boundedSource);
        for(int i=1;i<=64;i++) {
            boundedSource.value=packet(5,i,i);Object image=new Object();
            bounded.complete(bounded.acquire(owner,image,640,64,i),gpu(5,i,i),0);
            check(bounded.counts()[3]<=ImageIdentity.MAX_IMAGES,"Backing history remains bounded");
        }
        check(bounded.counts()[0]==64,"Uncached images still receive independent verification");
        Source movieSource=new Source();movieSource.value=packet(6,1,61,7);
        FrameIdentity movieFrames=new FrameIdentity(movieSource);Object movieBacking=new Object();
        FrameIdentity.Captured oldMovie=movieFrames.acquire(owner,movieBacking,640,64,1);
        check(movieFrames.complete(oldMovie,gpu(6,1,61),0).movie==7,"Movie owner belongs to the verified composition");
        movieSource.value=packet(6,2,62,8);
        check(movieFrames.acquire(owner,movieBacking,640,64,1).predicted.movie==7,"A held image cannot become the next movie's overlay");
        FrameIdentity.Captured newMovie=movieFrames.acquire(owner,movieBacking,640,64,2);
        check(newMovie.predicted.movie==8&&movieFrames.complete(newMovie,gpu(6,2,62),0).movie==8,"New owned composition carries its new movie");
        movieSource.value=packet(6,3,63,0);
        FrameIdentity.Captured ordinary=movieFrames.acquire(owner,movieBacking,640,64,3);
        check(ordinary.predicted.movie==0&&movieFrames.complete(ordinary,gpu(6,3,63),0).movie==0,"Returning to ordinary output clears native movie ownership");
        Source copySource=new Source();FrameIdentity copies=new FrameIdentity(copySource);
        copySource.value=packet(7,1,71,9);
        FrameIdentity.Captured copy=copies.captureCopy(640,64);
        check(copy.predicted==null&&copy.flip==null,"A private copy cannot predict identity before GPU completion");
        copySource.value=packet(7,2,72,10);
        ImageIdentity.Resolved copyResult=copies.complete(copy,gpu(7,1,71),0);
        check(copyResult.pose==71&&copyResult.composition==1&&copyResult.movie==9&&copyResult.lease==0,
            "Copy completion must retain its exact original pose, composition and movie without inventing a lease");
        rejects(()->copies.complete(copy,gpu(7,1,71),0),"A copied completion cannot be consumed twice");
        FrameIdentity.Captured nextCopy=copies.captureCopy(640,64);
        check(nextCopy.predicted==null,"Reusing copy storage must not learn a producer-image prediction");
        check(copies.complete(nextCopy,gpu(7,2,72),0).movie==10,"The next copy verifies its new movie owner");
        FrameIdentity.Captured wrongEpoch=copies.captureCopy(640,64);
        rejects(()->copies.complete(wrongEpoch,gpu(8,2,72),0),"A copied image from another session cannot become an overlay");
        FrameIdentity.Captured wrongPose=copies.captureCopy(640,64);
        check(copies.complete(wrongPose,gpu(7,2,73),0)==null,"Unmatched copied pixels must not inherit the latest movie owner");
        FrameIdentity.Captured wrongSize=copies.captureCopy(641,64);
        check(copies.complete(wrongSize,gpu(7,2,72),0)==null,"A copied image with another extent cannot inherit an overlay");
        FrameIdentity.Captured damaged=copies.captureCopy(640,64);
        rejects(()->copies.complete(damaged,ByteBuffer.allocate(4),0),"Copied output still requires valid independent GPU tags");
        copySource.value=null;
        check(copies.complete(copies.captureCopy(640,64),gpu(7,3,74),0)==null,
            "Missing copy metadata cannot grant a movie owner");
        System.out.println(checks+" immutable identity, prediction, independent verification, orientation and lifecycle checks passed");
    }
}
