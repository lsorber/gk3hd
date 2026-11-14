package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Pure ownership/identity behavior tests, with no headset or Android dependency. */
public final class ImageIdentityTests {
    private static int checks;
    private static void check(boolean value,String message) {
        checks++;if(!value) throw new AssertionError(message);
    }
    private static ByteBuffer packet(int[] epoch,int serial,int pose) {
        ByteBuffer out=ByteBuffer.allocate(ImageIdentity.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        out.put(new byte[]{'G','P','M','P','0','0','0','2'});
        out.putInt(2).putInt(ImageIdentity.BYTES).putInt(4120).putInt(2061).putInt(2).putInt(serial);
        for(int value:epoch) out.putInt(value);
        out.position(64);out.putInt(0).putInt(serial).putInt(pose).putInt(0);out.putInt(1);
        out.position(0);return out;
    }
    public static void main(String[] args) {
        int[] epoch={1,2,3,4};Object owner=new Object(),backing=new Object();
        ByteBuffer bytes=packet(epoch,1,Integer.MIN_VALUE);
        ImageIdentity.Snapshot first=ImageIdentity.decode(bytes);
        check(first!=null&&first.width==4120&&first.height==2061&&first.count==2,"Decode a complete image pool");
        check(first.pose(0)==Integer.MIN_VALUE&&first.latest==1,"Preserve full signed pose and unsigned serial");
        bytes.putInt(16,0);int[] exposed=first.epoch();exposed[0]=99;
        check(first.width==4120&&first.epoch()[0]==1,"Do not retain caller-owned mutable storage");
        ImageIdentity.Binding binding=ImageIdentity.bootstrap(first,epoch,1,Integer.MIN_VALUE,owner,backing,4120,2061,1);
        check(binding!=null,"Bootstrap the actual acquired backing from GPU evidence");
        check(ImageIdentity.bootstrap(first,epoch,1,0,owner,backing,4120,2061,1)==null,"Reject wrong GPU pose");
        check(ImageIdentity.bootstrap(first,new int[]{5,6,7,8},1,Integer.MIN_VALUE,owner,backing,4120,2061,1)==null,"Reject wrong pool epoch");
        check(ImageIdentity.bootstrap(first,epoch,0,Integer.MIN_VALUE,owner,backing,4120,2061,1)==null,"Reject unpublished composition");
        check(ImageIdentity.bootstrap(first,epoch,1,Integer.MIN_VALUE,null,backing,4120,2061,1)==null,"Require a real owner");
        check(ImageIdentity.bootstrap(first,epoch,1,Integer.MIN_VALUE,owner,backing,1024,768,1)==null,"Reject wrong image dimensions");
        ImageIdentity.Snapshot next=ImageIdentity.decode(packet(epoch,2,-1));
        ImageIdentity.Resolved held=binding.resolve(next,owner,backing,4120,2061,1);
        check(held.composition==1&&held.pose==Integer.MIN_VALUE,"New metadata cannot relabel held pixels");
        check(binding.resolve(next,new Object(),backing,4120,2061,2)==null,"Reject another owner");
        check(binding.resolve(next,owner,new Object(),4120,2061,2)==null,"Reject another backing");
        check(binding.resolve(next,owner,backing,4120,2061,0)==null,"Reject missing lease");
        ImageIdentity.Resolved advanced=binding.resolve(next,owner,backing,4120,2061,2);
        check(advanced.composition==2&&advanced.pose==-1&&held.composition==1,"Advancement preserves older resolved values");
        check(binding.resolve(next,owner,backing,4120,2061,3)==null,"A new lease requires a new backing composition");
        check(binding.resolve(first,owner,backing,4120,2061,1)==null,"Reject a stale lease");
        check(binding.resolve(ImageIdentity.decode(packet(new int[]{5,6,7,8},3,42)),owner,backing,4120,2061,3)==null,"Recreated pools must bootstrap again");
        for(int offset:new int[]{0,8,12,24,32,48,63,64+2*16}) {
            ByteBuffer bad=packet(epoch,3,42);bad.put(offset,(byte)(bad.get(offset)^0x80));
            if(offset==32) for(int i=32;i<48;i++) bad.put(i,(byte)0);
            check(ImageIdentity.decode(bad)==null,"Reject malformed packet at "+offset);
        }
        ByteBuffer duplicate=packet(epoch,3,42);duplicate.putInt(64+16+4,3).putInt(64+16+8,42);
        check(ImageIdentity.decode(duplicate)==null,"Composition serials identify one backing only");
        check(ImageIdentity.decode(ByteBuffer.allocate(319))==null&&ImageIdentity.decode(null)==null,"Reject incomplete input");
        ImageIdentity.Snapshot high=ImageIdentity.decode(packet(epoch,-1,-1));
        check(high.latest==0xffffffffL&&high.serial(0)==0xffffffffL,"Unsigned maximum is not a negative serial");
        for(int serial=3;serial<=100_002;serial++) {
            ImageIdentity.Snapshot current=ImageIdentity.decode(packet(epoch,serial,serial^Integer.MIN_VALUE));
            ImageIdentity.Resolved frame=binding.resolve(current,owner,backing,4120,2061,serial);
            check(frame!=null&&frame.composition==serial&&frame.pose==(serial^Integer.MIN_VALUE),"Long session identity remains bounded and current");
        }
        System.out.println(checks+" image-identity, ownership, malformed-input, recreation and long-session checks passed");
    }
}
