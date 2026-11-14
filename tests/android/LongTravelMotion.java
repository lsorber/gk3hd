package org.gk3hd.standalone;

/** Test-only full-stick travel, followed by reverse travel and neutral recovery. */
public final class LongTravelMotion {
    public static float step(double seconds) {
        if(!Double.isFinite(seconds)||seconds<0)throw new IllegalArgumentException("Monotonic travel time required");
        double age=seconds%6;
        return age>=.5&&age<2.5?1:age>=3&&age<5?-1:0;
    }
}
