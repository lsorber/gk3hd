#pragma once

// Uses the actual device's controller samples and the exact Actions class used
// by the game. No synthetic tracking, mouse/controller injection or eye images.
struct InputRuntime {
    HMODULE library=nullptr;
    PFN_xrGetInstanceProcAddr resolve=nullptr;
    XrInstance instance=XR_NULL_HANDLE;XrSession session=XR_NULL_HANDLE;
    PFN_xrDestroyInstance destroyInstance=nullptr;
    PFN_xrDestroySession destroySession=nullptr;
    PFN_xrEndSession endSession=nullptr;
    template<class T> T function(const char* name) {
        PFN_xrVoidFunction out=nullptr;
        require(resolve(instance,name,&out)==XR_SUCCESS&&out!=nullptr,name);
        return reinterpret_cast<T>(out);
    }
    static void result(XrResult value,const char* name) {require(value==XR_SUCCESS,name);}
    explicit InputRuntime(const char* path) {
        library=LoadLibraryA(path);require(library!=nullptr,"No test OpenXR runtime");
        auto negotiate=reinterpret_cast<PFN_xrNegotiateLoaderRuntimeInterface>(GetProcAddress(library,"xrNegotiateLoaderRuntimeInterface"));
        require(negotiate!=nullptr,"No runtime negotiation");
        XrNegotiateLoaderInfo loader{XR_LOADER_INTERFACE_STRUCT_LOADER_INFO,1,sizeof(loader),1,1,XR_MAKE_VERSION(1,0,0),XR_CURRENT_API_VERSION};
        XrNegotiateRuntimeRequest runtime{XR_LOADER_INTERFACE_STRUCT_RUNTIME_REQUEST,1,sizeof(runtime)};
        result(negotiate(&loader,&runtime),"Runtime negotiation failed");resolve=runtime.getInstanceProcAddr;
        XrInstanceCreateInfo create{XR_TYPE_INSTANCE_CREATE_INFO};
        const char appName[]="GK3HD real-controller fixture";
        std::memcpy(create.applicationInfo.applicationName,appName,sizeof(appName));
        create.applicationInfo.apiVersion=XR_MAKE_VERSION(1,0,0);
        const char* extensions[]={XR_KHR_VULKAN_ENABLE_EXTENSION_NAME};
        create.enabledExtensionCount=1;create.enabledExtensionNames=extensions;
        result(function<PFN_xrCreateInstance>("xrCreateInstance")(&create,&instance),"Create XR input instance failed");
        destroyInstance=function<PFN_xrDestroyInstance>("xrDestroyInstance");
        destroySession=function<PFN_xrDestroySession>("xrDestroySession");endSession=function<PFN_xrEndSession>("xrEndSession");
    }
    ~InputRuntime() {
        if(session) {endSession(session);destroySession(session);}
        if(instance&&destroyInstance) destroyInstance(instance);
        if(library) FreeLibrary(library);
    }
    XrSpace startSession(Gpu& gpu) {
    XrSystemGetInfo systemInfo{XR_TYPE_SYSTEM_GET_INFO};systemInfo.formFactor=XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    XrSystemId system=0;result(function<PFN_xrGetSystem>("xrGetSystem")(instance,&systemInfo,&system),"Get XR system failed");
    XrGraphicsRequirementsVulkanKHR requirements{XR_TYPE_GRAPHICS_REQUIREMENTS_VULKAN_KHR};
    result(function<PFN_xrGetVulkanGraphicsRequirementsKHR>("xrGetVulkanGraphicsRequirementsKHR")
        (instance,system,&requirements),"Get Vulkan requirements failed");
    XrGraphicsBindingVulkanKHR graphics{XR_TYPE_GRAPHICS_BINDING_VULKAN_KHR};
    graphics.instance=gpu.instance;graphics.physicalDevice=gpu.physical;graphics.device=gpu.device;graphics.queueFamilyIndex=gpu.family;
    XrSessionCreateInfo create{XR_TYPE_SESSION_CREATE_INFO};create.next=&graphics;create.systemId=system;
    result(function<PFN_xrCreateSession>("xrCreateSession")(instance,&create,&session),"Create XR input session failed");
    XrReferenceSpaceCreateInfo local{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};local.referenceSpaceType=XR_REFERENCE_SPACE_TYPE_LOCAL;local.poseInReferenceSpace.orientation.w=1;
    XrSpace origin=XR_NULL_HANDLE;
    result(function<PFN_xrCreateReferenceSpace>("xrCreateReferenceSpace")(session,&local,&origin),"Create input origin failed");
    XrSessionBeginInfo begin{XR_TYPE_SESSION_BEGIN_INFO};begin.primaryViewConfigurationType=XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    result(function<PFN_xrBeginSession>("xrBeginSession")(session,&begin),"Begin input session failed");
    return origin;
    }
};

