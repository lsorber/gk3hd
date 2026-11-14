package org.gk3hd.standalone;

import java.io.Closeable;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.Arrays;

/** Device-neutral tracking bridge to the separately built Windows OpenXR runtime.
 * WXR8 adds explicit location flags to WXR7's per-space record. No image pixels
 * travel through this socket. Unlocated controllers remain unlocated.
 */
public final class XrApiBridge implements Closeable {
    private static final class Reference {
        final int type;final float[] offset;
        Reference(int type,float[] offset) {this.type=type;this.offset=offset;}
    }
    private static final class Action {
        final int hand;final boolean grip;final float[] offset;
        Action(int hand,boolean grip,float[] offset) {this.hand=hand;this.grip=grip;this.offset=offset;}
    }
    private static final class Located {
        final float[] pose;final int flags;
        Located(float[] pose,int flags) {this.pose=pose;this.flags=flags;}
    }
    private final DatagramSocket socket;
    private final InetAddress loopback=InetAddress.getByName("127.0.0.1");
    private final Thread receiver;
    private final Map<Integer,Reference> references=new HashMap<>();
    private final Map<Integer,Action> actions=new HashMap<>();
    private final ArrayList<int[]> queries=new ArrayList<>();
    private volatile boolean closed;
    private volatile IOException failure;
    private int received;
    private boolean runtimeConnected;
    private final long sourceId=1+(new java.security.SecureRandom().nextLong()&0x3fffffffffffffffL);
    private long poseEpoch=1,inputGeneration=1,externalEpoch;
    private boolean focused,haveExternalEpoch;
    private byte[] lastPacket;
    // Android lifecycle callbacks must not perform socket IO on the UI thread.
    // Only focus withdrawals coalesce here; this is not a button-event queue.
    private final java.util.concurrent.ThreadPoolExecutor controlUpdates=
        new java.util.concurrent.ThreadPoolExecutor(0,1,1,java.util.concurrent.TimeUnit.SECONDS,
            new java.util.concurrent.ArrayBlockingQueue<Runnable>(1),task-> {
                Thread thread=new Thread(task,"GK3HDXrControl");thread.setDaemon(true);return thread;
            },new java.util.concurrent.ThreadPoolExecutor.DiscardOldestPolicy());

