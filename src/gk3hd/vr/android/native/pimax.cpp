#include <jni.h>
#include <dlfcn.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>

namespace {
// Verified against the installed 4.0.5.3 firmware, not the older/smaller Unity
// SDK state declaration. Both functions return aggregate structs via ARM64 x8.
struct alignas(8) ControllerState {std::array<uint8_t,208> bytes;};
struct alignas(8) PredictedPose {std::array<uint8_t,56> bytes;};
static_assert(sizeof(ControllerState)==208&&sizeof(PredictedPose)==56);
struct Bridge {
    void* library=nullptr;
    int (*start)(const char*)=nullptr;
    void (*stop)(int)=nullptr;
    ControllerState (*state)(int,int)=nullptr;
    PredictedPose (*pose)(int,float)=nullptr;
    PredictedPose (*head)(float)=nullptr;
    int hands[2]={-1,-1};
    ~Bridge() {
        for(int hand:hands) if(hand>=0&&stop) stop(hand);
        if(library) dlclose(library);
    }
    template<class T> void load(T& function,const char* name) {
        function=reinterpret_cast<T>(dlsym(library,name));
        if(!function) throw std::runtime_error(name);
    }
};
void fail(JNIEnv* env,const char* message) {env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),message);}
}

extern "C" JNIEXPORT jlong JNICALL
Java_org_gk3hd_standalone_PimaxControllers_open(JNIEnv* env,jclass,jstring version) {
    const char* text=env->GetStringUTFChars(version,nullptr);
    bool compatible=std::strcmp(text,"4.0.5.3, Jan 18 2024 - 17:37:55")==0;
    env->ReleaseStringUTFChars(version,text);
    if(!compatible) {fail(env,"Controller ABI has not been qualified for this Pimax runtime version");return 0;}
    try {
        auto bridge=std::make_unique<Bridge>();
        // The firmware explicitly publishes this library in public.libraries-pi.txt.
        // No bundled vendor binary, private linker bypass or root access.
        bridge->library=dlopen("libpxrcore.pi.so",RTLD_NOW|RTLD_LOCAL);
        if(!bridge->library) throw std::runtime_error(dlerror());
        bridge->load(bridge->start,"sxrControllerStartTracking");bridge->load(bridge->stop,"sxrControllerStopTracking");
        bridge->load(bridge->state,"sxrControllerGetState");bridge->load(bridge->pose,"sxrGetPredictedControllerPose");
        bridge->load(bridge->head,"sxrGetPredictedHeadPose");
        const char* descriptors[]={"left","right"}; // Firmware Unity input provider uses these exact descriptors.
        for(int i=0;i<2;i++) {
            bridge->hands[i]=bridge->start(descriptors[i]);
            if(bridge->hands[i]<0||bridge->hands[i]>7) throw std::runtime_error("Controller registration failed");
        }
        return reinterpret_cast<jlong>(bridge.release());
    } catch(const std::exception& error) {fail(env,error.what());return 0;}
}

extern "C" JNIEXPORT void JNICALL
Java_org_gk3hd_standalone_PimaxControllers_poll(JNIEnv* env,jclass,jlong handle,jobject buffer) {
    auto* bridge=reinterpret_cast<Bridge*>(handle);
    auto* bytes=static_cast<uint8_t*>(env->GetDirectBufferAddress(buffer));
    if(!bridge||!bytes||env->GetDirectBufferCapacity(buffer)!=544) {fail(env,"Invalid controller sample buffer");return;}
    std::memset(bytes,0,544);
    for(int i=0;i<2;i++) {
        ControllerState state=bridge->state(bridge->hands[i],0);
        std::memcpy(bytes+i*272,state.bytes.data(),state.bytes.size());
        // Do not ask prediction for a disconnected/unlocated controller.
        uint32_t connection=0;std::memcpy(&connection,state.bytes.data()+136,4);
        if(connection==2&&state.bytes[140]!=0) {
            PredictedPose pose=bridge->pose(bridge->hands[i],0.f);
            std::memcpy(bytes+i*272+208,pose.bytes.data(),pose.bytes.size());
        }
        std::memcpy(bytes+i*272+264,&bridge->hands[i],4);
    }
}

extern "C" JNIEXPORT void JNICALL
Java_org_gk3hd_standalone_PimaxControllers_close(JNIEnv*,jclass,jlong handle) {
    delete reinterpret_cast<Bridge*>(handle);
}

extern "C" JNIEXPORT jint JNICALL
Java_org_gk3hd_standalone_PimaxControllers_headStatus(JNIEnv* env,jclass,jlong handle) {
    auto* bridge=reinterpret_cast<Bridge*>(handle);
    if(!bridge) {fail(env,"Controller adapter closed");return 0;}
    // Firmware's own Java JNI wrapper reads status at byte 28 and timestamps
    // at 32/40/48 from this same 56-byte C aggregate. Diagnostic comparison
    // only: this result never substitutes for the rendered pose's validity.
    PredictedPose sample=bridge->head(0.f);
    uint32_t status=0;std::memcpy(&status,sample.bytes.data()+28,4);
    return static_cast<jint>(status);
}