void runtimeImageLimitTests(const char* path) {
    Gpu gpu(true);InputRuntime xr(path);xr.startSession(gpu);
    XrSystemProperties properties{XR_TYPE_SYSTEM_PROPERTIES};
    InputRuntime::result(xr.function<PFN_xrGetSystemProperties>("xrGetSystemProperties")
        (xr.instance,1,&properties),"Native runtime image limits failed");
    VkPhysicalDeviceProperties device{};gpu.GetPhysicalDeviceProperties(gpu.physical,&device);
    const auto expected=worldImageLimits(device.limits);
    require(properties.graphicsProperties.maxSwapchainImageWidth==expected.width &&
            properties.graphicsProperties.maxSwapchainImageHeight==expected.height,
            "Native runtime does not report the bound GPU's image/framebuffer limits");
    std::cout<<"Actual runtime bound-GPU world limits: "<<expected.width<<'x'<<expected.height<<'\n';
}

void realControllerTests(const char* path) {
    Gpu gpu;InputRuntime xr(path);XrSpace origin=xr.startSession(gpu);
    {
        gk3hd::vr::Actions actions(xr.resolve);actions.initialize(xr.instance);actions.attach(xr.session);
        auto wait=xr.function<PFN_xrWaitFrame>("xrWaitFrame");auto start=xr.function<PFN_xrBeginFrame>("xrBeginFrame");
        auto end=xr.function<PFN_xrEndFrame>("xrEndFrame");auto poll=xr.function<PFN_xrPollEvent>("xrPollEvent");
        unsigned matched=0;gk3hd::vr::InputSnapshot input{};bool focused=false;
        for(unsigned frame=0;frame<300&&matched<20;frame++) {
            XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
            while(poll(xr.instance,&event)==XR_SUCCESS) {
                if(event.type==XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED)
                    focused=reinterpret_cast<XrEventDataSessionStateChanged*>(&event)->state==XR_SESSION_STATE_FOCUSED;
                event={XR_TYPE_EVENT_DATA_BUFFER};
            }
            XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState state{XR_TYPE_FRAME_STATE};
            InputRuntime::result(wait(xr.session,&wi,&state),"Input wait failed");
            XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};InputRuntime::result(start(xr.session,&bi),"Input begin failed");
            input=actions.sample(origin,state.predictedDisplayTime,focused);
            if((input.hands[0].flags&gk3hd::vr::AimValid)&&(input.hands[1].flags&gk3hd::vr::AimValid)) matched++;
            XrFrameEndInfo ei{XR_TYPE_FRAME_END_INFO};ei.displayTime=state.predictedDisplayTime;ei.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
            InputRuntime::result(end(xr.session,&ei),"Input end failed");
        }
        require(matched==20,"Both real controller poses did not reach the game's Actions implementation");
        for(unsigned hand=0;hand<2;hand++) {
            const auto& h=input.hands[hand];
            std::cout<<"REAL_CONTROLLER hand="<<hand<<" aimValid="<<h.flags<<" xyz="<<h.position[0]<<','<<h.position[1]<<','<<h.position[2]
                <<" stick="<<h.stick[0]<<','<<h.stick[1]<<" held="<<h.held<<'\n';
        }
        std::cout<<"Actual controller input passed through firmware, Android, WXR8, OpenXR and game Actions for "<<matched<<" samples; no head/eye acceptance claimed\n";
    }
    InputRuntime::result(xr.function<PFN_xrDestroySpace>("xrDestroySpace")(origin),"Destroy input origin failed");
}

