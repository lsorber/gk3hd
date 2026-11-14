package org.gk3hd.standalone;

public final class RuntimeSelectionTests {
    private static void check(boolean value) {if(!value)throw new AssertionError("Runtime routing/permission mismatch");}
    private static void rejects(int support,boolean pimax) {
        try {XrRuntimeSelection.choose(support,pimax);throw new AssertionError("Unsupported runtime accepted");}
        catch(IllegalStateException|IllegalArgumentException expected) { }
    }
    public static void main(String[] args) {
        for(boolean vendor:new boolean[]{false,true}) {
            check(XrRuntimeSelection.choose(1,vendor)==XrRuntimeSelection.Backend.OPENXR);
            rejects(2,vendor);rejects(-1,vendor);rejects(3,vendor);
        }
        check(XrRuntimeSelection.choose(0,true)==XrRuntimeSelection.Backend.PIMAX);
        rejects(0,false);
        check(!XrRuntimeSelection.needsCamera(XrRuntimeSelection.Backend.OPENXR));
        check(XrRuntimeSelection.needsCamera(XrRuntimeSelection.Backend.PIMAX));
        check("2688x2752".equals(XrRuntimeSelection.headsetEyeResolution(XrRuntimeSelection.Backend.PIMAX,"Pimax_Crystal")));
        check("3008x3264".equals(XrRuntimeSelection.headsetEyeResolution(XrRuntimeSelection.Backend.OPENXR,"Quest 3")));
        check(XrRuntimeSelection.headsetEyeResolution(XrRuntimeSelection.Backend.OPENXR,"Pimax_Crystal")==null);
        check(XrRuntimeSelection.headsetEyeResolution(XrRuntimeSelection.Backend.OPENXR,"Quest 3S")==null);
        System.out.println("Runtime capabilities select OpenXR/vendor fallback and only vendor tracking requests camera");
    }
}
