package org.gk3hd.standalone;

import com.winlator.xserver.Drawable;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Runs with Winlator's native CPU drawing methods on Android. */
public final class DrawableStorageTests {
    private static final short SIZE=4;

    private static void check(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }

    private static long usedHeap() {
        Runtime runtime=Runtime.getRuntime();
        return runtime.totalMemory()-runtime.freeMemory();
    }

    public static void run() {
        long before=usedHeap();
        Drawable window=new Drawable(1,5632,2884,null);
        Drawable pixmap=new Drawable(2,5632,2884,null);
        check(usedHeap()-before<32L*1024*1024,"Unused drawables eagerly allocated CPU pixels");

        ByteBuffer shared=ByteBuffer.allocateDirect(16);
        pixmap.setData(shared);
        check(pixmap.getData()==shared,"Shared-memory pixmap lost its supplied storage");
        window.setData(null);
        check(window.getData()==null,"GPU window acquired CPU storage");

        Drawable source=new Drawable(3,SIZE,SIZE,null);
        Drawable target=new Drawable(4,SIZE,SIZE,null);
        ByteBuffer initial=target.getData();
        check(initial.isDirect()&&initial.order()==ByteOrder.LITTLE_ENDIAN&&
            initial.capacity()==SIZE*SIZE*4&&initial.getInt(0)==0,"New CPU pixels are not zero-initialized BGRA storage");
        source.fillColor(0x123456);
        target.copyArea((short)0,(short)0,(short)0,(short)0,SIZE,SIZE,source);
        ByteBuffer read=target.getImage((short)0,(short)0,SIZE,SIZE);
        for(int offset=0;offset<read.capacity();offset+=4)
            check(read.getInt(offset)==0xFF123456,"CPU fill/copy/read changed the pixel at byte "+offset);
        check(target.getData()==initial,"CPU access replaced the original pixel buffer");
    }
}
