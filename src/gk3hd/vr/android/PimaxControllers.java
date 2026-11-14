package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Crystal's public firmware C API, isolated from the device-neutral XR protocol. */
public final class PimaxControllers implements AutoCloseable {
    static {System.loadLibrary("gk3hd_pimax");}
    private long handle;
    private final ByteBuffer bytes=ByteBuffer.allocateDirect(544).order(ByteOrder.LITTLE_ENDIAN);
    private static native long open(String runtimeVersion);
    private static native void poll(long handle,ByteBuffer output);
    private static native void close(long handle);
    private static native int headStatus(long handle);
    public PimaxControllers(String runtimeVersion) {handle=open(runtimeVersion);}
    public synchronized ByteBuffer sample() {
        if(handle==0) throw new IllegalStateException("Controller adapter closed");
        poll(handle,bytes);bytes.clear();return bytes.asReadOnlyBuffer().order(ByteOrder.LITTLE_ENDIAN);
    }
    /** Read-only C/Java firmware cross-check, never an input/tracking override. */
    public synchronized int nativeHeadStatus() {
        if(handle==0) throw new IllegalStateException("Controller adapter closed");
        return headStatus(handle);
    }
    @Override public synchronized void close() {if(handle!=0) {close(handle);handle=0;}}
}
