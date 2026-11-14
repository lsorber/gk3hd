#include "frame_metadata_reader.h"
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>

static unsigned checks;
static void checked(int ok,int line){checks++;if(!ok){fprintf(stderr,"Shared map check failed:%u at line%d\n",checks,line);exit(1);}}
#define check(value) checked((value),__LINE__)
static uint32_t storage[256] __attribute__((aligned(16)));
static int running,started;
static void initialize(void){memset(storage,0,sizeof(storage));storage[0]=GPMAP_MAGIC;storage[1]=1;storage[2]=GPMAP_BYTES;storage[3]=GPMAP_PAYLOAD;}
static void publish(uint32_t seq){
    unsigned start=GPMAP_BANK+(seq&1u)*GPMAP_WORDS;
    for(unsigned i=0;i<GPMAP_WORDS;i++)__atomic_store_n(storage+start+i,seq^(i*0x45d9f3bu),__ATOMIC_RELAXED);
    // Match InterlockedExchange's acquire+release/full-publication semantics.
    // A release-only store does not order later bank reuse after publication.
    (void)__atomic_exchange_n(storage+4,seq,__ATOMIC_SEQ_CST);
}
static int consistent(const uint8_t bytes[GPMAP_PAYLOAD]){
    uint32_t seq=0,value=0;memcpy(&seq,bytes,4);
    for(unsigned i=0;i<GPMAP_WORDS;i++){memcpy(&value,bytes+i*4,4);if(value!=(seq^(i*0x45d9f3bu)))return 0;}
    return seq!=0;
}
static void* writer(void* ignored){
    (void)ignored;while(!__atomic_load_n(&started,__ATOMIC_ACQUIRE))sched_yield();
    for(uint32_t i=1;i<=100000;i++){publish(i);if(i%32==0)sched_yield();}
    __atomic_store_n(&running,0,__ATOMIC_RELEASE);return NULL;
}
int main(void){
    uint8_t output[GPMAP_PAYLOAD];initialize();
    check(!gpmap_copy(storage,sizeof(storage),output));publish(0x80000001u);
    check(gpmap_copy(storage,sizeof(storage),output)&&consistent(output));publish(UINT32_MAX);
    check(gpmap_copy(storage,sizeof(storage),output)&&consistent(output));
    check(!gpmap_copy(NULL,sizeof(storage),output));check(!gpmap_copy(storage,sizeof(storage),NULL));
    check(!gpmap_copy(storage,sizeof(storage)-1,output));check(!gpmap_copy((uint8_t*)storage+1,sizeof(storage),output));
    const unsigned indices[]={0,1,2,3,5,15,176,255};
    for(unsigned i=0;i<sizeof(indices)/sizeof(indices[0]);i++){
        unsigned index=indices[i];uint32_t saved=storage[index];storage[index]^=1;
        check(!gpmap_copy(storage,sizeof(storage),output));storage[index]=saved;
    }
    initialize();running=1;started=0;pthread_t thread;check(pthread_create(&thread,NULL,writer,NULL)==0);
    unsigned accepted=0,rejected=0;__atomic_store_n(&started,1,__ATOMIC_RELEASE);
    while(__atomic_load_n(&running,__ATOMIC_ACQUIRE)){
        if(gpmap_copy(storage,sizeof(storage),output)){check(consistent(output));accepted++;}else rejected++;
    }
    check(pthread_join(thread,NULL)==0);fprintf(stderr,"Concurrent coverage:accepted=%u rejected=%u\n",accepted,rejected);check(accepted>=100);
    check(gpmap_copy(storage,sizeof(storage),output)&&consistent(output));uint32_t final=0;memcpy(&final,output,4);check(final==100000);
    printf("Mapped reader:%u checks,100000 concurrent generations,%u accepted snapshots,%u bounded retries/rejections,zero torn packets\n",checks,accepted,rejected);
    return 0;
}