    public XrApiBridge() throws IOException {
        this(7278);
    }
    XrApiBridge(int port) throws IOException {
        socket=new DatagramSocket(port,loopback);socket.setSoTimeout(250);
        receiver=new Thread(this::receive,"GK3HDXrAPI");receiver.start();
    }
    private void receive() {
        byte[] bytes=new byte[16384];
        while(!closed) {
            try {
                DatagramPacket packet=new DatagramPacket(bytes,bytes.length);socket.receive(packet);
                if(!packet.getAddress().isLoopbackAddress()) continue;
                decode(new String(bytes,packet.getOffset(),packet.getLength(),StandardCharsets.US_ASCII));
            } catch(SocketTimeoutException timeout) { /* bounded shutdown polling */ }
            catch(IOException error) {if(!closed) failure=error;return;}
            catch(IllegalArgumentException malformed) { /* Ignore incomplete/malformed commands atomically. */ }
        }
    }
    synchronized void decode(String text) {
        String[] words=text.trim().split("\\s+");
        // GetState retries this hello while waiting for the first host pose.
        // It is a startup signal only, never evidence of valid tracking.
        if(words.length==4&&words[0].equals("0")&&words[1].equals("0")&&
                words[2].equals("2")&&words[3].equals("0")) {
            runtimeConnected=true;return;
        }
        if(words.length<7) return; // Startup hello, before the runtime registers spaces.
        int cursor=6;
        int count=count(words[cursor++]);
        if(cursor+count*9>=words.length) throw new IllegalArgumentException("Truncated reference definitions");
        Map<Integer,Reference> nextReferences=new HashMap<>();
        for(int i=0;i<count;i++) {
            int id=Integer.parseInt(words[cursor++]),type=Integer.parseInt(words[cursor++]);
            float[] offset=new float[7];
            for(int j=0;j<7;j++) offset[j]=finite(words[cursor++]);
            nextReferences.put(id,new Reference(type,offset));
        }
        count=count(words[cursor++]);
        if(cursor+count*10>=words.length) throw new IllegalArgumentException("Truncated action definitions");
        Map<Integer,Action> nextActions=new HashMap<>();
        for(int i=0;i<count;i++) {
            int id=Integer.parseInt(words[cursor++]),hand=Integer.parseInt(words[cursor++]),grip=Integer.parseInt(words[cursor++]);
            if(hand<1||hand>2||grip<0||grip>1) throw new IllegalArgumentException("Invalid action hand/type");
            float[] offset=new float[7];
            for(int j=0;j<7;j++) offset[j]=finite(words[cursor++]);
            nextActions.put(id,new Action(hand,grip!=0,offset));
        }
        count=count(words[cursor++]);
        ArrayList<int[]> nextQueries=new ArrayList<>();
        if(cursor+count*2>words.length) throw new IllegalArgumentException("Truncated space queries");
        for(int i=0;i<count;i++) nextQueries.add(new int[]{Integer.parseInt(words[cursor++]),Integer.parseInt(words[cursor++])});
        references.clear();references.putAll(nextReferences);actions.clear();actions.putAll(nextActions);
        queries.clear();queries.addAll(nextQueries);received++;runtimeConnected=true;
    }
    private static int count(String value) {
        int result=Integer.parseInt(value);if(result<0||result>128) throw new IllegalArgumentException("Too many spaces");return result;
    }
    private static float finite(String word) {
        float value=Float.parseFloat(word);if(!Float.isFinite(value)) throw new IllegalArgumentException("Non-finite pose");return value;
    }
    private Located global(int space,float[] head,int flags,XrInput inputs) {
        if(space==0) return new Located(head,flags);
        Action action=actions.get(space);
        if(action!=null) {
            XrInput.Hand hand=action.hand==1 ? inputs.left : inputs.right;
            return new Located(compose(action.grip?hand.gripPose():hand.pose(),action.offset),action.grip?hand.gripFlags:hand.flags);
        }
        Reference ref=references.get(space);
        if(ref==null) return null; // Controller or an unknown space.
        if(ref.type==1) return new Located(compose(head,ref.offset),flags); // VIEW
        if(ref.type==2||ref.type==3) return new Located(ref.offset,15); // LOCAL/STAGE origin still needs calibration.
        return null;
    }
    static float[] compose(float[] a,float[] b) {
        float ax=a[3],ay=a[4],az=a[5],aw=a[6],bx=b[3],by=b[4],bz=b[5],bw=b[6];
        float tx=2*(ay*b[2]-az*b[1]),ty=2*(az*b[0]-ax*b[2]),tz=2*(ax*b[1]-ay*b[0]);
        return new float[]{a[0]+b[0]+aw*tx+ay*tz-az*ty,a[1]+b[1]+aw*ty+az*tx-ax*tz,a[2]+b[2]+aw*tz+ax*ty-ay*tx,
            aw*bx+ax*bw+ay*bz-az*by,aw*by-ax*bz+ay*bw+az*bx,aw*bz+ax*by-ay*bx+az*bw,aw*bw-ax*bx-ay*by-az*bz};
    }
    static float[] inverse(float[] p) {
        float[] rotation={0,0,0,-p[3],-p[4],-p[5],p[6]};
        return compose(rotation,new float[]{-p[0],-p[1],-p[2],0,0,0,1});
    }
    synchronized byte[] encode(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame) {
        return encode(head,flags,ipd,fovX,fovY,hz,frame,XrInput.EMPTY);
    }
    synchronized byte[] encode(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs) {
        return encode(head,flags,ipd,fovX,fovY,hz,frame,inputs,null);
    }
    synchronized byte[] encode(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,StereoViews views) {
        if(head.length!=7 || (flags&~15)!=0 || !Float.isFinite(ipd) || ipd<=0 || ipd>.1f ||
            !Float.isFinite(fovX)||fovX<=0||fovX>=Math.PI || !Float.isFinite(fovY)||fovY<=0||fovY>=Math.PI ||
            !Float.isFinite(hz)||hz<30||hz>240) throw new IllegalArgumentException("Invalid tracking metadata");
        for(float value:head) if(!Float.isFinite(value)) throw new IllegalArgumentException("Invalid head pose");
        float norm=head[3]*head[3]+head[4]*head[4]+head[5]*head[5]+head[6]*head[6];
        if((flags&1)!=0 && Math.abs(norm-1)>.001f) throw new IllegalArgumentException("Invalid head orientation");
        ByteBuffer out=ByteBuffer.allocate(68+queries.size()*68+32+(views==null ? 0 : StereoViews.WIRE_BYTES)).order(ByteOrder.LITTLE_ENDIAN);
        out.put(new byte[]{'W','X','R',10});
        if(!focused)inputs=XrInput.EMPTY;
        XrInput.Hand left=inputs.left,right=inputs.right;
        out.putFloat(left.x).putFloat(left.y).putFloat(right.x).putFloat(right.y);
        out.putFloat(left.trigger).putFloat(left.grip).putFloat(right.trigger).putFloat(right.grip);
        out.putFloat(ipd).putFloat((float)Math.toDegrees(fovX)).putFloat((float)Math.toDegrees(fovY)).putFloat(hz);
        int buttons=wireButtons(left,new int[]{8,9,1,2,7,0})|wireButtons(right,new int[]{10,11,-1,13,18,12});
        out.putInt(frame).putInt(0).putInt(buttons).putInt(queries.size());
        for(int[] pair:queries) {
            Located a=global(pair[0],head,flags,inputs),b=global(pair[1],head,flags,inputs);
            int located=(a!=null&&b!=null&&(b.flags&1)!=0) ? a.flags&b.flags : 0;
            float[] pose=located!=0 ? compose(inverse(b.pose),a.pose) : new float[7];
            out.putInt(pair[0]).putInt(pair[1]).putInt(located);
            for(float value:pose) out.putFloat(value);
            for(int i=0;i<7;i++) out.putFloat(0); // Velocity unavailable, not guessed.
        }
        out.putInt(0x3146494c).putInt((focused?1:0)|(views==null?0:2));
        out.putLong(sourceId).putLong(poseEpoch).putLong(inputGeneration);
        if(views!=null)views.write(out);
        return out.array();
    }
    private static int wireButtons(XrInput.Hand hand,int[] positions) {
        int result=0;
        for(int i=0;i<positions.length;i++) if(positions[i]>=0&&(hand.buttons&(1<<i))!=0) result|=1<<positions[i];
        return result;
    }
    public void update(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs) throws IOException {
        update(head,flags,ipd,fovX,fovY,hz,frame,inputs,null);
    }
    public synchronized void update(float[] head,int flags,float ipd,float fovX,float fovY,float hz,int frame,XrInput inputs,StereoViews views) throws IOException {
        if(failure!=null) throw failure;
        if(closed) throw new IOException("XR bridge is closed");
        byte[] packet=encode(head,flags,ipd,fovX,fovY,hz,frame,inputs,views);
        socket.send(new DatagramPacket(packet,packet.length,loopback,7872));
        lastPacket=packet;
    }
    private static long advance(long value) {
        if(value==Long.MAX_VALUE)throw new IllegalStateException("Input lifetime exhausted");
        return value+1;
    }
    public synchronized void trackingEpoch(long epoch) {
        if(haveExternalEpoch&&externalEpoch!=epoch) {
            poseEpoch=advance(poseEpoch);inputGeneration=advance(inputGeneration);
        }
        externalEpoch=epoch;haveExternalEpoch=true;
    }
    public synchronized void focused(boolean value) {
        if(focused==value)return;
        focused=value;inputGeneration=advance(inputGeneration);
        if(value||lastPacket==null||closed)return;
        // Withdraw immediately even if the graphics thread is about to pause.
        // This is control metadata, never a freshly sampled tracking packet.
        byte[] packet=lastPacket.clone();ByteBuffer out=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
        int metadata=68+out.getInt(64)*68;
        Arrays.fill(packet,4,36,(byte)0);out.putInt(60,0);
        out.putInt(metadata+4,(out.getInt(metadata+4)&2)|4).putLong(metadata+24,inputGeneration);
        controlUpdates.execute(()-> {
            try {if(!closed)socket.send(new DatagramPacket(packet,packet.length,loopback,7872));}
            catch(IOException error){if(!closed)failure=error;}
        });
    }
    public synchronized int receivedCommands() {return received;}
    public synchronized boolean runtimeConnected() {return runtimeConnected;}
    @Override public void close() {
        synchronized(this) {closed=true;socket.close();controlUpdates.shutdownNow();}
        try {receiver.join(1000);} catch(InterruptedException error) {Thread.currentThread().interrupt();}
        try {controlUpdates.awaitTermination(1,java.util.concurrent.TimeUnit.SECONDS);}
        catch(InterruptedException error){Thread.currentThread().interrupt();}
    }
}
