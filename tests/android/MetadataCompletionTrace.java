package org.gk3hd.standalone;

import java.util.LinkedHashMap;
import java.util.ArrayList;

/** Join delayed metadata completion to selected immutable images, never poses alone. */
public final class MetadataCompletionTrace {
    public static final String[] COLUMNS={"snapshot","pose","composition","epoch0","epoch1","epoch2","epoch3",
        "capture_ns","first_poll_begin_ns","last_pending_begin_ns","ready_poll_begin_ns","ready_poll_end_ns",
        "metadata_verified_ns","window","pixmap","present_serial"};
    private final Thread owner=Thread.currentThread();
    private final LinkedHashMap<Long,long[]> pending=new LinkedHashMap<>(),recent=new LinkedHashMap<>();
    private final ArrayList<long[]> rows=new ArrayList<>();
    private final LinkedHashMap<Long,long[]> selected=new LinkedHashMap<>();
    private int issued,repeated;
    private void owned(){if(Thread.currentThread()!=owner)throw new IllegalStateException("Completion trace requires its GL owner");}
    /** A repainted immutable source is not a second fresh image or completion. */
    public boolean issue(long[] frame) {
        owned();
        if(frame==null||frame.length!=21||frame[0]<=0)
            throw new IllegalStateException("Invalid selected completion identity/bound: fields="+
                (frame==null ? -1 : frame.length)+" snapshot="+
                (frame==null||frame.length==0 ? -1 : frame[0])+" issued="+issued);
        long[] expected={frame[0],frame[1],frame[12],frame[13],frame[14],frame[15],frame[16],frame[18],frame[19],frame[20]};
        long[] previous=selected.get(frame[0]);
        if(previous!=null) {
            if(!java.util.Arrays.equals(previous,expected))
                throw new IllegalStateException("Repeated selection relabelled an immutable image");
            repeated++;return false;
        }
        if(issued>=4096)throw new IllegalStateException("Selected completion trace bound exceeded");
        if(pending.size()>=8)throw new IllegalStateException("Selected metadata completions did not retire");
        pending.put(frame[0],expected);selected.put(frame[0],expected);issued++;
        long[] completed=recent.remove(frame[0]);if(completed!=null)accept(completed);
        return true;
    }
    public void complete(long[] value) {
        owned();
        if(value==null||value.length!=16||value[0]<=0||value[7]<=0||value[8]<value[7]||
           value[10]<value[8]||value[11]<value[10]||value[12]<value[11]||
           value[9]!=0&&(value[9]<value[8]||value[9]>value[10]))
            throw new IllegalStateException("Invalid metadata completion time/identity");
        long[] row=value.clone();
        if(pending.containsKey(row[0]))accept(row);
        else {
            if(selected.containsKey(row[0]))throw new IllegalStateException("Selected completion reported twice");
            if(recent.put(row[0],row)!=null)throw new IllegalStateException("Duplicate metadata completion");
            if(recent.size()>32)recent.remove(recent.keySet().iterator().next());
        }
    }
    private void accept(long[] row) {
        long[] expected=pending.get(row[0]);
        for(int i=0;i<expected.length;i++)
            if(expected[i]!=row[i<7 ? i : i+6])throw new IllegalStateException("Metadata completion relabelled an image");
        pending.remove(row[0]);rows.add(row);
    }
    public int pending(){owned();return pending.size();}
    public int issued(){owned();return issued;}
    public int repeated(){owned();return repeated;}
    public int completed(){owned();return rows.size();}
    public long[][] rows(){owned();long[][] result=new long[rows.size()][];for(int i=0;i<result.length;i++)result[i]=rows.get(i).clone();return result;}
}
