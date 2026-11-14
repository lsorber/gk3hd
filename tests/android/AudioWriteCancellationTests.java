package org.gk3hd.standalone;

import com.winlator.alsaserver.ALSAClient;
import java.nio.ByteBuffer;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Own silent track only: pausing must let a pending write return, not spin. */
final class AudioWriteCancellationTests {
    static void run() throws Exception {
        ALSAClient.Options options=new ALSAClient.Options();options.volume=0;
        ALSAClient client=new ALSAClient(options);
        client.setChannels((byte)2);client.setDataType(ALSAClient.DataType.FLOATLE);
        client.setSampleRate(48000);client.setBufferSize(4096);client.prepare();
        CountDownLatch entered=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread writer=new Thread(()-> {
            entered.countDown();
            try {client.writeDataToTrack(ByteBuffer.allocateDirect(1024*1024));}
            catch(Throwable error){failure.set(error);}
        },"GK3HDSilentAudioWriter");
        writer.setDaemon(true);
        try {
            writer.start();
            if(!entered.await(1,TimeUnit.SECONDS))throw new AssertionError("Audio writer did not start");
            Thread.sleep(100);
            if(!writer.isAlive())throw new AssertionError("Fixture did not retain a pending audio write");
            client.pause();writer.join(1000);
            if(writer.isAlive())throw new AssertionError("Paused audio write did not return before retirement");
            if(failure.get()!=null)throw new AssertionError("Audio writer failed",failure.get());
        } finally {
            client.pause();writer.join(1000);
            // Never release storage beneath an unfinished native write. The
            // host retires this bounded test app after retaining its failure.
            if(!writer.isAlive())client.release();
        }
    }
}
