#include "quad.h"
#include <algorithm>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>

namespace gk3hd::standalone {
namespace {
void check(VkResult result,const char* operation) {
    if(result!=VK_SUCCESS) throw std::runtime_error(std::string(operation)+": "+std::to_string(result));
}
constexpr uint32_t vertexCode[]=
#include "quad.vert.inc"
;
constexpr uint32_t fragmentCode[]=
#include "quad.frag.inc"
;
#define COMPOSITOR_FUNCTIONS(X) \
    X(CreateShaderModule) X(DestroyShaderModule) X(CreateRenderPass) X(DestroyRenderPass) \
    X(CreateSampler) X(DestroySampler) X(CreateDescriptorSetLayout) X(DestroyDescriptorSetLayout) \
    X(CreatePipelineLayout) X(DestroyPipelineLayout) X(CreateGraphicsPipelines) X(DestroyPipeline) \
    X(CreateDescriptorPool) X(DestroyDescriptorPool) X(ResetDescriptorPool) X(AllocateDescriptorSets) \
    X(UpdateDescriptorSets) X(CreateImageView) X(DestroyImageView) X(CreateFramebuffer) X(DestroyFramebuffer) \
    X(CmdPipelineBarrier) X(CmdBeginRenderPass) X(CmdEndRenderPass) X(CmdBindPipeline) \
    X(CmdBindDescriptorSets) X(CmdPushConstants) X(CmdSetViewport) X(CmdSetScissor) X(CmdDraw) X(CmdClearAttachments)
}

struct QuadComposer::State {
    VkFormat targetFormat;
    bool colorLayout;
    VkDevice device;
#define DECLARE(name) PFN_vk##name name=nullptr;
    COMPOSITOR_FUNCTIONS(DECLARE)
#undef DECLARE
    VkRenderPass pass=VK_NULL_HANDLE;
    VkSampler sampler=VK_NULL_HANDLE;
    VkDescriptorSetLayout descriptorLayout=VK_NULL_HANDLE;
    VkPipelineLayout layout=VK_NULL_HANDLE;
    VkPipeline pipelines[3]={};
    struct Frame {
        VkExtent2D extent{};
        VkImageView targetView=VK_NULL_HANDLE;
        VkFramebuffer framebuffer=VK_NULL_HANDLE;
        VkDescriptorPool pool=VK_NULL_HANDLE;
        std::vector<VkImageView> sources;
    };
    std::map<VkImage,Frame> frames;
    State(VkDevice value,PFN_vkGetDeviceProcAddr resolve,VkFormat format,bool preserve)
        :targetFormat(format),colorLayout(preserve),device(value) {
        if(!device||!resolve) throw std::invalid_argument("Missing compositor device/resolver");
#define LOAD(name) name=reinterpret_cast<PFN_vk##name>(resolve(device,"vk" #name)); \
    if(!name) throw std::runtime_error("Missing Vulkan command vk" #name);
        COMPOSITOR_FUNCTIONS(LOAD)
#undef LOAD
        try {initialize();} catch(...) {destroy();throw;}
    }
    ~State() {destroy();}
    void clear(Frame& frame) {
        for(auto image:frame.sources) DestroyImageView(device,image,nullptr);
        frame.sources.clear();
        if(frame.framebuffer) DestroyFramebuffer(device,frame.framebuffer,nullptr);
        if(frame.targetView) DestroyImageView(device,frame.targetView,nullptr);
        if(frame.pool) DestroyDescriptorPool(device,frame.pool,nullptr);
        frame=Frame{};
    }
    void reset() {for(auto& pair:frames) clear(pair.second);frames.clear();}
    void destroy() {
        reset();
        for(auto& pipeline:pipelines) {if(pipeline) DestroyPipeline(device,pipeline,nullptr);pipeline=VK_NULL_HANDLE;}
        if(layout) DestroyPipelineLayout(device,layout,nullptr);
        if(descriptorLayout) DestroyDescriptorSetLayout(device,descriptorLayout,nullptr);
        if(sampler) DestroySampler(device,sampler,nullptr);
        if(pass) DestroyRenderPass(device,pass,nullptr);
        layout=VK_NULL_HANDLE;descriptorLayout=VK_NULL_HANDLE;sampler=VK_NULL_HANDLE;pass=VK_NULL_HANDLE;
    }
    VkImageView imageView(VkImage image,VkFormat format,uint32_t layer) {
        VkImageViewCreateInfo info{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        info.image=image;info.viewType=VK_IMAGE_VIEW_TYPE_2D;info.format=format;
        info.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,layer,1};
        VkImageView view=VK_NULL_HANDLE;check(CreateImageView(device,&info,nullptr,&view),"create layer view");return view;
    }
    void initialize() {
        VkAttachmentDescription attachment{};
        attachment.format=targetFormat;attachment.samples=VK_SAMPLE_COUNT_1_BIT;
        attachment.loadOp=VK_ATTACHMENT_LOAD_OP_LOAD;attachment.storeOp=VK_ATTACHMENT_STORE_OP_STORE;
        attachment.stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE;attachment.stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE;
        attachment.initialLayout=attachment.finalLayout=colorLayout ?
            VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL : VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        VkAttachmentReference color{0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
        VkSubpassDescription subpass{};subpass.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS;
        subpass.colorAttachmentCount=1;subpass.pColorAttachments=&color;
        VkSubpassDependency dependencies[2]{};
        dependencies[0].srcSubpass=VK_SUBPASS_EXTERNAL;dependencies[0].dstSubpass=0;
        dependencies[0].srcStageMask=colorLayout ? VK_PIPELINE_STAGE_ALL_COMMANDS_BIT : VK_PIPELINE_STAGE_TRANSFER_BIT;
        dependencies[0].dstStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        dependencies[0].srcAccessMask=colorLayout ? VK_ACCESS_MEMORY_WRITE_BIT : VK_ACCESS_TRANSFER_WRITE_BIT;
        dependencies[0].dstAccessMask=VK_ACCESS_COLOR_ATTACHMENT_READ_BIT|VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        dependencies[1].srcSubpass=0;dependencies[1].dstSubpass=VK_SUBPASS_EXTERNAL;
        dependencies[1].srcStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        dependencies[1].dstStageMask=colorLayout ? VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT : VK_PIPELINE_STAGE_TRANSFER_BIT;
        dependencies[1].srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
        dependencies[1].dstAccessMask=colorLayout ? 0 : VK_ACCESS_TRANSFER_READ_BIT|VK_ACCESS_TRANSFER_WRITE_BIT;
        VkRenderPassCreateInfo render{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
        render.attachmentCount=1;render.pAttachments=&attachment;render.subpassCount=1;render.pSubpasses=&subpass;
        render.dependencyCount=2;render.pDependencies=dependencies;
        check(CreateRenderPass(device,&render,nullptr,&pass),"create quad render pass");
        VkSamplerCreateInfo sampling{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
        sampling.minFilter=sampling.magFilter=VK_FILTER_LINEAR;sampling.mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST;
        sampling.addressModeU=sampling.addressModeV=sampling.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
        check(CreateSampler(device,&sampling,nullptr,&sampler),"create quad sampler");
        VkDescriptorSetLayoutBinding binding{0,VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,1,VK_SHADER_STAGE_FRAGMENT_BIT,nullptr};
        VkDescriptorSetLayoutCreateInfo descriptors{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        descriptors.bindingCount=1;descriptors.pBindings=&binding;
        check(CreateDescriptorSetLayout(device,&descriptors,nullptr,&descriptorLayout),"create quad descriptor layout");
        VkPushConstantRange constants{VK_SHADER_STAGE_VERTEX_BIT,0,sizeof(QuadVertices)};
        VkPipelineLayoutCreateInfo pipelineLayout{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
        pipelineLayout.setLayoutCount=1;pipelineLayout.pSetLayouts=&descriptorLayout;
        pipelineLayout.pushConstantRangeCount=1;pipelineLayout.pPushConstantRanges=&constants;
        check(CreatePipelineLayout(device,&pipelineLayout,nullptr,&layout),"create quad pipeline layout");
        VkShaderModule vs=VK_NULL_HANDLE,fs=VK_NULL_HANDLE;
        try {
            VkShaderModuleCreateInfo module{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
            module.codeSize=sizeof(vertexCode);module.pCode=vertexCode;
            check(CreateShaderModule(device,&module,nullptr,&vs),"create quad vertex shader");
            module.codeSize=sizeof(fragmentCode);module.pCode=fragmentCode;
            check(CreateShaderModule(device,&module,nullptr,&fs),"create quad fragment shader");
            VkPipelineShaderStageCreateInfo stages[2]{};
            for(auto& stage:stages) {stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;stage.pName="main";}
            stages[0].stage=VK_SHADER_STAGE_VERTEX_BIT;stages[0].module=vs;
            stages[1].stage=VK_SHADER_STAGE_FRAGMENT_BIT;stages[1].module=fs;
            VkPipelineVertexInputStateCreateInfo vertex{VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
            VkPipelineInputAssemblyStateCreateInfo assembly{VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
            assembly.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
            VkPipelineViewportStateCreateInfo viewport{VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
            viewport.viewportCount=viewport.scissorCount=1;
            VkPipelineRasterizationStateCreateInfo raster{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
            raster.polygonMode=VK_POLYGON_MODE_FILL;raster.cullMode=VK_CULL_MODE_NONE;raster.lineWidth=1;
            VkPipelineMultisampleStateCreateInfo samples{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
            samples.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
            VkPipelineColorBlendAttachmentState blend{};
            blend.colorWriteMask=VK_COLOR_COMPONENT_R_BIT|VK_COLOR_COMPONENT_G_BIT|VK_COLOR_COMPONENT_B_BIT|VK_COLOR_COMPONENT_A_BIT;
            blend.dstColorBlendFactor=blend.dstAlphaBlendFactor=VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
            blend.srcAlphaBlendFactor=VK_BLEND_FACTOR_ONE;
            VkPipelineColorBlendStateCreateInfo blending{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
            blending.attachmentCount=1;blending.pAttachments=&blend;
            VkDynamicState dynamicStates[]={VK_DYNAMIC_STATE_VIEWPORT,VK_DYNAMIC_STATE_SCISSOR};
            VkPipelineDynamicStateCreateInfo dynamic{VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO};
            dynamic.dynamicStateCount=2;dynamic.pDynamicStates=dynamicStates;
            VkGraphicsPipelineCreateInfo pipeline{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
            pipeline.stageCount=2;pipeline.pStages=stages;pipeline.pVertexInputState=&vertex;
            pipeline.pInputAssemblyState=&assembly;pipeline.pViewportState=&viewport;
            pipeline.pRasterizationState=&raster;pipeline.pMultisampleState=&samples;
            pipeline.pColorBlendState=&blending;pipeline.pDynamicState=&dynamic;pipeline.layout=layout;pipeline.renderPass=pass;
            for(unsigned mode=0;mode<3;mode++) {
                blend.blendEnable=mode!=0;
                blend.srcColorBlendFactor=mode==2 ? VK_BLEND_FACTOR_SRC_ALPHA : VK_BLEND_FACTOR_ONE;
                check(CreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&pipeline,nullptr,&pipelines[mode]),"create quad pipeline");
            }
        } catch(...) {if(vs) DestroyShaderModule(device,vs,nullptr);if(fs) DestroyShaderModule(device,fs,nullptr);throw;}
        DestroyShaderModule(device,vs,nullptr);DestroyShaderModule(device,fs,nullptr);
    }
    Frame& prepare(VkImage target,VkExtent2D extent) {
        auto& frame=frames[target];
        if(frame.framebuffer && (extent.width!=frame.extent.width||extent.height!=frame.extent.height)) clear(frame);
        if(!frame.framebuffer) {
            try {
            frame.extent=extent;frame.targetView=imageView(target,targetFormat,0);
            VkFramebufferCreateInfo fb{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
            fb.renderPass=pass;fb.attachmentCount=1;fb.pAttachments=&frame.targetView;
            fb.width=extent.width;fb.height=extent.height;fb.layers=1;
            check(CreateFramebuffer(device,&fb,nullptr,&frame.framebuffer),"create stereo framebuffer");
            VkDescriptorPoolSize size{VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,64};
            VkDescriptorPoolCreateInfo pool{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
            pool.maxSets=64;pool.poolSizeCount=1;pool.pPoolSizes=&size;
            check(CreateDescriptorPool(device,&pool,nullptr,&frame.pool),"create quad descriptor pool");
            } catch(...) {clear(frame);throw;}
        } else {
            for(auto image:frame.sources) DestroyImageView(device,image,nullptr);
            frame.sources.clear();check(ResetDescriptorPool(device,frame.pool,0),"reset quad descriptors");
        }
        return frame;
    }
};

QuadComposer::QuadComposer(VkDevice device,PFN_vkGetDeviceProcAddr resolve,VkFormat format,bool colorLayout)
    :state_(std::make_unique<State>(device,resolve,format,colorLayout)) {}
QuadComposer::~QuadComposer()=default;
void QuadComposer::reset() {state_->reset();}
void QuadComposer::record(VkCommandBuffer command,VkImage target,VkExtent2D extent,const std::vector<QuadDraw>& draws,
                          const uint32_t* frameId,const std::array<uint32_t,5>* bootstrap,bool markerOnly) {
    if(bootstrap&&(!frameId||extent.width<576)) throw std::invalid_argument("Invalid image identity extent/pose");
    if(draws.empty()&&!frameId) return;
    if(!command||!target||!extent.width||!extent.height||draws.size()>64)
        throw std::invalid_argument("Invalid quad target/count");
    if(frameId&&(extent.width<96||extent.height<2)) throw std::invalid_argument("Invalid frame marker extent");
    for(const auto& draw:draws) {
        auto v=draw.viewport;
        if(!draw.image||draw.image==target||draw.format==VK_FORMAT_UNDEFINED||draw.blend>2||
           v.offset.x<0||v.offset.y<0||!v.extent.width||!v.extent.height||
           uint64_t(v.offset.x)+v.extent.width>extent.width||uint64_t(v.offset.y)+v.extent.height>extent.height)
            throw std::invalid_argument("Invalid quad draw");
    }
    auto& s=*state_;auto& frame=s.prepare(target,extent);
    std::vector<VkImageMemoryBarrier> barriers;
    for(const auto& draw:draws) {
        if(std::any_of(barriers.begin(),barriers.end(),[&](const auto& b) {
            return b.image==draw.image && b.subresourceRange.baseArrayLayer==draw.arrayLayer;
        })) continue;
        VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
        barrier.srcAccessMask=VK_ACCESS_MEMORY_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_SHADER_READ_BIT;
        barrier.oldLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;barrier.newLayout=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        barrier.srcQueueFamilyIndex=barrier.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
        barrier.image=draw.image;barrier.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,draw.arrayLayer,1};
        barriers.push_back(barrier);
    }
    // Prepare descriptors before recording; allocation failures must not leave an open render pass.
    std::vector<VkDescriptorSet> sets;
    for(const auto& draw:draws) {
        frame.sources.push_back(s.imageView(draw.image,draw.format,draw.arrayLayer));
        VkDescriptorSetAllocateInfo allocation{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
        allocation.descriptorPool=frame.pool;allocation.descriptorSetCount=1;allocation.pSetLayouts=&s.descriptorLayout;
        VkDescriptorSet set=VK_NULL_HANDLE;check(s.AllocateDescriptorSets(s.device,&allocation,&set),"allocate quad descriptor");
        VkDescriptorImageInfo image{s.sampler,frame.sources.back(),VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
        VkWriteDescriptorSet write{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        write.dstSet=set;write.descriptorCount=1;write.descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;write.pImageInfo=&image;
        s.UpdateDescriptorSets(s.device,1,&write,0,nullptr);sets.push_back(set);
    }
    s.CmdPipelineBarrier(command,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,0,
        0,nullptr,0,nullptr,static_cast<uint32_t>(barriers.size()),barriers.data());
    VkRenderPassBeginInfo begin{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    begin.renderPass=s.pass;begin.framebuffer=frame.framebuffer;begin.renderArea.extent=extent;
    if(markerOnly&&draws.empty()&&frameId)
        begin.renderArea={{0,int32_t(extent.height-1)},{extent.width,1}};
    s.CmdBeginRenderPass(command,&begin,VK_SUBPASS_CONTENTS_INLINE);
    for(size_t i=0;i<draws.size();i++) {
        const auto& draw=draws[i];auto r=draw.viewport;
        VkViewport viewport{float(r.offset.x),float(r.offset.y),float(r.extent.width),float(r.extent.height),0,1};
        s.CmdSetViewport(command,0,1,&viewport);s.CmdSetScissor(command,0,1,&r);
        s.CmdBindPipeline(command,VK_PIPELINE_BIND_POINT_GRAPHICS,s.pipelines[draw.blend]);
        s.CmdBindDescriptorSets(command,VK_PIPELINE_BIND_POINT_GRAPHICS,s.layout,0,1,&sets[i],0,nullptr);
        s.CmdPushConstants(command,s.layout,VK_SHADER_STAGE_VERTEX_BIT,0,sizeof(draw.vertices),&draw.vertices);
        s.CmdDraw(command,6,1,0,0);
    }
    if(frameId) {
        // Dedicated last row, outside both eye viewports. Commands carry their
        // own values, so no CPU staging buffer can be overwritten in flight.
        std::array<uint32_t,18> words{};
        const uint32_t blocks=bootstrap ? 6u : 1u;
        for(uint32_t block=0;block<blocks;block++) {
            uint32_t value=block==0 ? *frameId : (*bootstrap)[block-1];
            words[block*3]=0x47583346u;words[block*3+1]=value;words[block*3+2]=~value;
        }
        VkClearAttachment clear{};clear.aspectMask=VK_IMAGE_ASPECT_COLOR_BIT;
        clear.clearValue.color={{0.f,0.f,0.f,1.f}};
        const VkClearRect row{{{0,static_cast<int32_t>(extent.height-1)},{blocks*96,1}},0,1};
        s.CmdClearAttachments(command,1,&clear,1,&row);
        // Batch all white cells into one call. Avoid 96 translated Vulkan
        // requests per frame while preserving the exact ID/check pixels.
        std::array<VkClearRect,576> white{};
        uint32_t count=0;
        for(uint32_t bit=0;bit<blocks*96;bit++) {
            if(words[bit/32]&(1u<<(bit%32)))
                white[count++]={{{static_cast<int32_t>(bit),static_cast<int32_t>(extent.height-1)},{1,1}},0,1};
        }
        clear.clearValue.color={{1.f,1.f,1.f,1.f}};
        if(count) s.CmdClearAttachments(command,1,&clear,count,white.data());
    }
    s.CmdEndRenderPass(command);
    for(auto& barrier:barriers) {
        barrier.srcAccessMask=VK_ACCESS_SHADER_READ_BIT;barrier.dstAccessMask=VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT;
        std::swap(barrier.oldLayout,barrier.newLayout);
    }
    s.CmdPipelineBarrier(command,VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,
        0,nullptr,0,nullptr,static_cast<uint32_t>(barriers.size()),barriers.data());
}
}
