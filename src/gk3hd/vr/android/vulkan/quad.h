#pragma once
#include <openxr/openxr.h>
#include <vulkan/vulkan.h>
#include <array>
#include <cstdint>
#include <memory>
#include <vector>

namespace gk3hd::standalone {
struct QuadVertices {
    float clip[4][4];
    float uv[4];
};
// Input poses share one OpenXR right-handed reference space. No tracking is
// invented here. The caller must supply valid, same-frame eye/layer poses.
QuadVertices projectQuad(const XrPosef& eye, const XrFovf& fov,
                         const XrPosef& quad, XrExtent2Df size,
                         XrRect2Di crop, uint32_t width, uint32_t height);

struct QuadDraw {
    VkImage image=VK_NULL_HANDLE;
    VkFormat format=VK_FORMAT_UNDEFINED;
    uint32_t arrayLayer=0;
    VkRect2D viewport{};
    QuadVertices vertices{};
    // 0 opaque, 1 premultiplied, 2 straight alpha, matching OpenXR layer flags.
    unsigned blend=0;
};

// Records GPU-only composition into a supplied sRGB stereo target. The caller
// owns queue synchronization: retire a target's prior submission before record,
// and all submissions before reset/destruction or destroying source images.
// Sources enter and leave COLOR_ATTACHMENT_OPTIMAL. The target uses
// TRANSFER_DST_OPTIMAL unless the caller keeps it as a color attachment.
class QuadComposer {
public:
    QuadComposer(VkDevice device, PFN_vkGetDeviceProcAddr resolve,
                 VkFormat targetFormat=VK_FORMAT_B8G8R8A8_SRGB, bool colorLayout=false);
    ~QuadComposer();
    QuadComposer(const QuadComposer&)=delete;
    QuadComposer& operator=(const QuadComposer&)=delete;
    void record(VkCommandBuffer command, VkImage target, VkExtent2D extent,
                const std::vector<QuadDraw>& draws, const uint32_t* frameId=nullptr,
                const std::array<uint32_t,5>* bootstrap=nullptr, bool markerOnly=false);
    void reset();
private:
    struct State;
    std::unique_ptr<State> state_;
};
}