// Actual runtime/session/action calls, with recorded Java packet fixtures.
// This checks focus admission; it is not physical-controller or display proof.
void inputLifetimeTests(const char* path,const char* packets) {
    Gpu gpu;InputRuntime xr(path);XrSpace origin=xr.startSession(gpu);
    SOCKET sender=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    require(sender!=INVALID_SOCKET,"Lifetime sender socket failed");
    sockaddr_in target{};target.sin_family=AF_INET;target.sin_port=htons(7872);
    target.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    auto send=[&](const char* name) {
        std::ifstream input(std::string(packets)+"/"+name,std::ios::binary);
        std::vector<char> bytes((std::istreambuf_iterator<char>(input)),{});
        require(bytes.size()==168,"Missing real Java focus fixture");
        require(sendto(sender,bytes.data(),int(bytes.size()),0,reinterpret_cast<sockaddr*>(&target),sizeof(target))==int(bytes.size()),"Input focus datagram failed");
    };
    auto wait=xr.function<PFN_xrWaitFrame>("xrWaitFrame");
    auto begin=xr.function<PFN_xrBeginFrame>("xrBeginFrame");
    auto end=xr.function<PFN_xrEndFrame>("xrEndFrame");
    auto poll=xr.function<PFN_xrPollEvent>("xrPollEvent");
    auto lastState=[&]() {
        XrSessionState result=XR_SESSION_STATE_UNKNOWN;
        XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
        while(poll(xr.instance,&event)==XR_SUCCESS) {
            if(event.type==XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED)
                result=reinterpret_cast<XrEventDataSessionStateChanged*>(&event)->state;
            event={XR_TYPE_EVENT_DATA_BUFFER};
        }
        return result;
    };
    {
        gk3hd::vr::Actions actions(xr.resolve);actions.initialize(xr.instance);actions.attach(xr.session);
        auto sample=[&](const char* packet,bool expectedFocus) {
            send(packet);
            XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState frame{XR_TYPE_FRAME_STATE};
            InputRuntime::result(wait(xr.session,&wi,&frame),"Focus fixture wait failed");
            XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};InputRuntime::result(begin(xr.session,&bi),"Focus fixture begin failed");
            // The renderer has not polled the new state yet. xrSyncActions must
            // still withdraw input in this very frame, without waiting for it.
            const auto input=actions.sample(origin,frame.predictedDisplayTime,true);
            require(bool(input.flags&gk3hd::vr::InputFocused)==expectedFocus,"Host focus did not reach actual Actions synchronization");
            if(!expectedFocus)for(const auto& hand:input.hands)
                require(!hand.held&&!hand.pressed,"Paused action survived synchronization");
            XrFrameEndInfo finish{XR_TYPE_FRAME_END_INFO};finish.displayTime=frame.predictedDisplayTime;
            finish.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
            InputRuntime::result(end(xr.session,&finish),"Focus fixture end failed");
            require(lastState()==(expectedFocus?XR_SESSION_STATE_FOCUSED:XR_SESSION_STATE_VISIBLE),"Host focus transition did not reach session events");
        };
        sample("focused.bin",true);sample("withdrawal.bin",false);sample("new-epoch.bin",true);
    }
    closesocket(sender);
    InputRuntime::result(xr.function<PFN_xrDestroySpace>("xrDestroySpace")(origin),"Destroy focus fixture origin failed");
    std::cout<<"Real runtime focus: Java packet, frame admission, same-frame action withdrawal, session event and fresh recovery passed; no headset presentation claimed\n";
}

