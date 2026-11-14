// Opt-in lab benchmark. Not part of normal tests or game presentation.
// Queue-idle retirement belongs to this isolated fixture, not production.
void compositionBenchmark(unsigned eyeSize) {
    require(eyeSize==128 || eyeSize==1030 || eyeSize==2060,"Unsupported benchmark size");
    Gpu gpu;
    VkPhysicalDeviceProperties properties{};
    gpu.GetPhysicalDeviceProperties(gpu.physical,&properties);
    uint32_t count=0;
    gpu.GetPhysicalDeviceQueueFamilyProperties(gpu.physical,&count,nullptr);
    std::vector<VkQueueFamilyProperties> families(count);
    gpu.GetPhysicalDeviceQueueFamilyProperties(gpu.physical,&count,families.data());
    const auto bits=families[gpu.family].timestampValidBits;
    require(bits>0 && bits<=64 && properties.limits.timestampPeriod>0,"Unsupported timestamp clock");
#define TIMING_FUNCTIONS(X) X(CreateQueryPool) X(DestroyQueryPool) X(CmdResetQueryPool) X(CmdWriteTimestamp) X(GetQueryPoolResults)
#define LOAD_TIMING(name) auto name=reinterpret_cast<PFN_vk##name>(gpu.GetDeviceProcAddr(gpu.device,"vk" #name)); require(name!=nullptr,"Missing timing function");
    TIMING_FUNCTIONS(LOAD_TIMING)
#undef LOAD_TIMING
#undef TIMING_FUNCTIONS
    struct Queries {
        VkDevice device; VkQueryPool pool=VK_NULL_HANDLE; PFN_vkDestroyQueryPool destroy;
        ~Queries() {if(pool) destroy(device,pool,nullptr);}
    } queries{gpu.device,VK_NULL_HANDLE,DestroyQueryPool};
    VkQueryPoolCreateInfo info{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO};
    info.queryType=VK_QUERY_TYPE_TIMESTAMP;info.queryCount=2;
    ok(CreateQueryPool(gpu.device,&info,nullptr,&queries.pool));
    gpu.DestroyImage(gpu.device,gpu.target.image,nullptr);
    gpu.FreeMemory(gpu.device,gpu.target.memory,nullptr);
    gpu.target={};
    gpu.target=gpu.image(eyeSize*2,eyeSize+1,VK_FORMAT_B8G8R8A8_SRGB,
        VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT);
    gpu.upload(128,64,32,255);
    QuadComposer composer(gpu.device,gpu.GetDeviceProcAddr);
    std::vector<QuadDraw> draws;
    for(unsigned eye=0;eye<2;eye++) {
        QuadDraw d;d.image=gpu.source.image;d.format=VK_FORMAT_R8G8B8A8_SRGB;
        d.viewport={{static_cast<int>(eye*eyeSize),0},{eyeSize,eyeSize}};
        for(unsigned corner=0;corner<4;corner++) {
            d.vertices.clip[corner][0]=(corner&2) ? 1.f : -1.f;
            d.vertices.clip[corner][1]=(corner&1) ? 1.f : -1.f;
            d.vertices.clip[corner][3]=1;
        }
        d.vertices.uv[2]=d.vertices.uv[3]=1;draws.push_back(d);
    }
    const uint64_t mask=bits==64 ? UINT64_MAX : (uint64_t(1)<<bits)-1;
    using Clock=std::chrono::steady_clock;
    auto microseconds=[](Clock::time_point a,Clock::time_point b) {
        return std::chrono::duration<double,std::micro>(b-a).count();
    };
    bool initialized=false;
    for(unsigned mode=0;mode<3;mode++) {
        const std::vector<QuadDraw> empty;
        std::vector<double> recording,gpuTime,submission;
        // Eight warmups and forty observed samples. No per-frame pixel copy.
        for(uint32_t sample=0;sample<48;sample++) {
            gpu.begin();
            gpu.barrier(gpu.target.image,initialized ? VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL : VK_IMAGE_LAYOUT_UNDEFINED,
                        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
            initialized=true;
            CmdResetQueryPool(gpu.command,queries.pool,0,2);
            CmdWriteTimestamp(gpu.command,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queries.pool,0);
            const auto first=Clock::now();
            composer.record(gpu.command,gpu.target.image,{eyeSize*2,eyeSize+1},mode==2 ? empty : draws,
                            mode==0 ? nullptr : &sample);
            const auto last=Clock::now();
            CmdWriteTimestamp(gpu.command,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queries.pool,1);
            const auto submitted=Clock::now();gpu.submit();const auto retired=Clock::now();
            // Existing fixture retirement precedes this read, avoiding stale
            // availability from an earlier query generation. Never use WAIT.
            struct Result {uint64_t value,available;} result[2]{};
            ok(GetQueryPoolResults(gpu.device,queries.pool,0,2,sizeof(result),result,sizeof(Result),
                VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WITH_AVAILABILITY_BIT));
            require(result[0].available && result[1].available,"Unavailable completed composition timestamp");
            const double elapsed=double((result[1].value-result[0].value)&mask)*properties.limits.timestampPeriod/1000.;
            const double upper=microseconds(first,retired);
            const double wrap=std::ldexp(double(properties.limits.timestampPeriod),static_cast<int>(bits))/1000.;
            require(std::isfinite(elapsed) && upper<wrap && elapsed<=upper*1.02+100,"Invalid GPU composition interval");
            if(sample>=8) {recording.push_back(microseconds(first,last));gpuTime.push_back(elapsed);submission.push_back(microseconds(submitted,retired));}
        }
        auto median=[](std::vector<double> values) {std::sort(values.begin(),values.end());return (values[19]+values[20])*.5;};
        auto p95=[](std::vector<double> values) {std::sort(values.begin(),values.end());return values[37];};
        std::cout<<"composition eye="<<eyeSize<<" mode="<<mode<<" samples=40 record_us="<<median(recording)
                 <<" record_p95_us="<<p95(recording)<<" gpu_envelope_us="<<median(gpuTime)
                 <<" gpu_envelope_p95_us="<<p95(gpuTime)<<" submit_retire_us="<<median(submission)<<'\n';
    }
}
