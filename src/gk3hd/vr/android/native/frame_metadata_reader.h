#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define GPMAP_BYTES 1024u
#define GPMAP_PAYLOAD 320u
#define GPMAP_MAGIC 0x324d5047u
#define GPMAP_WORDS 80u
#define GPMAP_BANK 16u

_Static_assert(__atomic_always_lock_free(4,0),"Shared snapshots require lock-free aligned 32-bit loads");
_Static_assert(__BYTE_ORDER__==__ORDER_LITTLE_ENDIAN__,"Snapshot word serialization is little endian");
static inline uint32_t gpmap_load(const uint32_t* word){return __atomic_load_n(word,__ATOMIC_ACQUIRE);}

/* No wait, stale-cache reuse or unbounded retry. Return only an immutable copy. */
static inline int gpmap_copy(const void* source,size_t size,uint8_t output[GPMAP_PAYLOAD]){
    if(!source||!output||size!=GPMAP_BYTES||((uintptr_t)source&3u))return 0;
    const uint32_t* words=(const uint32_t*)source;
    if(gpmap_load(words)!=GPMAP_MAGIC||gpmap_load(words+1)!=1||
        gpmap_load(words+2)!=GPMAP_BYTES||gpmap_load(words+3)!=GPMAP_PAYLOAD)return 0;
    for(unsigned i=5;i<GPMAP_BANK;i++)if(gpmap_load(words+i))return 0;
    for(unsigned i=GPMAP_BANK+2*GPMAP_WORDS;i<GPMAP_BYTES/4;i++)if(gpmap_load(words+i))return 0;
    for(unsigned attempt=0;attempt<3;attempt++){
        uint32_t before=gpmap_load(words+4);if(!before)return 0;
        unsigned start=GPMAP_BANK+(before&1u)*GPMAP_WORDS;
        for(unsigned i=0;i<GPMAP_WORDS;i++){
            uint32_t value=__atomic_load_n(words+start+i,__ATOMIC_RELAXED);
            memcpy(output+i*4,&value,sizeof(value));
        }
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        if(gpmap_load(words+4)==before)return 1;
    }
    return 0;
}