// Synthetic host timing through the actual runtime. Does not present to a HMD.
void pendingStartupTests(const char* path,const char* packets) {
    Gpu gpu;InputRuntime xr(path);XrSpace origin=xr.startSession(gpu);
    auto wait=xr.function<PFN_xrWaitFrame>("xrWaitFrame");
    auto begin=xr.function<PFN_xrBeginFrame>("xrBeginFrame");
    auto end=xr.function<PFN_xrEndFrame>("xrEndFrame");
    auto poll=xr.function<PFN_xrPollEvent>("xrPollEvent");
    auto locate=xr.function<PFN_xrLocateViews>("xrLocateViews");
    auto lastState=[&]() {
        XrSessionState result=XR_SESSION_STATE_UNKNOWN;
        XrEventDataBuffer event{XR_TYPE_EVENT_DATA_BUFFER};
        while(poll(xr.instance,&event)==XR_SUCCESS) {
            if(event.type==XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED)
                result=reinterpret_cast<XrEventDataSessionStateChanged*>(&event)->state;
            event={XR_TYPE_EVENT_DATA_BUFFER};
        }
        return result;
    };
    require(lastState()==XR_SESSION_STATE_SYNCHRONIZED,"Startup claimed native visibility before tracking");
    XrTime previous=0;unsigned pending=0;
    const auto start=std::chrono::steady_clock::now();
    while(std::chrono::steady_clock::now()-start<std::chrono::milliseconds(5250)) {
        const auto before=std::chrono::steady_clock::now();
        XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState frame{XR_TYPE_FRAME_STATE};
        InputRuntime::result(wait(xr.session,&wi,&frame),"Pending startup became fatal");
        require(std::chrono::steady_clock::now()-before<std::chrono::seconds(1),"Pending startup blocked the frame loop");
        require(!frame.shouldRender&&frame.predictedDisplayTime>previous&&frame.predictedDisplayPeriod>0,
                "Pending startup invented a renderable frame or regressed time");
        previous=frame.predictedDisplayTime;++pending;
        XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};InputRuntime::result(begin(xr.session,&bi),"Pending begin failed");
        XrViewLocateInfo li{XR_TYPE_VIEW_LOCATE_INFO};li.space=origin;li.displayTime=frame.predictedDisplayTime;
        li.viewConfigurationType=XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
        XrViewState state{XR_TYPE_VIEW_STATE};XrView views[2]={{XR_TYPE_VIEW},{XR_TYPE_VIEW}};uint32_t count=0;
        InputRuntime::result(locate(xr.session,&li,&state,2,&count,views),"Pending views became fatal");
        require(!state.viewStateFlags,"Pending startup fabricated tracked eyes");
        XrFrameEndInfo finish{XR_TYPE_FRAME_END_INFO};finish.displayTime=frame.predictedDisplayTime;
        finish.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        InputRuntime::result(end(xr.session,&finish),"Pending empty frame failed");
        require(lastState()!=XR_SESSION_STATE_FOCUSED,"Pending startup invented input focus");
    }
    require(pending>=5,"Pending fixture did not service multiple frames");
    SOCKET sender=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    require(sender!=INVALID_SOCKET,"Startup sender socket failed");
    sockaddr_in target{};target.sin_family=AF_INET;target.sin_port=htons(7872);
    target.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    std::ifstream input(std::string(packets)+"/focused.bin",std::ios::binary);
    std::vector<char> bytes((std::istreambuf_iterator<char>(input)),{});
    require(bytes.size()==168,"Missing real Java startup packet fixture");
    require(sendto(sender,bytes.data(),int(bytes.size()),0,reinterpret_cast<sockaddr*>(&target),sizeof(target))==int(bytes.size()),"Delayed host datagram failed");
    XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState frame{XR_TYPE_FRAME_STATE};
    InputRuntime::result(wait(xr.session,&wi,&frame),"Delayed first host packet failed");
    require(frame.shouldRender&&frame.predictedDisplayTime>previous,"First actual packet did not resume rendering");
    require(lastState()==XR_SESSION_STATE_FOCUSED,"First actual packet did not restore focus");
    XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};InputRuntime::result(begin(xr.session,&bi),"Recovered begin failed");
    XrFrameEndInfo finish{XR_TYPE_FRAME_END_INFO};finish.displayTime=frame.predictedDisplayTime;
    finish.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    InputRuntime::result(end(xr.session,&finish),"Recovered empty frame failed");
    closesocket(sender);
    InputRuntime::result(xr.function<PFN_xrDestroySpace>("xrDestroySpace")(origin),"Destroy startup origin failed");
    std::cout<<"Pending startup survived the old deadline, serviced "<<pending<<" hidden frames, then recovered on an actual datagram; no HMD presentation claimed\n";
}

void startupPortConflictTests(const char* path) {
    WSADATA data{};require(WSAStartup(MAKEWORD(2,2),&data)==0,"Conflict socket startup failed");
    SOCKET owner=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    require(owner!=INVALID_SOCKET,"Conflict owner socket failed");
    sockaddr_in address{};address.sin_family=AF_INET;address.sin_port=htons(7872);
    address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
    require(bind(owner,reinterpret_cast<sockaddr*>(&address),sizeof(address))==0,"Conflict fixture port already occupied");
    {
        Gpu gpu;InputRuntime xr(path);xr.startSession(gpu);
        XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState frame{XR_TYPE_FRAME_STATE};
        const auto before=std::chrono::steady_clock::now();
        require(xr.function<PFN_xrWaitFrame>("xrWaitFrame")(xr.session,&wi,&frame)==XR_ERROR_RUNTIME_FAILURE,
                "Failed bind was incorrectly treated as pending tracking");
        require(std::chrono::steady_clock::now()-before<std::chrono::seconds(1),"Failed bind did not fail promptly");
    }
    closesocket(owner);WSACleanup();
    std::cout<<"Actual runtime reports occupied tracking port as a failure, not pending startup\n";
}
