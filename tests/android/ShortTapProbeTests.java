package org.gk3hd.standalone;

public final class ShortTapProbeTests {
    private static void require(boolean value) {if(!value)throw new AssertionError("Invalid short-tap schedule");}
    public static void main(String[] args) {
        ShortTapProbe pulse=new ShortTapProbe();
        require(pulse.held(10));require(pulse.held(10_000_010));
        require(!pulse.held(20_000_010));require(!pulse.held(1_400_000_010L));
        require(pulse.started()==10&&pulse.released()==20_000_010&&pulse.lastDown()==10_000_010);
        require(pulse.downSamples()==2&&!pulse.fallback());
        require(pulse.held(1_500_000_010L)&&pulse.fallback());
        require(!pulse.held(1_850_000_010L));
        try {pulse.held(9);throw new AssertionError("Backward clock accepted");}
        catch(IllegalArgumentException expected) {}
        try {pulse.held(100_000_010);throw new AssertionError("Pulse resurrected after clock rewind");}
        catch(IllegalArgumentException expected) {}
        System.out.println("Short-tap probe: pulse, released gap, explicit recovery and clock checks passed");
    }
}
