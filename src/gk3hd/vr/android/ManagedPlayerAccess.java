package com.winlator;

/** Single-process exclusion between the Android display and managed setup. */
public final class ManagedPlayerAccess {
    private static Lease owner;

    private ManagedPlayerAccess() {}

    static synchronized Lease tryPlay() {return acquire(false);}
    public static synchronized Lease tryInstall() {return acquire(true);}

    private static Lease acquire(boolean installing) {
        if(owner!=null)return null;
        owner=new Lease(installing);
        return owner;
    }

    static synchronized boolean installing() {return owner!=null&&owner.installing;}

    public static final class Lease implements AutoCloseable {
        private final boolean installing;

        private Lease(boolean installing) {this.installing=installing;}

        @Override public void close() {
            synchronized(ManagedPlayerAccess.class) {
                if(owner==this)owner=null;
            }
        }
    }
}
