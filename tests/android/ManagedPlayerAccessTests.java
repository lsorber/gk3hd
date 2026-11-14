package com.winlator;

import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

public final class ManagedPlayerAccessTests {
    private static void check(boolean valid,String message) {
        if(!valid)throw new AssertionError(message);
    }

    public static void main(String[] args) throws Exception {
        ManagedPlayerAccess.Lease game=ManagedPlayerAccess.tryPlay();
        check(game!=null&&!ManagedPlayerAccess.installing(),"game must own idle player");
        check(ManagedPlayerAccess.tryInstall()==null,"install admitted during play");
        check(ManagedPlayerAccess.tryPlay()==null,"second display admitted");
        game.close();
        try(ManagedPlayerAccess.Lease setup=ManagedPlayerAccess.tryInstall()) {
            check(setup!=null&&ManagedPlayerAccess.installing(),"install must own idle player");
            game.close();
            check(ManagedPlayerAccess.tryPlay()==null,"retired display released current install");
            check(ManagedPlayerAccess.tryInstall()==null,"second install admitted");
        }
        check(!ManagedPlayerAccess.installing(),"install did not retire");

        ExecutorService pool=Executors.newFixedThreadPool(8);
        try {
            for(int round=0;round<32;round++) {
                CountDownLatch start=new CountDownLatch(1),attempted=new CountDownLatch(8),release=new CountDownLatch(1);
                ArrayList<Future<Boolean>> candidates=new ArrayList<>();
                for(int i=0;i<8;i++) {
                    boolean install=i%2==0;
                    candidates.add(pool.submit(()-> {
                        check(start.await(5,TimeUnit.SECONDS),"race start timed out");
                        try(ManagedPlayerAccess.Lease owner=install?ManagedPlayerAccess.tryInstall():ManagedPlayerAccess.tryPlay()) {
                            attempted.countDown();
                            check(release.await(5,TimeUnit.SECONDS),"race release timed out");
                            return owner!=null;
                        }
                    }));
                }
                start.countDown();
                try {check(attempted.await(5,TimeUnit.SECONDS),"race admission timed out");}
                finally {release.countDown();}
                int admitted=0;
                for(Future<Boolean> candidate:candidates)
                    if(candidate.get(5,TimeUnit.SECONDS))admitted++;
                check(admitted==1,"one request must win admission");
            }
        } finally {pool.shutdownNow();}
        try(ManagedPlayerAccess.Lease next=ManagedPlayerAccess.tryPlay()) {
            check(next!=null,"play must work after installer retirement");
        }
        System.out.println("Managed player admission and 32 concurrent races passed");
    }
}
