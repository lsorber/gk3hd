package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;

/** Read-only shared mapping. Every successful read returns a frozen 320-byte packet. */
public final class MappedFrameMetadata implements FrameIdentity.Source {
    static {System.loadLibrary("gk3hd_frame_metadata");}
    private static native byte[] copy(ByteBuffer mapped);
    private final File file;
    private MappedByteBuffer mapped;
    public MappedFrameMetadata(File file){this.file=file;}
    @Override public ImageIdentity.Snapshot read() {
        try {
            byte[] bytes=copyPacket();
            return bytes==null ? null : ImageIdentity.decode(ByteBuffer.wrap(bytes));
        } catch(IOException unavailable) {return null;}
    }
    private byte[] copyPacket() throws IOException {
        if(mapped==null){
            try(RandomAccessFile source=new RandomAccessFile(file,"r")){
                if(source.length()!=1024)throw new IOException("Unexpected shared snapshot extent");
                mapped=source.getChannel().map(FileChannel.MapMode.READ_ONLY,0,1024);
            }
        }
        return copy(mapped);
    }
}
