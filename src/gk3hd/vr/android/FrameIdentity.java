package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.IdentityHashMap;

/** Freeze labels for acquired or copied immutable images. GPU ownership remains external. */
public final class FrameIdentity {
    public static final int PIXELS=FramePoses.PIXELS*6;
    public interface Source {ImageIdentity.Snapshot read();}
    public static final class Captured {
        final ImageIdentity.Snapshot snapshot;
        final ImageIdentity.Resolved predicted;
        final Object owner,backing;
        final int width,height;
        final long lease,generation;
        final Boolean flip;
        private final FrameIdentity tracker;
        private boolean completed;
        private Captured(ImageIdentity.Snapshot snapshot,ImageIdentity.Resolved predicted,Object owner,
                         Object backing,int width,int height,long lease,long generation,Boolean flip,FrameIdentity tracker) {
            this.snapshot=snapshot;this.predicted=predicted;this.owner=owner;this.backing=backing;
            this.width=width;this.height=height;this.lease=lease;this.generation=generation;this.flip=flip;
            this.tracker=tracker;
        }
    }
    private final Source source;
    private final IdentityHashMap<Object,ImageIdentity.Binding> bindings=new IdentityHashMap<>();
    private final IdentityHashMap<Object,Boolean> orientations=new IdentityHashMap<>();
    private int[] epoch;
    private long generation,verified,predicted,missing;
    public FrameIdentity(Source source) {
        if(source==null)throw new IllegalArgumentException("Missing image identity source");
        this.source=source;
    }
    public Captured acquire(Object owner,Object backing,int width,int height,long lease) {
        if(owner==null||backing==null||width<PIXELS||height<2||lease<=0)
            throw new IllegalArgumentException("Image identity requires an acquired immutable backing");
        ImageIdentity.Snapshot snapshot=source.read();ImageIdentity.Resolved result=null;
        if(snapshot==null)missing++;
        else {
            if(!Arrays.equals(epoch,snapshot.epoch())) {invalidate();epoch=snapshot.epoch();}
            ImageIdentity.Binding binding=bindings.get(backing);
            if(binding!=null)result=binding.resolve(snapshot,owner,backing,width,height,lease);
        }
        Boolean flip=result==null ? null : orientations.get(backing);
        if(result!=null&&flip!=null)predicted++;
        return new Captured(snapshot,result,owner,backing,width,height,lease,generation,flip,this);
    }
    /** Capture metadata under the source read dependency; verify tags only after the copy fence. */
    public Captured captureCopy(int width,int height) {
        if(width<PIXELS||height<2)throw new IllegalArgumentException("Invalid copied image extent");
        ImageIdentity.Snapshot snapshot=source.read();
        if(snapshot==null)missing++;
        return new Captured(snapshot,null,null,null,width,height,0,generation,null,this);
    }
    private static Integer block(ByteBuffer bytes,int offset) {
        if(bytes==null||offset<0||offset>bytes.limit()-FramePoses.PIXELS*4)return null;
        ByteBuffer part=bytes.duplicate();part.position(offset);part.limit(offset+FramePoses.PIXELS*4);
        return FramePoses.decode(part.slice());
    }
    /** Called only after the metadata readback fence signals, including early-selected images. */
    public ImageIdentity.Resolved complete(Captured captured,ByteBuffer bytes,int offset) {
        if(captured==null||captured.tracker!=this||captured.completed)
            throw new IllegalStateException("Foreign or already verified image");
        captured.completed=true;
        Integer pose=block(bytes,offset),serial=block(bytes,offset+FramePoses.PIXELS*4*5);
        int[] gpuEpoch=new int[4];boolean valid=pose!=null&&serial!=null;
        for(int i=0;i<4;i++) {
            Integer value=block(bytes,offset+(i+1)*FramePoses.PIXELS*4);
            if(value==null)valid=false;else gpuEpoch[i]=value;
        }
        // A missing CPU packet keeps the original GPU-ID path. A prediction
        // may never escape independent verification by becoming a fallback.
        if(captured.snapshot==null)return null;
        if(!valid||!Arrays.equals(captured.snapshot.epoch(),gpuEpoch))throw mismatch();
        long composition=serial&0xffffffffL;
        if(captured.lease==0) {
            ImageIdentity.Resolved copy=ImageIdentity.completedCopy(captured.snapshot,gpuEpoch,composition,pose,
                captured.width,captured.height);
            // An ordered copy may trail the bounded metadata publication.
            // Missing association never grants a movie overlay or a prediction.
            if(copy==null)missing++;else verified++;
            return copy;
        }
        ImageIdentity.Resolved match=captured.predicted;
        ImageIdentity.Binding binding=null;
        if(match==null) {
            binding=ImageIdentity.bootstrap(captured.snapshot,gpuEpoch,composition,pose,
                captured.owner,captured.backing,captured.width,captured.height,captured.lease);
            if(binding==null)throw mismatch();
            match=binding.resolve(captured.snapshot,captured.owner,captured.backing,
                captured.width,captured.height,captured.lease);
        }
        boolean flip=offset!=0;
        if(match==null||match.composition!=composition||match.pose!=pose||match.lease!=captured.lease||
           (captured.flip!=null&&captured.flip!=flip))throw mismatch();
        if(captured.generation==generation&&Arrays.equals(epoch,gpuEpoch)) {
            if(binding!=null) {
                // Old completions cannot replace a newer binding on this backing.
                ImageIdentity.Binding current=bindings.get(captured.backing);
                if(current!=null&&current.resolve(captured.snapshot,captured.owner,captured.backing,
                    captured.width,captured.height,captured.lease)==null) {verified++;return match;}
                if(bindings.size()>=ImageIdentity.MAX_IMAGES&&!bindings.containsKey(captured.backing)) {
                    verified++;return match;
                }
                bindings.put(captured.backing,binding);
            }
            orientations.put(captured.backing,flip);
        }
        verified++;return match;
    }
    private static IllegalStateException mismatch() {
        return new IllegalStateException("Immutable image CPU/GPU identity mismatch");
    }
    public void invalidate() {bindings.clear();orientations.clear();epoch=null;generation++;}
    public long[] counts() {return new long[]{verified,predicted,missing,bindings.size()};}
}
