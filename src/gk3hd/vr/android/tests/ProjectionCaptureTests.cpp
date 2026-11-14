#include "../projection_capture.h"
#include <iostream>
#include <limits>

using namespace gk3hd::standalone;
static void require(bool value) {
    if (!value) throw std::runtime_error("Projection capture mismatch");
}
int main() {
    // Distinct eyes and a metadata row must not leak into a cropped eye.
    const std::vector<uint8_t> source{
        1,2,3,255, 4,5,6,255, 7,8,9,255, 10,11,12,255,
        13,14,15,255, 16,17,18,255, 19,20,21,255, 22,23,24,255,
        99,99,99,255, 99,99,99,255, 99,99,99,255, 99,99,99,255};
    require(projectionCaptureRgb(source,4,3,0,0,2,2,false) ==
        std::vector<uint8_t>({1,2,3,4,5,6,13,14,15,16,17,18}));
    require(projectionCaptureRgb(source,4,3,2,0,2,2,false) ==
        std::vector<uint8_t>({7,8,9,10,11,12,19,20,21,22,23,24}));
    require(projectionCaptureRgb(source,4,3,1,1,2,1,true) ==
        std::vector<uint8_t>({18,17,16,21,20,19}));
    require(projectionCaptureFits(4120,2061,2060,0,2060,2060));
    require(projectionCaptureFits(3360,1761,1680,0,1680,1760));
    require(projectionCaptureFits(2060,2060,0,0,2060,2060));
    for (auto r : std::vector<std::vector<int32_t>>{
        {-1,0,1,1}, {0,-1,1,1}, {0,0,0,1}, {0,0,1,-1},
        {3,0,2,1}, {0,2,1,2}, {1,0,std::numeric_limits<int32_t>::max(),1}}) {
        require(!projectionCaptureFits(4,3,r[0],r[1],r[2],r[3]));
        try {
            projectionCaptureRgb(source,4,3,r[0],r[1],r[2],r[3],false);
            throw std::runtime_error("Invalid region accepted");
        } catch (const std::invalid_argument&) {}
    }
    require(!projectionCaptureFits(65536,65536,0,0,1,1));
    require(!projectionCaptureFits(4096,4096,0,0,4096,4096));
    try {
        projectionCaptureRgb({},4,3,0,0,2,2,false);
        throw std::runtime_error("Missing pixels accepted");
    } catch (const std::invalid_argument&) {}
    std::cout << "Projection eye crops, channels, bounds and resource caps passed\n";
}
