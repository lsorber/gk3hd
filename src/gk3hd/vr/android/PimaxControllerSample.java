package org.gk3hd.standalone;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Pure firmware-record decoder, shared by the adapter and off-device tests. */
public final class PimaxControllerSample {
    private PimaxControllerSample() {}
    public static XrInput decode(ByteBuffer bytes,long elapsedRealtimeNanos) {
        if(bytes.remaining()!=544) throw new IllegalArgumentException("Invalid controller record size");
        ByteBuffer data=bytes.slice().order(ByteOrder.LITTLE_ENDIAN);
        return new XrInput(hand(data,0,elapsedRealtimeNanos),hand(data,272,elapsedRealtimeNanos));
    }
    private static XrInput.Hand hand(ByteBuffer data,int base,long now) {
        int status=data.getInt(base+236);
        long age=now-data.getLong(base+240);
        // Firmware prediction status 2 is emitted only for a connected,
        // position-valid controller. It is not the head pose's bitmask.
        if(data.getInt(base+136)!=2||data.get(base+140)==0||status!=2||age<0||age>250_000_000L)
            return XrInput.UNLOCATED;
        float[] pose=new float[7];
        for(int i=0;i<3;i++) pose[i]=data.getFloat(base+224+i*4);
        for(int i=0;i<4;i++) pose[i+3]=data.getFloat(base+208+i*4);
        // Unlike native HMD poses, these predicted controller poses already
        // use OpenXR's right-handed basis. Match the firmware Unity provider's
        // controller conversion, followed by Unity -> OpenXR conversion.
        int raw=data.getInt(base+64),buttons=0;
        if((raw&1)!=0) buttons|=XrInput.PRIMARY;
        if((raw&2)!=0) buttons|=XrInput.SECONDARY;
        if((raw&(1<<15))!=0) buttons|=XrInput.MENU;
        if((raw&0x300)!=0) buttons|=XrInput.STICK;
        float trigger=clamp(data.getFloat(base+100)/255,0,1),grip=clamp(data.getFloat(base+108)/255,0,1);
        if(trigger>.7f) buttons|=XrInput.TRIGGER;
        if(grip>.7f) buttons|=XrInput.GRIP;
        try {
            return new XrInput.Hand(pose,15,buttons,clamp((data.getFloat(base+68)-128)/128,-1,1),
                clamp((data.getFloat(base+72)-128)/128,-1,1),trigger,grip);
        } catch(IllegalArgumentException invalid) {return XrInput.UNLOCATED;}
    }
    private static float clamp(float value,float lo,float hi) {return Math.max(lo,Math.min(value,hi));}
}
