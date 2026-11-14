#pragma once

// Isolated synthetic projection+quad fixture. Its eye poses are test geometry,
// never sent to the game or advertised as real HMD tracking. The Android side
// checks actual output pixels after the complete Vulkan/X-server/GLES path.
void stereoTransportTests(const char* path,unsigned cycles=1) {
    require(cycles==1||cycles==4,"Unsupported bounded lifecycle fixture");
    std::ofstream lifecycle;
    if(cycles>1) {
        char token[33]{};
        require(GetEnvironmentVariableA("GK3HD_TRANSPORT_TOKEN",token,sizeof(token))==32,"Missing fixture token");
        lifecycle.open("transport-lifecycle.log",std::ios::trunc);
        require(bool(lifecycle),"Cannot create bounded lifecycle report");
        lifecycle<<"token="<<token<<std::endl;
    }
    for(unsigned cycle=0;cycle<cycles;cycle++) {
    std::cout<<"Stereo lifecycle begin "<<cycle<<'/'<<cycles<<std::endl;
    if(cycles>1) lifecycle<<"begin="<<cycle<<std::endl;
    Gpu gpu(true);InputRuntime xr(path);XrSpace origin=xr.startSession(gpu);
    XrSystemGetInfo systemInfo{XR_TYPE_SYSTEM_GET_INFO};systemInfo.formFactor=XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    XrSystemId system=0;InputRuntime::result(xr.function<PFN_xrGetSystem>("xrGetSystem")(xr.instance,&systemInfo,&system),"Get stereo system failed");
    XrViewConfigurationView configuration[2]={{XR_TYPE_VIEW_CONFIGURATION_VIEW},{XR_TYPE_VIEW_CONFIGURATION_VIEW}};
    uint32_t count=0;
    InputRuntime::result(xr.function<PFN_xrEnumerateViewConfigurationViews>("xrEnumerateViewConfigurationViews")
        (xr.instance,system,XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO,2,&count,configuration),"Get stereo size failed");
    require(count==2,"Stereo fixture requires two views");
    uint32_t width=configuration[0].recommendedImageRectWidth,height=configuration[0].recommendedImageRectHeight;
    require(width>0&&height>0&&width<=4096&&height<=4096,"Invalid fixture eye extent");
    auto create=xr.function<PFN_xrCreateSwapchain>("xrCreateSwapchain");
    auto enumerate=xr.function<PFN_xrEnumerateSwapchainImages>("xrEnumerateSwapchainImages");
    auto acquire=xr.function<PFN_xrAcquireSwapchainImage>("xrAcquireSwapchainImage");
    auto waitImage=xr.function<PFN_xrWaitSwapchainImage>("xrWaitSwapchainImage");
    auto release=xr.function<PFN_xrReleaseSwapchainImage>("xrReleaseSwapchainImage");
    XrSwapchain chains[3]{};std::vector<XrSwapchainImageVulkanKHR> images[3];
    for(int eye=0;eye<3;eye++) {
        XrSwapchainCreateInfo info{XR_TYPE_SWAPCHAIN_CREATE_INFO};
        info.usageFlags=XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT|XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT|XR_SWAPCHAIN_USAGE_TRANSFER_SRC_BIT;
        info.format=VK_FORMAT_B8G8R8A8_SRGB;info.sampleCount=1;info.width=eye<2 ? width : 64;info.height=eye<2 ? height : 64;
        info.faceCount=info.arraySize=info.mipCount=1;
        InputRuntime::result(create(xr.session,&info,&chains[eye]),"Create fixture images failed");
        count=0;InputRuntime::result(enumerate(chains[eye],0,&count,nullptr),"Count fixture images failed");
        images[eye].resize(count,{XR_TYPE_SWAPCHAIN_IMAGE_VULKAN_KHR});
        InputRuntime::result(enumerate(chains[eye],count,&count,reinterpret_cast<XrSwapchainImageBaseHeader*>(images[eye].data())),"Read fixture images failed");
    }
    auto wait=xr.function<PFN_xrWaitFrame>("xrWaitFrame");auto begin=xr.function<PFN_xrBeginFrame>("xrBeginFrame");auto end=xr.function<PFN_xrEndFrame>("xrEndFrame");
    for(unsigned frame=0;frame<(cycles==1 ? 120u : 48u);frame++) {
        XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};XrFrameState state{XR_TYPE_FRAME_STATE};
        InputRuntime::result(wait(xr.session,&wi,&state),"Stereo fixture wait failed");
        XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};InputRuntime::result(begin(xr.session,&bi),"Stereo fixture begin failed");
        uint32_t indices[3]{};gpu.begin();
        for(int eye=0;eye<3;eye++) {
            XrSwapchainImageAcquireInfo ai{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
            InputRuntime::result(acquire(chains[eye],&ai,&indices[eye]),"Acquire fixture eye failed");
            XrSwapchainImageWaitInfo waitInfo{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};waitInfo.timeout=1'000'000'000;
            InputRuntime::result(waitImage(chains[eye],&waitInfo),"Wait for fixture eye failed");
            VkImage image=images[eye].at(indices[eye]).image;
            gpu.barrier(image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
            VkClearColorValue color{};color.float32[eye]=.25f;color.float32[3]=1;
            const float phases[]={.125f,.25f,.5f,.75f};
            if(cycles>1&&eye==2) color.float32[2]=phases[cycle];
            VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
            gpu.CmdClearColorImage(gpu.command,image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&color,1,&range);
            if(cycles>1&&frame==0) {
                gpu.barrier(image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
                VkBufferImageCopy sample{};sample.bufferOffset=eye*4;sample.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};sample.imageExtent={1,1,1};
                gpu.CmdCopyImageToBuffer(gpu.command,image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,gpu.buffer,1,&sample);
                if(eye==0) {
                    gpu.barrier(gpu.target.image,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
                    VkImageBlit blit{};blit.srcSubresource=blit.dstSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};
                    blit.srcOffsets[1]=blit.dstOffsets[1]={1,1,1};
                    gpu.CmdBlitImage(gpu.command,image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,gpu.target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,1,&blit,VK_FILTER_LINEAR);
                    gpu.barrier(gpu.target.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
                    sample.bufferOffset=12;
                    gpu.CmdCopyImageToBuffer(gpu.command,gpu.target.image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,gpu.buffer,1,&sample);
                }
                gpu.barrier(image,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
            } else gpu.barrier(image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL);
        }
        gpu.submit();
        if(cycles>1&&frame==0) {
            void* sample=nullptr;ok(gpu.MapMemory(gpu.device,gpu.bufferMemory,0,16,0,&sample));
            const auto* bytes=static_cast<const unsigned char*>(sample);
            for(unsigned eye=0;eye<3;eye++) lifecycle<<"input-bgra="<<cycle<<','<<eye<<':'<<int(bytes[eye*4])<<','<<int(bytes[eye*4+1])<<','<<int(bytes[eye*4+2])<<','<<int(bytes[eye*4+3])<<std::endl;
            lifecycle<<"offscreen-blit-bgra="<<cycle<<':'<<int(bytes[12])<<','<<int(bytes[13])<<','<<int(bytes[14])<<','<<int(bytes[15])<<std::endl;
            gpu.UnmapMemory(gpu.device,gpu.bufferMemory);
        }
        for(int eye=0;eye<3;eye++) {
            XrSwapchainImageReleaseInfo ri{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
            InputRuntime::result(release(chains[eye],&ri),"Release fixture eye failed");
        }
        XrCompositionLayerProjectionView views[2]={{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW},{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW}};
        for(int eye=0;eye<2;eye++) {
            views[eye].pose.orientation.w=1;views[eye].pose.position.x=eye==0 ? -.032f : .032f;
            views[eye].fov={-.785398163f,.785398163f,.785398163f,-.785398163f};
            views[eye].subImage={chains[eye],{{0,0},{static_cast<int32_t>(width),static_cast<int32_t>(height)}},0};
        }
        XrCompositionLayerProjection projection{XR_TYPE_COMPOSITION_LAYER_PROJECTION};projection.space=origin;projection.viewCount=2;projection.views=views;
        XrCompositionLayerQuad quad{XR_TYPE_COMPOSITION_LAYER_QUAD};quad.space=origin;quad.eyeVisibility=XR_EYE_VISIBILITY_BOTH;
        quad.subImage={chains[2],{{0,0},{64,64}},0};quad.pose.orientation.w=1;quad.pose.position.z=-1;quad.size={1,1};
        const XrCompositionLayerBaseHeader* layers[]={reinterpret_cast<XrCompositionLayerBaseHeader*>(&projection),reinterpret_cast<XrCompositionLayerBaseHeader*>(&quad)};
        XrFrameEndInfo ei{XR_TYPE_FRAME_END_INFO};ei.displayTime=state.predictedDisplayTime;ei.environmentBlendMode=XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        ei.layerCount=2;ei.layers=layers;InputRuntime::result(end(xr.session,&ei),"Submit stereo fixture failed");
        if(cycles>1) Sleep(16); // Bound producer rate so each phase can be independently sampled.
    }
    for(auto chain:chains) InputRuntime::result(xr.function<PFN_xrDestroySwapchain>("xrDestroySwapchain")(chain),"Destroy fixture eye failed");
    InputRuntime::result(xr.function<PFN_xrDestroySpace>("xrDestroySpace")(origin),"Destroy fixture origin failed");
    std::cout<<"Stereo lifecycle complete "<<cycle<<'/'<<cycles<<std::endl;
    if(cycles>1) lifecycle<<"complete="<<cycle<<std::endl;
    }
    std::cout<<"Stereo fixture lifecycle submitted "<<cycles<<" sessions; Android per-phase pixel verification is required, no game/head acceptance claimed\n";
    if(cycles>1) lifecycle<<"STEREO_LIFECYCLE_EXIT=0"<<std::endl;
}
