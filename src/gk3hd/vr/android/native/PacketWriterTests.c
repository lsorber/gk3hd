#define _GNU_SOURCE
#include <unistd.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include "PacketWriter.h"

struct Shared {atomic_uint head,tail,status;unsigned char storage[4096];};
static struct Shared* shared;
static RingBuffer ring;
static unsigned checks;
static void reset(uint32_t size,uint32_t at) {
    atomic_store(&shared->head,at);atomic_store(&shared->tail,at);atomic_store(&shared->status,0);
    memset(shared->storage,0xa5,sizeof(shared->storage));ring.bufferSize=size;
}
static void roundtrip(uint32_t at,unsigned length) {
    reset(64,at);
    uint32_t header[2]={0x1234,length};unsigned char data[64],out[64];
    for(unsigned i=0;i<length;i++)data[i]=(unsigned char)(i*17+at);
    assert(gk3hdWritePacket(&ring,header,data,length));
    assert(RingBuffer_size(&ring)==GK3HD_PACKET_HEADER_SIZE+length);
    uint32_t got[2];assert(RingBuffer_read(&ring,got,sizeof(got)));
    assert(!memcmp(got,header,sizeof(got)));
    if(length)assert(RingBuffer_read(&ring,out,length)&&!memcmp(data,out,length));
    assert(RingBuffer_size(&ring)==0);++checks;
}
int main(void) {
    shared=mmap(NULL,sizeof(*shared),PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
    assert(shared!=MAP_FAILED);
    ring=(RingBuffer){.head=&shared->head,.tail=&shared->tail,.status=&shared->status,
                      .buffer=shared->storage,.bufferSize=64};
    for(unsigned at=0;at<64;at++)for(unsigned n=0;n<=56;n++)roundtrip(at,n);
    for(unsigned i=0;i<16;i++)roundtrip(UINT32_MAX-i,56-i);
    reset(64,0);uint32_t h[2]={1,57};unsigned char bytes[64]={0};
    assert(!gk3hdWritePacket(&ring,h,bytes,57)&&RingBuffer_size(&ring)==0);++checks;
    assert(!gk3hdWritePacket(&ring,h,NULL,1)&&RingBuffer_size(&ring)==0);++checks;
    reset(64,0);atomic_store(&shared->tail,64);atomic_store(&shared->status,RING_STATUS_EXIT);
    assert(!gk3hdWritePacket(&ring,h,bytes,1)&&RingBuffer_getTail(&ring)==64);++checks;
    /* Negative control: split publication exposes an incomplete request. */
    reset(64,0);h[1]=24;assert(RingBuffer_write(&ring,h,sizeof(h)));
    assert(RingBuffer_size(&ring)==GK3HD_PACKET_HEADER_SIZE&&
           RingBuffer_size(&ring)<GK3HD_PACKET_HEADER_SIZE+h[1]);++checks;
    reset(4096,UINT32_MAX-1023);
    pid_t producer=fork();assert(producer>=0);
    if(producer==0) {
        unsigned char payload[4000];
        for(uint32_t sequence=1;sequence<=30000;sequence++) {
            unsigned size=1+(sequence*37)%sizeof(payload);
            for(unsigned i=0;i<size;i++)payload[i]=(unsigned char)(sequence+i*13);
            uint32_t packet[2]={sequence,size};
            if(!gk3hdWritePacket(&ring,packet,payload,size))_exit(2);
        }
        _exit(0);
    }
    for(uint32_t sequence=1;sequence<=30000;sequence++) {
        uint32_t packet[2];unsigned char payload[4000];
        assert(RingBuffer_read(&ring,packet,sizeof(packet)));
        assert(packet[0]==sequence&&packet[1]>0&&packet[1]<=sizeof(payload));
        assert(RingBuffer_size(&ring)>=packet[1]);
        assert(RingBuffer_read(&ring,payload,packet[1]));
        for(unsigned i=0;i<packet[1];i++)assert(payload[i]==(unsigned char)(sequence+i*13));
        ++checks;
    }
    int status;assert(waitpid(producer,&status,0)==producer&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    assert(RingBuffer_size(&ring)==0);
    printf("%u packet wrap/bounds/exit/process-order checks passed; split negative control detected\n",checks);
    munmap(shared,sizeof(*shared));return 0;
}
