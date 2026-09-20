#define NOMINMAX
#include "private_locks.h"
#include <iostream>
#include <numeric>
#include <random>
#include <stdexcept>

void require(bool value) { if(!value) throw std::runtime_error("lock-region invariant"); }

int main() {
  try {
    std::mt19937 random(0x675533);
    const RECT full{0,0,64,64};
    unsigned completed=0;
    for(unsigned trial=0;trial<20000;++trial) {
      dxvk::SurfaceLockRegions tracker;
      struct Lock { RECT region; void* data; bool writable; };
      std::vector<Lock> locks;
      const unsigned count=1+random()%16;
      for(unsigned i=0;i<count;++i) {
        RECT region{LONG(i%4)*16,LONG(i/4)*16,LONG(i%4+1)*16,LONG(i/4+1)*16};
        const bool writable=random()%2;
        void* data=reinterpret_cast<void*>(uintptr_t(i+1)*1024);
        locks.push_back({region,data,writable});
        tracker.add(&region,full,data,writable?DDLOCK_WRITEONLY:DDLOCK_READONLY);
      }
      std::shuffle(locks.begin(),locks.end(),random);
      for(const auto& lock:locks) {
        const auto dirty=random()%2 ? tracker.byData(lock.data) : tracker.byRect(&lock.region);
        require(dirty.size()==unsigned(lock.writable));
        if(lock.writable) require(EqualRect(&dirty.front(),&lock.region));
        ++completed;
      }
      require(tracker.empty());
      require(tracker.byData(nullptr).empty());
    }
    dxvk::SurfaceLockRegions tracker;
    tracker.add(nullptr,full,reinterpret_cast<void*>(1),0);
    auto dirty=tracker.byData(nullptr);
    require(dirty.size()==1 && EqualRect(&dirty.front(),&full) && tracker.empty());
    const RECT a{0,0,16,16},b{16,0,32,16};
    tracker.add(&a,full,reinterpret_cast<void*>(1),DDLOCK_WRITEONLY);
    tracker.add(&b,full,reinterpret_cast<void*>(2),DDLOCK_READONLY);
    dirty=tracker.byData(reinterpret_cast<void*>(99));
    require(dirty.size()==1 && EqualRect(&dirty.front(),&a) && !tracker.empty());
    tracker.byRect(&b);
    require(tracker.empty());
    tracker.add(&a,full,reinterpret_cast<void*>(1),DDLOCK_WRITEONLY);
    tracker.clear();
    require(tracker.empty() && tracker.byRect(&a).empty());
    std::cout << "PASS: " << completed << " shuffled cross-interface unlocks in 20000 trials; full, ambiguous, empty and reset cases\n";
    return 0;
  } catch(const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
