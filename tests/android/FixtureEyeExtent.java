package org.gk3hd.standalone;

/** Explicit bounded source dimensions for debug workloads, not an optical policy. */
public final class FixtureEyeExtent {
    public final int width,height;
    public FixtureEyeExtent(int width,int height) {
        // Bound this explicit diagnostic to the existing 4096-per-eye source
        // dimension contract. The runner separately checks available device
        // memory; this bound is not a normal-play quality recommendation.
        if(width<512||height<512||width>4096||height>4096)
            throw new IllegalArgumentException("Eye extent exceeds the bounded diagnostic workload");
        this.width=width;this.height=height;
    }
}
