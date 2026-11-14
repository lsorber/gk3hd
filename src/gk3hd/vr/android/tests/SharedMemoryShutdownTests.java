package org.gk3hd.standalone;

import com.winlator.xenvironment.EnvironmentComponent;
import com.winlator.xenvironment.XEnvironment;
import com.winlator.xenvironment.components.SysVSharedMemoryComponent;

/** Run against the actual dependency classes, without opening a native socket. */
public final class SharedMemoryShutdownTests {
    private static final class FollowingComponent extends EnvironmentComponent {
        int stops;
        @Override public void start() { }
        @Override public void stop() { stops++; }
    }
    public static void main(String[] args) {
        // A surface can reject startup before environment components start.
        // Its later Activity destruction must still reach every other owner.
        XEnvironment environment=new XEnvironment(null,null);
        environment.addComponent(new SysVSharedMemoryComponent(null,null));
        FollowingComponent following=new FollowingComponent();
        environment.addComponent(following);
        environment.stopEnvironmentComponents();
        if(following.stops!=1)throw new AssertionError("Partial-start cleanup stopped early");
        environment.stopEnvironmentComponents();
        if(following.stops!=2)throw new AssertionError("Repeated cleanup stopped early");
        System.out.println("Shared-memory partial-start and repeated shutdown checks passed");
    }
}
