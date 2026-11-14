package org.gk3hd.standalone;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Actual host datagrams; no headset, input injection or generated tracking claim. */
public final class InputLifetimeTests {
    private static int checks;
    private static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
    private static ByteBuffer receive(DatagramSocket socket) throws Exception {
        byte[] bytes=new byte[4096];DatagramPacket packet=new DatagramPacket(bytes,bytes.length);socket.receive(packet);
        return ByteBuffer.wrap(java.util.Arrays.copyOf(bytes,packet.getLength())).order(ByteOrder.LITTLE_ENDIAN);
    }
    private static int metadata(ByteBuffer packet) {return 68+68*packet.getInt(64);}
    public static void main(String[] args) throws Exception {
        Path output=Paths.get(args[0]);Files.createDirectories(output);
        try(DatagramSocket receiver=new DatagramSocket(7872,InetAddress.getByName("127.0.0.1"));
            XrApiBridge bridge=new XrApiBridge(0)) {
            receiver.setSoTimeout(1000);
            bridge.decode("0 0 1 1 90 90 1 101 2 0 0 0 0 0 0 1 0 1 0 101");
            bridge.trackingEpoch(7);bridge.focused(true);
            XrInput.Hand hand=new XrInput.Hand(new float[]{0,0,0,0,0,0,1},15,XrInput.PRIMARY|XrInput.TRIGGER,.5f,.6f,1,0);
            XrInput inputs=new XrInput(XrInput.UNLOCATED,hand);
            bridge.update(new float[]{1,2,3,0,0,0,1},15,.064f,1.5f,1.5f,90,100,inputs);
            ByteBuffer first=receive(receiver);int at=metadata(first);
            check(first.get(3)==10&&first.getInt(at)==0x3146494c,"Missing lifetime header");
            check(first.getInt(at+4)==1&&first.getLong(at+8)>0,"Source focus/identity missing");
            check(first.getInt(60)!=0&&first.getFloat(28)==1,"Focused controls were discarded");
            long epoch=first.getLong(at+16),generation=first.getLong(at+24);
            Files.write(output.resolve("focused.bin"),first.array());
            bridge.focused(false);ByteBuffer withdrawn=receive(receiver);
            check(withdrawn.getInt(52)==100,"Pause invented a freshly sampled pose ID");
            check(withdrawn.getInt(at+4)==4&&withdrawn.getLong(at+24)>generation,"Focus withdrawal has no new input generation");
            check(withdrawn.getLong(at+8)==first.getLong(at+8)&&withdrawn.getLong(at+16)==epoch,"Focus recentered or restarted the source");
            check(withdrawn.getInt(60)==0&&withdrawn.getFloat(28)==0,"Pause retained controller state");
            check(withdrawn.getFloat(80)==1&&withdrawn.getFloat(36)==first.getFloat(36),"Pause changed cached pose/optics");
            Files.write(output.resolve("withdrawal.bin"),withdrawn.array());
            bridge.focused(true);receiver.setSoTimeout(40);
            try {receive(receiver);throw new AssertionError("Resume replayed an old pose");}
            catch(SocketTimeoutException expected) {checks++;}
            bridge.trackingEpoch(8);receiver.setSoTimeout(1000);
            bridge.update(new float[]{9,2,3,0,0,0,1},15,.064f,1.5f,1.5f,90,3,inputs);
            ByteBuffer reset=receive(receiver);
            check(reset.getLong(at+16)>epoch&&reset.getLong(at+24)>withdrawn.getLong(at+24),"New tracking epoch was not explicit");
            check(reset.getInt(56)==0,"Input lifetime changed reference recenter identity");
            Files.write(output.resolve("new-epoch.bin"),reset.array());
            bridge.focused(false);receive(receiver);
            bridge.update(new float[]{10,2,3,0,0,0,1},15,.064f,1.5f,1.5f,90,4,inputs);
            ByteBuffer inactive=receive(receiver);
            check(inactive.getInt(at+4)==0&&inactive.getInt(60)==0,"Unfocused ordinary packet retained actions");
            Files.write(output.resolve("unfocused.bin"),inactive.array());
        }
        System.out.println("Input lifetime host checks: "+checks);
    }
}
