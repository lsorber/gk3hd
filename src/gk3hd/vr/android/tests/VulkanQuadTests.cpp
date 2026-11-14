// Headless GPU fixture. Synthetic quads/poses never reach the game or headset.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#define XR_USE_GRAPHICS_API_VULKAN
#include <Winsock2.h>
#pragma comment(lib,"ws2_32.lib")
#include <windows.h>
#include "quad.h"
#include "../image_limits.h"
#include <openxr/openxr_platform.h>
#include <loader_interfaces.h>
#include "input.h"
#include <cmath>
#include <algorithm>
#include <chrono>
#include <cstring>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace gk3hd::standalone;
namespace {
void require(bool value,const char* message) {if(!value) throw std::runtime_error(message);}
void ok(VkResult value) {if(value!=VK_SUCCESS) throw std::runtime_error("GPU error "+std::to_string(value));}
void closeEnough(float a,float b) {require(std::abs(a-b)<.0001f,"Quad geometry mismatch");}
void imageLimitTests() {
    for(uint32_t image : {0u,1u,2u,3u,4u,5u,4095u,4096u,4097u,8192u,16384u})
        for(uint32_t framebuffer : {0u,1u,2u,3u,4u,5u,4095u,4096u,4097u,8192u,16384u}) {
            VkPhysicalDeviceLimits limits{};
            limits.maxImageDimension2D=image;limits.maxFramebufferWidth=framebuffer;
            limits.maxFramebufferHeight=framebuffer;
            const auto maximum=worldImageLimits(limits);
            require(maximum.width==std::min(image,framebuffer),"Image width exceeds an actual GPU limit");
            require(!maximum.height || (transportImageHeight(maximum.height)<=image && transportImageHeight(maximum.height)<=framebuffer),
                    "Metadata/padding exceeds an actual GPU limit");
            if(maximum.height)require(transportImageHeight(maximum.height+1)>std::min(image,framebuffer),
                    "A larger visible eye would fit the advertised GPU limits");
        }
    VkPhysicalDeviceLimits limits{};
    limits.maxImageDimension2D=16384;limits.maxFramebufferWidth=8192;limits.maxFramebufferHeight=4096;
    const auto maximum=worldImageLimits(limits);
    require(maximum.width==8192 && maximum.height==4095,"Asymmetric GPU limits were conflated");
    require(4120<=maximum.width && 2061<=maximum.height,"Full-sized stereo was capped at a guessed 4096 width");
}
void transportLayoutTests(const char* path) {
    std::ifstream input(path);require(bool(input),"Missing Java transport vectors");
    uint64_t visible=0,physical=0;unsigned count=0;
    while(input>>visible) {
        require(bool(input>>physical),"Truncated transport vector");
        require(++count<=5000 && visible<=UINT32_MAX && physical<=UINT32_MAX,"Unbounded transport vector");
        require(transportImageHeight(uint32_t(visible))==physical,"Java/native transport layout disagrees");
        require(physical>visible && physical-visible<=4 && physical%4==0,"Invalid native transport layout");
    }
    require(input.eof()&&count>4096,"Incomplete or malformed Java transport vectors");
    for(uint32_t value : {0u,UINT32_MAX-3,UINT32_MAX}) {
        try {transportImageHeight(value);throw std::runtime_error("Overflowing transport accepted");}
        catch(const std::invalid_argument&) {}
    }
    imageLimitTests();
    std::cout<<"Java/native visible-eye transport layout passed\n";
}
void mathTests() {
    XrPosef eye{{0,0,0,1},{0,0,0}},quad{{0,0,0,1},{0,0,-1}};
    XrFovf fov{-.785398163f,.785398163f,.785398163f,-.785398163f};
    auto p=projectQuad(eye,fov,quad,{1,1},{{8,4},{16,16}},32,32);
    closeEnough(p.clip[0][0],-.5f);closeEnough(p.clip[0][1],-.5f);closeEnough(p.clip[0][3],1);
    closeEnough(p.clip[3][0],.5f);closeEnough(p.clip[3][1],.5f);closeEnough(p.clip[3][2],.99f);
    closeEnough(p.uv[0],.25f);closeEnough(p.uv[1],.125f);closeEnough(p.uv[2],.75f);closeEnough(p.uv[3],.625f);
    eye.position.x=-.032f;auto left=projectQuad(eye,fov,quad,{1,1},{{0,0},{32,32}},32,32);
    eye.position.x=.032f;auto right=projectQuad(eye,fov,quad,{1,1},{{0,0},{32,32}},32,32);
    closeEnough(left.clip[0][0]-right.clip[0][0],.064f);
    // A shared world rotation cannot alter the panel's perceived geometry.
    float s=std::sqrt(.5f);eye={{0,s,0,s},{0,0,0}};quad={{0,s,0,s},{-1,0,0}};
    auto rotated=projectQuad(eye,fov,quad,{1,1},{{8,4},{16,16}},32,32);
    for(int i=0;i<4;i++) for(int j=0;j<4;j++) closeEnough(rotated.clip[i][j],p.clip[i][j]);
    try {projectQuad(eye,fov,quad,{1,1},{{20,0},{16,16}},32,32);throw std::runtime_error("Bad crop accepted");}
    catch(const std::invalid_argument&) {}
}
#define GPU_COMMANDS(X) \
    X(DestroyInstance) X(EnumeratePhysicalDevices) X(GetPhysicalDeviceQueueFamilyProperties) X(GetPhysicalDeviceProperties) \
    X(GetPhysicalDeviceMemoryProperties) X(CreateDevice) X(GetDeviceProcAddr) \
    X(DestroyDevice) X(GetDeviceQueue) X(CreateCommandPool) X(DestroyCommandPool) \
    X(AllocateCommandBuffers) X(BeginCommandBuffer) X(EndCommandBuffer) X(ResetCommandBuffer) \
    X(CreateImage) X(DestroyImage) X(GetImageMemoryRequirements) X(AllocateMemory) X(FreeMemory) X(BindImageMemory) \
    X(CreateBuffer) X(DestroyBuffer) X(GetBufferMemoryRequirements) X(BindBufferMemory) X(MapMemory) X(UnmapMemory) \
    X(CmdPipelineBarrier) X(CmdClearColorImage) X(CmdCopyBufferToImage) X(CmdCopyImageToBuffer) X(CmdBlitImage) X(QueueSubmit) X(QueueWaitIdle)
struct Gpu {
    HMODULE library=nullptr;VkInstance instance=VK_NULL_HANDLE;VkDevice device=VK_NULL_HANDLE;
    VkPhysicalDevice physical=VK_NULL_HANDLE;VkQueue queue=VK_NULL_HANDLE;VkCommandPool pool=VK_NULL_HANDLE;
    uint32_t family=UINT32_MAX;
    VkCommandBuffer command=VK_NULL_HANDLE;VkPhysicalDeviceMemoryProperties memory{};
#define DECLARE(name) PFN_vk##name name=nullptr;
    GPU_COMMANDS(DECLARE)
#undef DECLARE
    struct Image {VkImage image=VK_NULL_HANDLE;VkDeviceMemory memory=VK_NULL_HANDLE;};
    Image target,source;
    VkBuffer buffer=VK_NULL_HANDLE;VkDeviceMemory bufferMemory=VK_NULL_HANDLE;
    uint32_t targetWidth;
    explicit Gpu(bool presentation=false,uint32_t width=256,VkFormat targetFormat=VK_FORMAT_B8G8R8A8_SRGB):targetWidth(width) {
        require(width>=256&&width<=8192,"Bounded compositor fixture width required");
        library=LoadLibraryW(L"vulkan-1.dll");require(library!=nullptr,"No Vulkan loader");
        auto resolve=reinterpret_cast<PFN_vkGetInstanceProcAddr>(GetProcAddress(library,"vkGetInstanceProcAddr"));
        require(resolve!=nullptr,"No Vulkan instance resolver");
        auto create=reinterpret_cast<PFN_vkCreateInstance>(resolve(VK_NULL_HANDLE,"vkCreateInstance"));
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};app.pApplicationName="GK3HD headless compositor test";app.apiVersion=VK_API_VERSION_1_0;
        VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};info.pApplicationInfo=&app;
        const char* surfaceExtensions[]={"VK_KHR_surface","VK_KHR_win32_surface"};
        if(presentation) {info.enabledExtensionCount=2;info.ppEnabledExtensionNames=surfaceExtensions;}
        ok(create(&info,nullptr,&instance));
#define LOAD(name) name=reinterpret_cast<PFN_vk##name>(resolve(instance,"vk" #name));require(name!=nullptr,"Missing vk" #name);
        GPU_COMMANDS(LOAD)
#undef LOAD
        uint32_t count=0;ok(EnumeratePhysicalDevices(instance,&count,nullptr));require(count>0,"No Vulkan GPU");
        std::vector<VkPhysicalDevice> devices(count);ok(EnumeratePhysicalDevices(instance,&count,devices.data()));
        for(auto candidate:devices) {
            GetPhysicalDeviceQueueFamilyProperties(candidate,&count,nullptr);
            std::vector<VkQueueFamilyProperties> families(count);GetPhysicalDeviceQueueFamilyProperties(candidate,&count,families.data());
            for(uint32_t i=0;i<count;i++) if(families[i].queueFlags&VK_QUEUE_GRAPHICS_BIT) {physical=candidate;family=i;break;}
            if(physical) break;
        }
        require(physical!=VK_NULL_HANDLE,"No graphics queue");
        VkPhysicalDeviceProperties properties{};GetPhysicalDeviceProperties(physical,&properties);
        std::cout<<"GPU: "<<properties.deviceName<<'\n';
        float priority=1;VkDeviceQueueCreateInfo q{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
        q.queueFamilyIndex=family;q.queueCount=1;q.pQueuePriorities=&priority;
        VkDeviceCreateInfo d{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};d.queueCreateInfoCount=1;d.pQueueCreateInfos=&q;
        const char* swapchainExtension="VK_KHR_swapchain";
        if(presentation) {d.enabledExtensionCount=1;d.ppEnabledExtensionNames=&swapchainExtension;}
        ok(CreateDevice(physical,&d,nullptr,&device));GetDeviceQueue(device,family,0,&queue);
        GetPhysicalDeviceMemoryProperties(physical,&memory);
        VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};cp.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;cp.queueFamilyIndex=family;
        ok(CreateCommandPool(device,&cp,nullptr,&pool));
        VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=pool;ca.commandBufferCount=1;
        ok(AllocateCommandBuffers(device,&ca,&command));
        target=image(targetWidth,128,targetFormat,VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
        source=image(32,32,VK_FORMAT_R8G8B8A8_SRGB,VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT|VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT);
        VkBufferCreateInfo bc{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};bc.size=targetWidth*128*4;bc.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        ok(CreateBuffer(device,&bc,nullptr,&buffer));VkMemoryRequirements mr{};GetBufferMemoryRequirements(device,buffer,&mr);
        VkMemoryAllocateInfo allocate{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};allocate.allocationSize=mr.size;
        allocate.memoryTypeIndex=memoryType(mr.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        ok(AllocateMemory(device,&allocate,nullptr,&bufferMemory));ok(BindBufferMemory(device,buffer,bufferMemory,0));
    }
    uint32_t memoryType(uint32_t bits,VkMemoryPropertyFlags flags) {
        for(uint32_t i=0;i<memory.memoryTypeCount;i++) if((bits&(1u<<i))&&(memory.memoryTypes[i].propertyFlags&flags)==flags) return i;
        throw std::runtime_error("No compatible GPU memory");
    }
    Image image(uint32_t width,uint32_t height,VkFormat format,VkImageUsageFlags usage) {
        Image out;VkImageCreateInfo info{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};info.imageType=VK_IMAGE_TYPE_2D;
        info.extent={width,height,1};info.mipLevels=info.arrayLayers=1;info.format=format;info.samples=VK_SAMPLE_COUNT_1_BIT;info.usage=usage;
        ok(CreateImage(device,&info,nullptr,&out.image));VkMemoryRequirements mr{};GetImageMemoryRequirements(device,out.image,&mr);
        VkMemoryAllocateInfo allocate{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};allocate.allocationSize=mr.size;
        allocate.memoryTypeIndex=memoryType(mr.memoryTypeBits,0);ok(AllocateMemory(device,&allocate,nullptr,&out.memory));
        ok(BindImageMemory(device,out.image,out.memory,0));return out;
    }
    void begin() {ok(ResetCommandBuffer(command,0));VkCommandBufferBeginInfo b{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};ok(BeginCommandBuffer(command,&b));}
    void barrier(VkImage image,VkImageLayout old,VkImageLayout next) {
        VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};b.oldLayout=old;b.newLayout=next;
        b.srcAccessMask=old==VK_IMAGE_LAYOUT_UNDEFINED ? 0 : VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT;
        b.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT;
        b.srcQueueFamilyIndex=b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;b.image=image;b.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        CmdPipelineBarrier(command,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,0,nullptr,0,nullptr,1,&b);
    }
    void submit() {ok(EndCommandBuffer(command));VkSubmitInfo s{VK_STRUCTURE_TYPE_SUBMIT_INFO};s.commandBufferCount=1;s.pCommandBuffers=&command;ok(QueueSubmit(queue,1,&s,VK_NULL_HANDLE));ok(QueueWaitIdle(queue));}
    void upload(unsigned char r,unsigned char g,unsigned char b,unsigned char a,bool pattern=false) {
        void* mapped=nullptr;ok(MapMemory(device,bufferMemory,0,32*32*4,0,&mapped));
        auto* pixels=static_cast<unsigned char*>(mapped);
        for(int i=0;i<32*32;i++) {
            bool right=i%32>=16,bottom=i/32>=16;
            pixels[i*4]=pattern ? (!right&&!bottom ? 255 : 0) : r;
            pixels[i*4+1]=pattern ? (right ? 255 : 0) : g;
            pixels[i*4+2]=pattern ? (bottom ? 255 : 0) : b;pixels[i*4+3]=a;
        }
        UnmapMemory(device,bufferMemory);begin();barrier(source.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        VkBufferImageCopy copy{};copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={32,32,1};
        CmdCopyBufferToImage(command,buffer,source.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,1,&copy);
        barrier(source.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);submit();
    }
    std::vector<unsigned char> draw(QuadComposer& composer,unsigned blend,bool oneEye=false,
                                    XrRect2Di crop={{0,0},{32,32}},const uint32_t* frame=nullptr,bool markerOnly=false,
                                    bool packedStereo=false,const std::array<uint32_t,5>* bootstrap=nullptr) {
        begin();barrier(target.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        VkClearColorValue black{};black.float32[2]=.25f;black.float32[3]=1;
        VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        CmdClearColorImage(command,target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&black,1,&range);
        std::vector<QuadDraw> draws;
        for(int eye=0;eye<(oneEye?1:2);eye++) {
            QuadDraw d;d.image=source.image;d.format=VK_FORMAT_R8G8B8A8_SRGB;d.blend=blend;
            d.viewport={{eye*128,0},{128,128}};
            XrPosef pose{{0,0,0,1},{eye==0 ? -.032f : .032f,0,0}},panel{{0,0,0,1},{0,0,-1}};
            XrFovf fov{-.785398163f,.785398163f,.785398163f,-.785398163f};
            d.vertices=projectQuad(pose,fov,panel,{1,1},crop,32,32);
            if(packedStereo) {
                // Two projection subimages may share one released allocation.
                // Use disjoint horizontal halves with different source colors,
                // not two identical copies that could hide a wrong eye crop.
                for(unsigned corner=0;corner<4;corner++) {
                    d.vertices.clip[corner][0]=(corner&2) ? 1.f : -1.f;
                    d.vertices.clip[corner][1]=(corner&1) ? 1.f : -1.f;
                    d.vertices.clip[corner][2]=0;d.vertices.clip[corner][3]=1;
                }
                d.vertices.uv[0]=float(eye)*.5f;d.vertices.uv[1]=0;
                d.vertices.uv[2]=float(eye+1)*.5f;d.vertices.uv[3]=1;
            }
            draws.push_back(d);
        }
        if(markerOnly) draws.clear();
        composer.record(command,target.image,{targetWidth,128},draws,frame,bootstrap);
        barrier(target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        VkBufferImageCopy copy{};copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};copy.imageExtent={targetWidth,128,1};
        CmdCopyImageToBuffer(command,target.image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,buffer,1,&copy);submit();
        void* mapped=nullptr;ok(MapMemory(device,bufferMemory,0,targetWidth*128*4,0,&mapped));
        std::vector<unsigned char> bytes(targetWidth*128*4);std::memcpy(bytes.data(),mapped,bytes.size());UnmapMemory(device,bufferMemory);return bytes;
    }
    void preservingMarker(QuadComposer& composer,uint32_t height) {
        const auto bytes=VkDeviceSize(targetWidth)*height*4;
        std::vector<unsigned char> expected(static_cast<size_t>(bytes));
        for(size_t i=0;i<expected.size();++i)
            expected[i]=static_cast<unsigned char>((i*127)^(i/11)^(i/targetWidth));
        void* mapped=nullptr;
        ok(MapMemory(device,bufferMemory,0,bytes,0,&mapped));
        std::memcpy(mapped,expected.data(),expected.size());
        UnmapMemory(device,bufferMemory);
        begin();
        barrier(target.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        VkBufferImageCopy copy{};
        copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};
        copy.imageExtent={targetWidth,height,1};
        CmdCopyBufferToImage(command,buffer,target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,1,&copy);
        barrier(target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
        uint32_t pose=0x9adb2461u;
        const std::array<uint32_t,5> tags{{13,29,38,42,53}};
        composer.record(command,target.image,{targetWidth,height},{},&pose,&tags,true);
        barrier(target.image,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        CmdCopyImageToBuffer(command,target.image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,buffer,1,&copy);
        submit();
        for(size_t block=0;block<6;block++) {
            uint32_t value=block?tags[block-1]:pose;
            const uint32_t words[]={0x47583346u,value,~value};
            for(size_t bit=0;bit<96;bit++) {
                const size_t cell=(size_t(height-1)*targetWidth+block*96+bit)*4;
                const unsigned char color=words[bit/32]&(1u<<(bit%32)) ? 255 : 0;
                expected[cell]=expected[cell+1]=expected[cell+2]=color;
                expected[cell+3]=255;
            }
        }
        ok(MapMemory(device,bufferMemory,0,bytes,0,&mapped));
        bool exact=std::memcmp(mapped,expected.data(),expected.size())==0;
        UnmapMemory(device,bufferMemory);
        require(exact,"RGBA direct marker pass changed world pixels, padding or identity");
        std::cout<<"Direct marker preserves "<<bytes<<" expected RGBA bytes\n";
    }
    ~Gpu() {
        if(device) {
            QueueWaitIdle(queue);
            if(buffer) DestroyBuffer(device,buffer,nullptr);if(bufferMemory) FreeMemory(device,bufferMemory,nullptr);
            for(auto i:{source,target}) {if(i.image) DestroyImage(device,i.image,nullptr);if(i.memory) FreeMemory(device,i.memory,nullptr);}
            if(pool) DestroyCommandPool(device,pool,nullptr);DestroyDevice(device,nullptr);
        }
        if(instance) DestroyInstance(instance,nullptr);if(library) FreeLibrary(library);
    }
};
float linear(unsigned char s) {float v=s/255.f;return v<=.04045f ? v/12.92f : std::pow((v+.055f)/1.055f,2.4f);}
int encoded(float v) {return int(std::lround(255*(v<=.0031308f ? v*12.92f : 1.055f*std::pow(v,1/2.4f)-.055f)));}
int pixel(const std::vector<unsigned char>& image,int x,int y,int rgb) {return image[(y*256+x)*4+2-rgb];}
void gpuTests() {
    Gpu gpu;
    QuadComposer composer(gpu.device,gpu.GetDeviceProcAddr);
    gpu.upload(128,64,32,0);auto opaque=gpu.draw(composer,0);
    for(int x:{64,192}) {require(std::abs(pixel(opaque,x,64,0)-128)<=1,"Opaque sRGB red changed");require(std::abs(pixel(opaque,x,64,1)-64)<=1,"Opaque sRGB green changed");}
    require(pixel(opaque,32,64,0)==0&&pixel(opaque,35,64,0)==128,"Left eye disparity missing");
    require(pixel(opaque,128+29,64,0)==0&&pixel(opaque,128+31,64,0)==128,"Right eye disparity missing");
    gpu.upload(128,64,32,128);auto straight=gpu.draw(composer,2);
    float alpha=128/255.f;
    int expected[]={encoded(linear(128)*alpha),encoded(linear(64)*alpha),encoded(linear(32)*alpha+.25f*(1-alpha))};
    for(int c=0;c<3;c++) require(std::abs(pixel(straight,64,64,c)-expected[c])<=2,"Straight alpha/sRGB blend mismatch");
    gpu.upload(static_cast<unsigned char>(encoded(linear(128)*alpha)),static_cast<unsigned char>(encoded(linear(64)*alpha)),
        static_cast<unsigned char>(encoded(linear(32)*alpha)),128);
    auto premult=gpu.draw(composer,1);
    for(int c=0;c<3;c++) require(std::abs(pixel(premult,64,64,c)-expected[c])<=2,"Premultiplied alpha mismatch");
    auto one=gpu.draw(composer,0,true);require(pixel(one,192,64,0)==0,"Left-only layer leaked to right eye");
    gpu.upload(0,0,0,255,true);auto pattern=gpu.draw(composer,0);
    require(pixel(pattern,48,48,0)==255&&pixel(pattern,80,48,1)==255&&pixel(pattern,48,80,2)==255,
        "Panel texture orientation is inverted");
    auto cropped=gpu.draw(composer,0,false,{{16,0},{16,16}});
    for(int x:{48,80,176,208}) require(pixel(cropped,x,48,1)==255&&pixel(cropped,x,80,0)==0,
        "Texture subrectangle ignored or stretched from whole image");
    for(unsigned repeat=0;repeat<3;repeat++) {
        auto packed=gpu.draw(composer,0,false,{{0,0},{32,32}},nullptr,false,true);
        for(int x:{16,64,112}) {
            require(pixel(packed,x,32,0)==255&&pixel(packed,x,32,1)==0&&pixel(packed,x,32,2)==0,
                    "Packed left eye lost its source origin");
            require(pixel(packed,x,96,0)==0&&pixel(packed,x,96,1)==0&&pixel(packed,x,96,2)==255,
                    "Packed left eye changed vertical orientation");
            require(pixel(packed,x+128,32,0)==0&&pixel(packed,x+128,32,1)==255&&pixel(packed,x+128,32,2)==0,
                    "Packed right eye sampled the left eye or the full source");
            require(pixel(packed,x+128,96,0)==0&&pixel(packed,x+128,96,1)==255&&pixel(packed,x+128,96,2)==255,
                    "Packed right eye changed its lower source region");
        }
    }
    auto unpacked=gpu.draw(composer,0);
    require(pixel(unpacked,48,48,0)==255&&pixel(unpacked,176,48,0)==255,
            "Returning from packed to ordinary subimages retained stale crop state");
    composer.reset();gpu.upload(200,100,50,255);auto recreated=gpu.draw(composer,0);
    require(std::abs(pixel(recreated,64,64,0)-200)<=1,"Target recreation lost panel");
    std::vector<uint32_t> markerIds{0u,255u,256u,0x87654321u,0xffffffffu};
    for(unsigned bit=0;bit<32;bit++) {
        markerIds.push_back(uint32_t(1)<<bit);markerIds.push_back(~(uint32_t(1)<<bit));
    }
    uint32_t seed=0x12345678u;
    for(unsigned sample=0;sample<16;sample++) {seed=seed*1664525u+1013904223u;markerIds.push_back(seed);}
    for(uint32_t id:markerIds) {
        for(bool markerOnly:{false,true}) {
            auto marked=gpu.draw(composer,0,false,{{0,0},{32,32}},&id,markerOnly);
            const uint32_t words[]={0x47583346u,id,~id};
            for(unsigned bit=0;bit<96;bit++) for(int channel=0;channel<3;channel++)
                require(pixel(marked,bit,127,channel)==((words[bit/32]&(1u<<(bit%32))) ? 255 : 0),
                    "GPU frame marker doesn't match the exact 32-bit ID/check");
            for(unsigned bit=0;bit<96;bit++)
                require(marked[(127*256+bit)*4+3]==255,"Frame marker lost opaque alpha");
            if(!markerOnly) require(std::abs(pixel(marked,64,64,0)-200)<=1,"Metadata damaged the visible image");
        }
    }
    // Validate all six independently checked blocks, including epoch and
    // unsigned composition. These commands must carry their own values, not
    // refer to a CPU staging allocation overwritten by the next frame.
    Gpu extended(false,640);QuadComposer extendedComposer(extended.device,extended.GetDeviceProcAddr);
    extended.upload(200,100,50,255);
    for(uint32_t serial: {1u,0x80000001u,0xffffffffu}) {
        uint32_t pose=serial^0x12345678u;
        std::array<uint32_t,5> tags{{0x11223344,0x55667788,0x99aabbcc,0xddeeff00,serial}};
        for(bool onlyMetadata: {false,true}) {
            auto bytes=extended.draw(extendedComposer,0,false,{{0,0},{32,32}},&pose,onlyMetadata,false,&tags);
            for(unsigned block=0;block<6;block++) {
                uint32_t value=block==0 ? pose : tags[block-1];
                uint32_t words[]={0x47583346u,value,~value};
                for(unsigned bit=0;bit<96;bit++) {
                    unsigned at=(127*640+block*96+bit)*4;
                    unsigned char expectedBit=(words[bit/32]&(1u<<(bit%32))) ? 255 : 0;
                    for(unsigned channel=0;channel<3;channel++)
                        require(bytes[at+channel]==expectedBit,"Extended GPU identity block mismatch");
                    require(bytes[at+3]==255,"Extended metadata lost opaque alpha");
                }
            }
        }
    }
}
#include "RuntimeInputTests.h"
#include "RuntimeStereoTests.h"
#include "CompositionBenchmark.h"
}
int main(int argc,char** argv) {
    try {
        imageLimitTests();
        if(argc==2&&std::strcmp(argv[1],"--image-limits")==0) {
            std::cout<<"GPU-derived image/framebuffer bounds and metadata row checks passed\n";return 0;
        }
        if(argc==3&&std::strcmp(argv[1],"--transport-layout")==0) {
            transportLayoutTests(argv[2]);return 0;
        }
        if(argc==3&&std::strcmp(argv[1],"--runtime-image-limits")==0) {
            runtimeImageLimitTests(argv[2]);return 0;
        }
        if(argc==3&&std::strcmp(argv[1],"--composition-benchmark")==0) {
            require(std::strcmp(argv[2],"128")==0 || std::strcmp(argv[2],"1030")==0 || std::strcmp(argv[2],"2060")==0,
                    "Expected eye size 128, 1030 or 2060");
            compositionBenchmark(static_cast<unsigned>(std::stoul(argv[2])));return 0;
        }
        if(argc==3&&std::strcmp(argv[1],"--controllers")==0) {realControllerTests(argv[2]);return 0;}
        if(argc==4&&std::strcmp(argv[1],"--input-lifetime")==0) {inputLifetimeTests(argv[2],argv[3]);return 0;}
        if(argc==4&&std::strcmp(argv[1],"--startup-pending")==0) {pendingStartupTests(argv[2],argv[3]);return 0;}
        if(argc==3&&std::strcmp(argv[1],"--startup-port-conflict")==0) {startupPortConflictTests(argv[2]);return 0;}
        if(argc==3&&std::strcmp(argv[1],"--stereo-transport")==0) {stereoTransportTests(argv[2]);return 0;}
        if(argc==2&&std::strcmp(argv[1],"--stereo-transport")==0) {stereoTransportTests("openxr_wxr32.dll");return 0;}
        if(argc==3&&std::strcmp(argv[1],"--stereo-lifecycle")==0) {stereoTransportTests(argv[2],4);return 0;}
        if(argc==2&&std::strcmp(argv[1],"--stereo-lifecycle")==0) {stereoTransportTests("openxr_wxr32.dll",4);return 0;}
        require(argc==1,"Expected no arguments, --composition-benchmark EYE_SIZE, or --controllers/--stereo-transport/--stereo-lifecycle RUNTIME_DLL");
        mathTests();gpuTests();
        {
            constexpr VkFormat format=VK_FORMAT_R8G8B8A8_SRGB;
            Gpu gpu(false,640,format);
            QuadComposer composer(gpu.device,gpu.GetDeviceProcAddr,format,true);
            gpu.preservingMarker(composer,128);
        }
        std::cout<<"Vulkan quads passed: real GPU, per-eye disparity, sRGB, alpha, visibility, orientation, crops, recreation and exact frame metadata\n";return 0;}
    catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
