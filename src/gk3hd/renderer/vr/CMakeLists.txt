cmake_minimum_required(VERSION 3.24)
project(gk3hd_xr LANGUAGES C CXX)
# Match the renderer's static CRT, including the statically linked XR loader.
if(MSVC)
  set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
include(FetchContent)
include(CTest)

if(WIN32 AND NOT CMAKE_SIZEOF_VOID_P EQUAL 4)
  message(FATAL_ERROR "GK3 requires an x86 build. Configure Visual Studio with -A Win32.")
endif()

# Downloaded dependencies stay in the chosen build tree, never in the repo.
set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_CONFORMANCE_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_SDK_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_API_LAYERS OFF CACHE BOOL "" FORCE)
set(DYNAMIC_LOADER OFF CACHE BOOL "" FORCE)
FetchContent_Declare(openxr
  GIT_REPOSITORY https://github.com/KhronosGroup/OpenXR-SDK.git
  GIT_TAG release-1.1.63
  GIT_SHALLOW TRUE
  GIT_SUBMODULES ""
)
FetchContent_Declare(vulkan_headers
  GIT_REPOSITORY https://github.com/KhronosGroup/Vulkan-Headers.git
  GIT_TAG afe9eb980aa928a66d1c9c06f38c55dd59868720
  GIT_SUBMODULES ""
)
FetchContent_MakeAvailable(openxr vulkan_headers)
find_package(Git REQUIRED)
execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${openxr_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE openxr_commit OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT openxr_commit STREQUAL "f2448a8797c85814aa892efc1ab8707900fbcc78")
  message(FATAL_ERROR "OpenXR SDK release tag no longer matches the pinned commit.")
