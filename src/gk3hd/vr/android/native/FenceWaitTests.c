#include "FenceWait.h"
#include <stdio.h>

typedef struct Fake {
    uint64_t now, start, first, second, maxSleep;
    unsigned queries, clocks, sleeps, failAt;
    int all, locked, violation, badClock;
    VkResult failure;
} Fake;
static uint64_t clockNow(void* opaque) {
    Fake* s=opaque;s->clocks++;return s->badClock ? UINT64_MAX : s->now;
}
static VkResult query(void* opaque) {
    Fake* s=opaque;s->queries++;s->locked=1;
    uint64_t elapsed=s->now-s->start;
    VkResult result=s->all ? (elapsed>=s->first&&elapsed>=s->second ? VK_SUCCESS : VK_TIMEOUT)
        : (elapsed>=s->first||elapsed>=s->second ? VK_SUCCESS : VK_TIMEOUT);
    if(s->failAt==s->queries)result=s->failure;
    s->locked=0;return result;
}
static void pauseNow(void* opaque,uint64_t duration) {
    Fake* s=opaque;s->sleeps++;if(s->locked||!duration||duration>200000)s->violation=1;
    if(duration>s->maxSleep)s->maxSleep=duration;
    s->now+=duration;
}
static VkResult run(Fake* state,uint64_t timeout) {
    return gk3hdWaitFences(state,timeout,query,clockNow,pauseNow);
}
static VKAPI_ATTR VkResult VKAPI_CALL fenceStatus(VkDevice device,VkFence fence) {
    (void)device;
    return (VkResult)((intptr_t)fence-8);
}
int main(void) {
    const VkFence mixed[]={(VkFence)(intptr_t)(8+VK_NOT_READY),(VkFence)(intptr_t)(8+VK_SUCCESS)};
    if(gk3hdFencePredicate(VK_NULL_HANDLE,2,mixed,VK_FALSE,fenceStatus)!=VK_SUCCESS||
       gk3hdFencePredicate(VK_NULL_HANDLE,2,mixed,VK_TRUE,fenceStatus)!=VK_TIMEOUT)return 10;
    if(gk3hdFencePredicate(VK_NULL_HANDLE,1,mixed,VK_FALSE,fenceStatus)!=VK_TIMEOUT||
       gk3hdFencePredicate(VK_NULL_HANDLE,1,mixed+1,VK_TRUE,fenceStatus)!=VK_SUCCESS)return 11;
    const VkFence error[]={(VkFence)(intptr_t)(8+VK_SUCCESS),(VkFence)(intptr_t)(8+VK_ERROR_DEVICE_LOST)};
    if(gk3hdFencePredicate(VK_NULL_HANDLE,2,error,VK_FALSE,fenceStatus)!=VK_ERROR_DEVICE_LOST)return 12;
    Fake ready={0};if(run(&ready,0)!=VK_SUCCESS||ready.queries!=1||ready.clocks||ready.sleeps)return 1;
    Fake pending={.first=UINT64_MAX,.second=UINT64_MAX};
    if(run(&pending,0)!=VK_TIMEOUT||pending.queries!=1||pending.clocks||pending.sleeps)return 2;
    Fake tiny={.first=100,.second=100};
    if(run(&tiny,1)!=VK_TIMEOUT||tiny.now!=1||tiny.maxSleep!=1||tiny.violation)return 3;
    Fake any={.first=1000000,.second=2000000};
    if(run(&any,1500000)!=VK_SUCCESS||any.now>=1500000||any.violation)return 4;
    Fake all={.first=1000000,.second=2000000,.all=1};
    if(run(&all,1500000)!=VK_TIMEOUT||all.now!=1500000||all.violation)return 5;
    Fake forever={.first=3000000,.second=5000000,.all=1};
    if(run(&forever,UINT64_MAX)!=VK_SUCCESS||forever.clocks||forever.queries>50||forever.violation)return 6;
    VkResult failures[]={VK_ERROR_DEVICE_LOST,VK_ERROR_OUT_OF_HOST_MEMORY,VK_ERROR_OUT_OF_DEVICE_MEMORY};
    for(unsigned i=0;i<sizeof(failures)/sizeof(failures[0]);i++) {
        Fake error={.first=UINT64_MAX,.second=UINT64_MAX,.failAt=3,.failure=failures[i]};
        if(run(&error,1000000)!=failures[i]||error.queries!=3||error.violation)return 7;
    }
    Fake wrap={.now=UINT64_MAX-2000,.start=UINT64_MAX-2000,.first=6000,.second=6000};
    if(run(&wrap,5000)!=VK_TIMEOUT||wrap.now-wrap.start!=5000||wrap.violation)return 8;
    Fake bad={.badClock=1};if(run(&bad,10)!=VK_ERROR_DEVICE_LOST||bad.queries)return 9;
    puts("Fence waits: zero/finite/infinite, all/any, errors, monotonic wrap and unlocked bounded backoff pass");
    return 0;
}
