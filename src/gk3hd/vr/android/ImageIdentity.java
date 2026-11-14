package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** Immutable image/pose association. This never grants GPU completion or ownership. */
public final class ImageIdentity {
    public static final int BYTES=320, MAX_IMAGES=16;
    private static final byte[] MAGIC={'G','P','M','P','0','0','0','2'};
    private ImageIdentity() { }
    private static long unsigned(int value) {return value&0xffffffffL;}

    public static final class Snapshot {
        public final int width,height,count;
        public final long latest;
        private final int[] epoch,serials,poses,movies;
        private Snapshot(int width,int height,int count,int latest,int[] epoch,int[] serials,int[] poses,int[] movies) {
            this.width=width;this.height=height;this.count=count;this.latest=unsigned(latest);
            this.epoch=epoch;this.serials=serials;this.poses=poses;this.movies=movies;
        }
        public int pose(int slot) {
            if(slot<0||slot>=count) throw new IndexOutOfBoundsException();
            return poses[slot];
        }
        public long serial(int slot) {
            if(slot<0||slot>=count) throw new IndexOutOfBoundsException();
            return unsigned(serials[slot]);
        }
        public int[] epoch() {return epoch.clone();}
        public long movie(int slot) {
            if(slot<0||slot>=count)throw new IndexOutOfBoundsException();return unsigned(movies[slot]);
        }
    }

    /** Decode one frozen v2 packet, including its exact external-movie owner. */
    public static Snapshot decode(ByteBuffer source) {
        if(source==null||source.remaining()!=BYTES) return null;
        ByteBuffer in=source.slice().order(ByteOrder.LITTLE_ENDIAN);
        for(int i=0;i<MAGIC.length;i++) if(in.get(i)!=MAGIC[i]) return null;
        if(in.getInt(8)!=2||in.getInt(12)!=BYTES) return null;
        int width=in.getInt(16),height=in.getInt(20),count=in.getInt(24),latest=in.getInt(28);
        if(width<576||width>8192||height<2||height>8192||count<1||count>MAX_IMAGES) return null;
        int[] epoch=new int[4],serials=new int[MAX_IMAGES],poses=new int[MAX_IMAGES],movies=new int[MAX_IMAGES];
        boolean nonzero=false;
        for(int i=0;i<epoch.length;i++) {epoch[i]=in.getInt(32+4*i);nonzero|=epoch[i]!=0;}
        if(!nonzero) return null;
        for(int i=48;i<64;i++) if(in.get(i)!=0) return null;
        long maximum=0;
        for(int i=0;i<MAX_IMAGES;i++) {
            int base=64+16*i,index=in.getInt(base),serial=in.getInt(base+4);
            int pose=in.getInt(base+8),movie=in.getInt(base+12);
            if(i>=count) {
                if(index!=0||serial!=0||pose!=0||movie!=0) return null;
                continue;
            }
            if(index!=i||unsigned(serial)>unsigned(latest)||(serial==0&&(pose!=0||movie!=0))) return null;
            if(serial!=0) for(int j=0;j<i;j++) if(serials[j]==serial) return null;
            serials[i]=serial;poses[i]=pose;movies[i]=movie;maximum=Math.max(maximum,unsigned(serial));
        }
        if(maximum!=unsigned(latest)) return null;
        return new Snapshot(width,height,count,latest,epoch,serials,poses,movies);
    }

    public static final class Resolved {
        public final long composition,lease,movie;
        public final int pose;
        private Resolved(long composition,long lease,int pose,long movie) {
            this.composition=composition;this.lease=lease;this.pose=pose;this.movie=movie;
        }
    }

    /** One backing's binding, owned by its source/render thread, not a frame history. */
    public static final class Binding {
        private final Object owner,backing;
        private final int[] epoch;
        private final int width,height,slot;
        private long lease,serial;
        private Resolved resolved;
        private Binding(Snapshot snapshot,Object owner,Object backing,int slot,long lease) {
            this.owner=owner;this.backing=backing;this.epoch=snapshot.epoch.clone();
            this.width=snapshot.width;this.height=snapshot.height;this.slot=slot;
            this.lease=lease;this.serial=snapshot.serial(slot);
            this.resolved=new Resolved(serial,lease,snapshot.pose(slot),snapshot.movie(slot));
        }
        /** A new mapping publication must never relabel an already-held immutable image. */
        public Resolved resolve(Snapshot next,Object owner,Object backing,int width,int height,long lease) {
            if(this.owner!=owner||this.backing!=backing||this.width!=width||this.height!=height||lease<=0) return null;
            if(lease==this.lease) return resolved;
            if(lease<this.lease||next==null||next.width!=width||next.height!=height||
               !Arrays.equals(epoch,next.epoch)||slot>=next.count||next.serial(slot)<=serial) return null;
            this.lease=lease;serial=next.serial(slot);
            resolved=new Resolved(serial,lease,next.pose(slot),next.movie(slot));
            return resolved;
        }
    }

    /** Bootstrap only from completed GPU tags belonging to this actual acquired backing. */
    public static Binding bootstrap(Snapshot snapshot,int[] gpuEpoch,long gpuSerial,int gpuPose,
                                    Object owner,Object backing,int width,int height,long lease) {
        if(snapshot==null||gpuEpoch==null||gpuEpoch.length!=4||!Arrays.equals(snapshot.epoch,gpuEpoch)||
           gpuSerial<=0||gpuSerial>0xffffffffL||owner==null||backing==null||lease<=0||
           snapshot.width!=width||snapshot.height!=height) return null;
        for(int i=0;i<snapshot.count;i++)
            if(snapshot.serial(i)==gpuSerial&&snapshot.pose(i)==gpuPose)
                return new Binding(snapshot,owner,backing,i,lease);
        return null;
    }

    /** A completed private copy has no producer lease and cannot predict a backing's next use. */
    public static Resolved completedCopy(Snapshot snapshot,int[] gpuEpoch,long gpuSerial,int gpuPose,
                                         int width,int height) {
        if(snapshot==null||gpuEpoch==null||gpuEpoch.length!=4||!Arrays.equals(snapshot.epoch,gpuEpoch)||
           gpuSerial<=0||gpuSerial>0xffffffffL||snapshot.width!=width||snapshot.height!=height)return null;
        for(int i=0;i<snapshot.count;i++)
            if(snapshot.serial(i)==gpuSerial&&snapshot.pose(i)==gpuPose)
                return new Resolved(gpuSerial,0,gpuPose,snapshot.movie(i));
        return null;
    }
}