endif()
if(MSVC)
  # Upstream defaults static loader libraries to /MD. Our containing renderer
  # uses /MT, so override the target property rather than patch vendor sources.
  set_property(TARGET openxr_loader PROPERTY MSVC_RUNTIME_LIBRARY
               "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

add_library(gk3hd_xr STATIC runtime.cpp input.cpp panel.cpp keyboard.cpp engine_camera.cpp renderer_host.cpp scene.cpp)
target_compile_features(gk3hd_xr PUBLIC cxx_std_17)
target_include_directories(gk3hd_xr PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(gk3hd_xr PUBLIC openxr_loader Vulkan::Headers)
if(WIN32)
  target_link_libraries(gk3hd_xr PUBLIC gdi32 user32)
endif()
if(MSVC)
  target_compile_options(gk3hd_xr PRIVATE /W4 /WX /EHsc)
endif()

add_executable(gk3hd-xr-probe probe.cpp)
target_link_libraries(gk3hd-xr-probe PRIVATE gk3hd_xr)
add_executable(gk3hd-xr-tests tests.cpp)
target_link_libraries(gk3hd-xr-tests PRIVATE gk3hd_xr)
add_executable(gk3hd-engine-camera-probe engine_camera_probe.cpp)
target_link_libraries(gk3hd-engine-camera-probe PRIVATE gk3hd_xr)
add_test(NAME xr_lifecycle COMMAND gk3hd-xr-tests)
add_executable(gk3hd-xr-scene-tests scene_tests.cpp)
target_link_libraries(gk3hd-xr-scene-tests PRIVATE gk3hd_xr)
if(MSVC)
  target_compile_options(gk3hd-xr-scene-tests PRIVATE /W4 /WX /EHsc)
endif()
add_test(NAME xr_scene COMMAND gk3hd-xr-scene-tests)
add_executable(gk3hd-xr-input-tests input_tests.cpp)
target_link_libraries(gk3hd-xr-input-tests PRIVATE gk3hd_xr)
if(MSVC)
  target_compile_options(gk3hd-xr-input-tests PRIVATE /W4 /WX /EHsc)
endif()
add_test(NAME xr_input COMMAND gk3hd-xr-input-tests)
add_executable(gk3hd-xr-panel-tests panel_tests.cpp)
target_link_libraries(gk3hd-xr-panel-tests PRIVATE gk3hd_xr)
if(MSVC)
  target_compile_options(gk3hd-xr-panel-tests PRIVATE /W4 /WX /EHsc)
endif()
add_test(NAME xr_panel COMMAND gk3hd-xr-panel-tests)
add_executable(gk3hd-xr-keyboard-tests keyboard_tests.cpp)
target_link_libraries(gk3hd-xr-keyboard-tests PRIVATE gk3hd_xr)
if(MSVC)
  target_compile_options(gk3hd-xr-keyboard-tests PRIVATE /W4 /WX /EHsc)
endif()
add_test(NAME xr_keyboard COMMAND gk3hd-xr-keyboard-tests)
add_executable(gk3hd-xr-input-probe input_probe.cpp)
target_link_libraries(gk3hd-xr-input-probe PRIVATE gk3hd_xr)
if(MSVC)
  target_compile_options(gk3hd-xr-input-probe PRIVATE /W4 /WX /EHsc)
endif()

if(WIN32)
  add_executable(gk3hd-xr-test-feed-tests test_input_feed_tests.cpp)
  target_compile_features(gk3hd-xr-test-feed-tests PRIVATE cxx_std_17)
  target_compile_options(gk3hd-xr-test-feed-tests PRIVATE /W4 /WX /EHsc)
  target_include_directories(gk3hd-xr-test-feed-tests PRIVATE "${openxr_SOURCE_DIR}/include")
  add_test(NAME xr_test_feed COMMAND gk3hd-xr-test-feed-tests)
  add_executable(gk3hd-xr-transport-tests transport_tests.cpp)
  target_compile_features(gk3hd-xr-transport-tests PRIVATE cxx_std_17)
  target_compile_options(gk3hd-xr-transport-tests PRIVATE /W4 /WX /EHsc)
  target_include_directories(gk3hd-xr-transport-tests PRIVATE "${openxr_SOURCE_DIR}/include")
  target_link_libraries(gk3hd-xr-transport-tests PRIVATE Vulkan::Headers dxguid user32)
  # This fixture is built only for development. Its synthetic poses are not a
  # headset, but its Vulkan images exercise the actual renderer bootstrap.
  add_library(gk3hd-xr-gpu-runtime SHARED gpu_test_runtime.cpp)
  target_link_libraries(gk3hd-xr-gpu-runtime PRIVATE Vulkan::Headers)
  target_include_directories(gk3hd-xr-gpu-runtime PRIVATE "${openxr_SOURCE_DIR}/include")
  target_compile_features(gk3hd-xr-gpu-runtime PRIVATE cxx_std_17)
  target_compile_options(gk3hd-xr-gpu-runtime PRIVATE /W4 /WX /EHsc)
  target_link_options(gk3hd-xr-gpu-runtime PRIVATE
    /EXPORT:xrNegotiateLoaderRuntimeInterface=_xrNegotiateLoaderRuntimeInterface@8
    /EXPORT:Gk3hdXrTestPixels=_Gk3hdXrTestPixels@12
    /EXPORT:Gk3hdXrTestPanel=_Gk3hdXrTestPanel@12
    /EXPORT:Gk3hdXrTestKeyboard=_Gk3hdXrTestKeyboard@12
    /EXPORT:Gk3hdXrTestSubtitle=_Gk3hdXrTestSubtitle@12
    /EXPORT:Gk3hdXrTestAim=_Gk3hdXrTestAim@16
    /EXPORT:Gk3hdXrTestInput=_Gk3hdXrTestInput@20
    /EXPORT:Gk3hdXrTestFrameStats=_Gk3hdXrTestFrameStats@8
    /EXPORT:Gk3hdXrTestMainWaits=_Gk3hdXrTestMainWaits@0)
  file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/$<CONFIG>/gpu-runtime.json"
    CONTENT "{\"file_format_version\":\"1.0.0\",\"runtime\":{\"library_path\":\"./gk3hd-xr-gpu-runtime.dll\"}}\n")
endif()

# The renderer consumes this small, self-contained staging tree. No guessed
# dependency build paths or locally installed OpenXR SDK are needed.
install(TARGETS gk3hd_xr openxr_loader ARCHIVE DESTINATION lib COMPONENT Renderer)
install(FILES runtime.h renderer_host.h frame_bridge.h frame_scheduler.h loading_frames.h scene.h camera_transition.h wall_visibility.h engine_camera.h camera.h input.h input_bridge.h panel.h panel_bridge.h keyboard.h overlay.h overlay_pixels.h mirror_pacer.h
        DESTINATION . COMPONENT Renderer)
install(DIRECTORY "${openxr_SOURCE_DIR}/include/openxr"
        DESTINATION include COMPONENT Renderer)
install(FILES "${openxr_SOURCE_DIR}/LICENSE" DESTINATION notices
        RENAME OpenXR.txt COMPONENT Renderer)
install(FILES "${openxr_SOURCE_DIR}/src/external/jsoncpp/LICENSE"
        DESTINATION notices RENAME JsonCpp.txt COMPONENT Renderer)
