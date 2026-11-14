package org.gk3hd.standalone;

import static org.gk3hd.standalone.NativeDrawProgress.Phase.DRAW;
import static org.gk3hd.standalone.NativeDrawProgress.Phase.RESIZE;
import static org.gk3hd.standalone.NativeDrawProgress.Phase.SETUP;
import static org.gk3hd.standalone.NativeDrawProgress.Phase.SWAP;

public final class NativeDrawProgressTests {
    private static final long SECOND=1_000_000_000L;

    private static void require(boolean condition,String message) {
        if(!condition)throw new AssertionError(message);
    }

    public static void main(String[] args) {
        NativeDrawProgress progress=new NativeDrawProgress();
        progress.begin(DRAW,0);
        require(progress.inspect(30*SECOND)==null,"Inactive calls must not report");
        progress.active(true);
        progress.begin(DRAW,SECOND);
        require(progress.inspect(11*SECOND-1)==null,"In-flight call reported too early");
        require(progress.pending(11*SECOND-1)==null,"Pause must not turn a short draw into a stall");
        NativeDrawProgress.Stall draw=progress.inspect(11*SECOND);
        require(draw!=null&&draw.phase==DRAW&&draw.elapsedNs==10*SECOND,"Draw timeout lost its phase or duration");
        require(progress.inspect(12*SECOND)==null,"An unchanged call should report once");
        require(progress.stillPending(progress.pending(12*SECOND)),"Reporting hid a still-blocked call from pause");
        progress.begin(SWAP,13*SECOND);
        require(!progress.stillPending(draw),"A new call inherited an old stall");
        require(progress.inspect(22*SECOND)==null,"Swap inherited draw time");
        NativeDrawProgress.Stall swap=progress.inspect(24*SECOND);
        require(swap!=null&&swap.phase==SWAP&&swap.elapsedNs==11*SECOND,"Swap timeout lost its own identity");
        progress.finish();
        require(!progress.stillPending(swap),"A recovered call must not request recovery on pause");
        require(progress.inspect(40*SECOND)==null,"Completed call still reported");
        progress.begin(DRAW,41*SECOND);
        progress.active(false);
        progress.active(true);
        require(progress.inspect(80*SECOND)==null,"Resume revived the interrupted call");
        progress.begin(DRAW,81*SECOND);
        require(progress.inspect(91*SECOND)!=null,"New call did not arm after resume");
        progress.finish();
        progress.begin(SETUP,100*SECOND);
        NativeDrawProgress.Stall setup=progress.inspect(111*SECOND);
        require(setup!=null&&setup.phase==SETUP,"A blocked initial graphics setup must be visible");
        require(progress.stillPending(setup),"Pause must recognize the same blocked setup call");
        progress.finish();
        progress.begin(RESIZE,112*SECOND);
        require(!progress.stillPending(setup),"A completed setup must not trigger recovery during resize");
        NativeDrawProgress.Stall resize=progress.inspect(123*SECOND);
        require(resize!=null&&resize.phase==RESIZE,"A blocked surface resize must be visible");
        progress.begin(DRAW,124*SECOND);
        require(!progress.stillPending(resize),"A completed resize must not trigger recovery during draw");
        System.out.println("Native draw progress: setup, resize, draw, swap and rearming passed");
    }
}
