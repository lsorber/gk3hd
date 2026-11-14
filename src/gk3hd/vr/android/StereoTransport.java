package org.gk3hd.standalone;

/** Physical standalone image height, preserving visible eyes and last-row metadata. */
public final class StereoTransport {
    private StereoTransport() {}
    public static int height(int visibleHeight) {
        if(visibleHeight<1||visibleHeight>Integer.MAX_VALUE-4)
            throw new IllegalArgumentException("Standalone eye height overflows its transport");
        return (visibleHeight+4)&~3;
    }
}
