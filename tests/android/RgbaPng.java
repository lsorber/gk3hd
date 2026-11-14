package org.gk3hd.standalone;

import java.io.DataOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.util.zip.CRC32;
import java.util.zip.Deflater;
import java.util.zip.DeflaterOutputStream;

/** Lossless diagnostic export without another image-sized Java allocation. */
public final class RgbaPng {
    private RgbaPng() { }

    public static void write(OutputStream output, ByteBuffer rgba, int width, int height) throws IOException {
        if(width<=0||height<=0)throw new IllegalArgumentException("Invalid PNG extent");
        int stride=Math.multiplyExact(width,4);
        if(Math.multiplyExact(stride,height)>rgba.limit())
            throw new IllegalArgumentException("Incomplete RGBA image");
        DataOutputStream out=new DataOutputStream(output);
        out.writeLong(0x89504e470d0a1a0aL);
        ByteBuffer header=ByteBuffer.allocate(13);
        header.putInt(width).putInt(height).put((byte)8).put((byte)6);
        chunk(out,0x49484452,header.array(),0,13); // IHDR, 8-bit straight RGBA.
        OutputStream chunks=new OutputStream() {
            @Override public void write(int value) throws IOException {
                write(new byte[]{(byte)value},0,1);
            }
            @Override public void write(byte[] data,int offset,int length) throws IOException {
                chunk(out,0x49444154,data,offset,length); // IDAT.
            }
        };
        Deflater deflater=new Deflater(Deflater.BEST_SPEED);
        try {
            DeflaterOutputStream compressed=new DeflaterOutputStream(chunks,deflater,32768);
            byte[] row=new byte[stride+1]; // PNG filter 0 followed by one unchanged RGBA row.
            ByteBuffer input=rgba.duplicate();
            for(int y=height-1;y>=0;y--) {
                input.position(y*stride);
                input.get(row,1,stride); // GL is bottom-up; PNG is top-down.
                compressed.write(row);
            }
            compressed.finish();
        } finally {deflater.end();}
        chunk(out,0x49454e44,new byte[0],0,0); // IEND.
        out.flush();
    }

    private static void chunk(DataOutputStream out,int type,byte[] data,int offset,int length) throws IOException {
        CRC32 crc=new CRC32();
        for(int shift=24;shift>=0;shift-=8)crc.update(type>>>shift&255);
        crc.update(data,offset,length);
        out.writeInt(length);out.writeInt(type);out.write(data,offset,length);out.writeInt((int)crc.getValue());
    }
}
