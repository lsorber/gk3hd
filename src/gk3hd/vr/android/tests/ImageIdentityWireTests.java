package org.gk3hd.standalone;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
public final class ImageIdentityWireTests {
    private static int checks;
    private static void expect(boolean value){checks++;if(!value)throw new AssertionError("protocol check "+checks);}
    private static byte[] encode(ImageIdentity.Snapshot s) {
        ByteBuffer b=ByteBuffer.allocate(ImageIdentity.BYTES).order(ByteOrder.LITTLE_ENDIAN);
        b.put(new byte[]{'G','P','M','P','0','0','0','2'});b.putInt(2).putInt(ImageIdentity.BYTES);
        b.putInt(s.width).putInt(s.height).putInt(s.count).putInt((int)s.latest);
        for(int word:s.epoch())b.putInt(word);
        b.position(64);
        for(int i=0;i<s.count;i++)b.putInt(i).putInt((int)s.serial(i)).putInt(s.pose(i)).putInt((int)s.movie(i));
        return b.array();
    }
    public static void main(String[] args)throws Exception {
        byte[] all=Files.readAllBytes(Paths.get(args[0]));expect(all.length==257*ImageIdentity.BYTES);
        ImageIdentity.Snapshot[] samples=new ImageIdentity.Snapshot[257];
        for(int n=0;n<samples.length;n++) {
            byte[] bytes=Arrays.copyOfRange(all,n*ImageIdentity.BYTES,(n+1)*ImageIdentity.BYTES);
            samples[n]=ImageIdentity.decode(ByteBuffer.wrap(bytes));expect(samples[n]!=null);
            expect(samples[n].latest==(n==256?0xffffffffL:n+1));
            expect(samples[n].width==4120&&samples[n].height==2061&&samples[n].count==6);
            expect(Arrays.equals(encode(samples[n]),bytes));
            for(int offset:new int[]{0,8,12,24,48,63,64+6*16}) {
                byte[] bad=bytes.clone();bad[offset]^=(byte)0x80;
                expect(ImageIdentity.decode(ByteBuffer.wrap(bad))==null);
            }
            expect(ImageIdentity.decode(ByteBuffer.wrap(Arrays.copyOf(bytes,bytes.length-1)))==null);
            // Parsing does not retain caller-owned buffers or mutable epoch arrays.
            bytes[16]=0;int[] epoch=samples[n].epoch();epoch[0]=0;
            expect(samples[n].width==4120&&samples[n].epoch()[0]==0x11223344);
        }
        expect(samples[0].pose(0)==Integer.MIN_VALUE);expect(samples[1].pose(1)==-1);
        Object owner=new String("owner"),backing=new String("backing");
        ImageIdentity.Snapshot start=samples[5],next=samples[11],future=samples[17];
        int[] epoch=start.epoch();int pose=start.pose(0);long serial=start.serial(0);
        ImageIdentity.Binding binding=ImageIdentity.bootstrap(start,epoch,serial,pose,owner,backing,4120,2061,100);
        expect(binding!=null);
        expect(ImageIdentity.bootstrap(start,epoch,serial,pose^1,owner,backing,4120,2061,100)==null);
        int[] wrong=epoch.clone();wrong[0]++;
        expect(ImageIdentity.bootstrap(start,wrong,serial,pose,owner,backing,4120,2061,100)==null);
        expect(ImageIdentity.bootstrap(start,epoch,0,pose,owner,backing,4120,2061,100)==null);
        expect(ImageIdentity.bootstrap(start,epoch,serial,pose,owner,backing,4121,2061,100)==null);
        // A newer metadata file must never relabel an already-held image.
        ImageIdentity.Resolved initial=binding.resolve(next,owner,backing,4120,2061,100);
        expect(initial!=null&&initial.pose==pose&&initial.composition==serial&&initial.lease==100&&initial.movie==start.movie(0));
        expect(binding.resolve(next,new String("owner"),backing,4120,2061,101)==null);
        expect(binding.resolve(next,owner,new String("backing"),4120,2061,101)==null);
        expect(binding.resolve(next,owner,backing,4120,2061,99)==null);
        expect(binding.resolve(start,owner,backing,4120,2061,101)==null);
        expect(binding.resolve(null,owner,backing,4120,2061,101)==null);
        ImageIdentity.Resolved accepted=binding.resolve(next,owner,backing,4120,2061,101);
        expect(accepted!=null&&accepted.pose==next.pose(0)&&accepted.composition==next.serial(0)&&accepted.movie==next.movie(0));
        expect(binding.resolve(future,owner,backing,4120,2061,101)==accepted);
        byte[] changedEpoch=encode(future);changedEpoch[32]^=1;
        ImageIdentity.Snapshot recreated=ImageIdentity.decode(ByteBuffer.wrap(changedEpoch));expect(recreated!=null);
        expect(binding.resolve(recreated,owner,backing,4120,2061,102)==null);
        expect(binding.resolve(future,owner,backing,4120,2061,102).pose==future.pose(0));
        // Same pose in different images is legal, but the GPU composition tag
        // must select the exact image rather than whichever pose matches first.
        byte[] repeated=encode(next);
        ByteBuffer repeat=ByteBuffer.wrap(repeated).order(ByteOrder.LITTLE_ENDIAN);
        repeat.putInt(64+16+8,next.pose(0));
        ImageIdentity.Snapshot samePose=ImageIdentity.decode(repeat);expect(samePose!=null);
        ImageIdentity.Binding second=ImageIdentity.bootstrap(samePose,epoch,samePose.serial(1),samePose.pose(1),owner,backing,4120,2061,200);
        expect(second!=null);
        expect(second.resolve(samePose,owner,backing,4120,2061,200).composition==samePose.serial(1));
        System.out.println(checks+" Java wire/binding/held-image/epoch/reuse checks passed");
    }
}
