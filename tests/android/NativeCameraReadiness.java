package org.gk3hd.standalone;

/** Test-only camera settlement before controller movement, not a game patch. */
public final class NativeCameraReadiness {
    private double[] candidate;
    private long since,firstFrame;
    public boolean ready(long now,long sceneFrame,double[] camera) {
        boolean valid=camera!=null&&camera.length==5&&sceneFrame>0;
        if(valid) for(double value:camera) valid&=Double.isFinite(value);
        if(valid) valid=Math.abs(camera[2])+Math.abs(camera[3])+Math.abs(camera[4])>.000001;
        if(!valid){candidate=null;return false;}
        boolean changed=candidate==null||sceneFrame<firstFrame;
        if(!changed)for(int i=0;i<5;i++)changed|=Math.abs(camera[i]-candidate[i])>.0001;
        if(changed){candidate=camera.clone();since=now;firstFrame=sceneFrame;return false;}
        return now-since>=200_000_000L&&sceneFrame-firstFrame>=2;
    }
}
