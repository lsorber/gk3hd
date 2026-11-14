package org.gk3hd.standalone;

/** Host-runnable admission checks before allocating diagnostic GPU images. */
public final class FixtureEyeExtentTests {
    private FixtureEyeExtentTests() { }
    private static void rejects(int width,int height) {
        try {new FixtureEyeExtent(width,height);}
        catch(IllegalArgumentException expected) {return;}
        throw new AssertionError("Unbounded diagnostic extent was accepted");
    }
    public static void main(String[] args) {
        for(int[] size:new int[][]{{2060,2060},{2580,2760},{3312,3312}}) {
            FixtureEyeExtent extent=new FixtureEyeExtent(size[0],size[1]);
            if(extent.width!=size[0]||extent.height!=size[1])
                throw new AssertionError("Source dimensions were squared or transposed");
        }
        rejects(0,2760);rejects(2580,0);rejects(-1,2060);
        rejects(Integer.MAX_VALUE,2060);rejects(2060,Integer.MAX_VALUE);
        rejects(8192,8192);
        System.out.println("Nine diagnostic extent checks passed");
    }
}
