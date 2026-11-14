package org.gk3hd.standalone;

/** Device-neutral, immutable controller samples in OpenXR meters/right-handed axes. */
public final class XrInput {
    public static final int PRIMARY=1,SECONDARY=2,MENU=4,STICK=8,TRIGGER=16,GRIP=32;
    public static final class Hand {
        public final int flags,gripFlags,buttons;
        private final float[] pose,gripPose;
        public final float x,y,trigger,grip;
        /** Firmware with one physical controller pose uses that pose for both
         * spaces. A two-pose runtime must supply each pose and its own flags.
         */
        public Hand(float[] pose,int flags,int buttons,float x,float y,float trigger,float grip) {
            this(pose,flags,pose,flags,buttons,x,y,trigger,grip);
        }
        public Hand(float[] aim,int aimFlags,float[] held,int heldFlags,int buttons,float x,float y,float trigger,float grip) {
            if((buttons&~63)!=0) throw new IllegalArgumentException("Invalid controller buttons");
            this.pose=checkedPose(aim,aimFlags);this.gripPose=checkedPose(held,heldFlags);
            if(!Float.isFinite(x)||!Float.isFinite(y)||!Float.isFinite(trigger)||!Float.isFinite(grip)||
                Math.abs(x)>1||Math.abs(y)>1||trigger<0||trigger>1||grip<0||grip>1)
                throw new IllegalArgumentException("Invalid controller axes");
            this.flags=aimFlags;this.gripFlags=heldFlags;
            // A pointing ray needs valid orientation AND position. These are
            // distinct from the runtime's actively-tracked status bits.
            boolean located=(aimFlags&3)==3;
            this.buttons=located ? buttons : 0;this.x=located ? x : 0;this.y=located ? y : 0;
            this.trigger=located ? trigger : 0;this.grip=located ? grip : 0;
        }
        private static float[] checkedPose(float[] value,int flags) {
            if(value==null||value.length!=7||(flags&~15)!=0)throw new IllegalArgumentException("Invalid controller metadata");
            for(float part:value)if(!Float.isFinite(part))throw new IllegalArgumentException("Non-finite controller pose");
            float norm=value[3]*value[3]+value[4]*value[4]+value[5]*value[5]+value[6]*value[6];
            if((flags&1)!=0&&Math.abs(norm-1)>.01f)throw new IllegalArgumentException("Invalid controller orientation");
            return value.clone();
        }
        public float[] pose() {return pose.clone();}
        public float[] gripPose() {return gripPose.clone();}
    }
    public static final Hand UNLOCATED=new Hand(new float[7],0,0,0,0,0,0);
    public static final XrInput EMPTY=new XrInput(UNLOCATED,UNLOCATED);
    public final Hand left,right;
    public XrInput(Hand left,Hand right) {
        if(left==null||right==null) throw new IllegalArgumentException("Missing hand sample");
        this.left=left;this.right=right;
    }
}
