package org.gk3hd.standalone;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.regex.Pattern;

/** Debug observation only: a visible save row is not a finalized native save. */
final class NativeSaveFile {
    private static final byte[] MAGIC={'G','K','3','!','S','a','v','e'};
    private static final Pattern SAVE_NAME=Pattern.compile("save[0-9]{4}\\.gk3",Pattern.CASE_INSENSITIVE);
    private NativeSaveFile() { }

    static File[] entries(File directory) {
        return directory.listFiles((parent,name)->SAVE_NAME.matcher(name).matches());
    }

    static String[] catalog(File file) throws IOException {
        if(!finalized(file))throw new IOException("Unfinished native save fixture");
        String[] fields=new String[3];
        try(RandomAccessFile input=new RandomAccessFile(file,"r")) {
            input.seek(0xf8);
            for(int i=0;i<fields.length;i++) {
                long length=Integer.toUnsignedLong(Integer.reverseBytes(input.readInt()));
                if(length>1024)throw new IOException("Unbounded save catalog field");
                byte[] data=new byte[(int)length];input.readFully(data);
                if(input.read()!=0)throw new IOException("Invalid save catalog terminator");
                for(byte value:data)if(value<32||value>126)throw new IOException("Invalid save catalog text");
                fields[i]=new String(data,StandardCharsets.US_ASCII);
            }
        }
        if(fields[0].isEmpty()||!fields[1].matches("[A-Za-z0-9]{3}")||!fields[2].matches("[123][0-9]{2}[ap]"))
            throw new IOException("Invalid save catalog identity");
        return fields;
    }

    static boolean finalized(File file) throws IOException {
        if(!file.isFile()) return false;
        try(RandomAccessFile input=new RandomAccessFile(file,"r")) {
            long size=input.length();
            if(size<0x100||size>8L*1024*1024) return false;
            byte[] magic=new byte[8];input.readFully(magic);
            if(!Arrays.equals(magic,MAGIC)) return false;
            // GK3 fills this little-endian total length during finalization.
            // A rebooted partial save can have its full allocated file length,
            // a readable catalogue and camera, but zero here and zero tail data.
            input.seek(0x33);
            long declared=Integer.toUnsignedLong(Integer.reverseBytes(input.readInt()));
            return declared==size&&input.length()==size;
        }
    }
}
