// Registration-free AV1/FLAC playback through the game's existing DirectDraw player.
// LAV's public COM settings interfaces are supplied by the pinned upstream archive.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <dshow.h>
#include <ddraw.h>
#include <amstream.h>
#include <ddstream.h>
#include <wrl/client.h>
#include <string>
#include "LAVVideoSettings.h"
#include "LAVAudioSettings.h"
#include "LAVSplitterSettings.h"

using Microsoft::WRL::ComPtr;
extern "C" IMAGE_DOS_HEADER __ImageBase;

static std::wstring directory() {
    wchar_t path[32768];
    DWORD count = GetModuleFileNameW(reinterpret_cast<HMODULE>(&__ImageBase), path, 32768);
    if (!count || count >= 32768) return L"";
    std::wstring result(path, count);
    return result.substr(0, result.find_last_of(L"\\/") + 1);
}

static HRESULT createFilter(const wchar_t* filename, const wchar_t* identifier, IBaseFilter** result) {
    // Keep codec modules loaded for the process lifetime. No COM registration,
    // user settings, system codecs or caller working directory are involved.
    const std::wstring path = directory() + filename;
    HMODULE module = GetModuleHandleW(path.c_str());
    if (!module) module = LoadLibraryExW(path.c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!module) return HRESULT_FROM_WIN32(GetLastError());
    auto getClass = reinterpret_cast<HRESULT (STDAPICALLTYPE*)(REFCLSID, REFIID, void**)>(
        GetProcAddress(module, "DllGetClassObject"));
    if (!getClass) return HRESULT_FROM_WIN32(GetLastError());
    CLSID clsid;
    HRESULT hr = CLSIDFromString(identifier, &clsid);
    ComPtr<IClassFactory> factory;
    if (SUCCEEDED(hr)) hr = getClass(clsid, IID_PPV_ARGS(&factory));
    if (SUCCEEDED(hr)) hr = factory->CreateInstance(nullptr, IID_PPV_ARGS(result));
    return hr;
}

static HRESULT freePin(IBaseFilter* filter, PIN_DIRECTION wanted, IPin** result) {
    ComPtr<IEnumPins> pins;
    HRESULT hr = filter->EnumPins(&pins);
    if (FAILED(hr)) return hr;
    ComPtr<IPin> pin;
    while (pins->Next(1, pin.ReleaseAndGetAddressOf(), nullptr) == S_OK) {
        PIN_DIRECTION actual;
        ComPtr<IPin> peer;
        if (SUCCEEDED(pin->QueryDirection(&actual)) && actual == wanted &&
            pin->ConnectedTo(&peer) == VFW_E_NOT_CONNECTED) {
            *result = pin.Detach();
            return S_OK;
        }
    }
    return VFW_E_NOT_FOUND;
}

static bool mediaType(IPin* pin, REFGUID wanted) {
    ComPtr<IEnumMediaTypes> types;
    if (FAILED(pin->EnumMediaTypes(&types))) return false;
    AM_MEDIA_TYPE* type = nullptr;
    while (types->Next(1, &type, nullptr) == S_OK) {
        bool found = type->majortype == wanted;
        if (type->cbFormat) CoTaskMemFree(type->pbFormat);
        if (type->pUnk) type->pUnk->Release();
        CoTaskMemFree(type);
        if (found) return true;
    }
    return false;
}

static HRESULT createVideo(IBaseFilter** result) {
    // LAV snapshots the converter's worker count in its constructor. Its PPL
    // RGB worker pool crashes intermittently under Proton/WoW64. Restrict only
    // that construction-time count, then restore FFmpeg's automatic count.
    // AV1 decoding still uses the explicit four threads configured below.
    HMODULE utility = LoadLibraryExW((directory() + L"avutil-lav-61.dll").c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!utility) return HRESULT_FROM_WIN32(GetLastError());
    auto forceCount = reinterpret_cast<void (__cdecl*)(int)>(
        GetProcAddress(utility, "av_cpu_force_count"));
    if (!forceCount) return HRESULT_FROM_WIN32(ERROR_PROC_NOT_FOUND);
    forceCount(1);
    HRESULT hr = createFilter(L"LAVVideo.ax", L"{EE30215D-164F-4A92-A4EB-9D4C13390F9F}", result);
    forceCount(-1);
    return hr;
}

static HRESULT connectVideo(IGraphBuilder* graph, IPin* output, IAMMultiMediaStream* stream) {
    // Use a heap-backed decoder sample, then the DirectDraw stream's sample.
    // Connecting LAV straight to Wine's single-surface allocator can deadlock
    // when the decoder retains an output sample. RGB32 -> RGB32 is a copy, not
    // another lossy colorspace conversion or an image-resizing operation.
    ComPtr<IBaseFilter> bridge;
    HRESULT hr = CoCreateInstance(CLSID_Colour, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&bridge));
    if (SUCCEEDED(hr)) hr = graph->AddFilter(bridge.Get(), L"GK3HD sample bridge");
    ComPtr<IPin> bridgeInput, bridgeOutput;
    if (SUCCEEDED(hr)) hr = freePin(bridge.Get(), PINDIR_INPUT, &bridgeInput);
    if (SUCCEEDED(hr)) hr = freePin(bridge.Get(), PINDIR_OUTPUT, &bridgeOutput);
    if (FAILED(hr)) return hr;
    ComPtr<IMediaStreamFilter> sink;
    hr = stream->GetFilter(&sink);
    ComPtr<IPin> input;
    if (SUCCEEDED(hr)) hr = freePin(sink.Get(), PINDIR_INPUT, &input);
    ComPtr<IEnumMediaTypes> types;
    if (SUCCEEDED(hr)) hr = output->EnumMediaTypes(&types);
    if (FAILED(hr)) return hr;
    AM_MEDIA_TYPE* type = nullptr;
    hr = VFW_E_CANNOT_CONNECT;
    while (types->Next(1, &type, nullptr) == S_OK) {
        if (type->majortype == MEDIATYPE_Video && type->subtype == MEDIASUBTYPE_RGB32 &&
            type->formattype == FORMAT_VideoInfo && type->cbFormat >= sizeof(VIDEOINFOHEADER)) {
            auto format = reinterpret_cast<VIDEOINFOHEADER*>(type->pbFormat);
            format->bmiHeader.biHeight = -abs(format->bmiHeader.biHeight);
            hr = graph->ConnectDirect(output, bridgeInput.Get(), type);
            if (SUCCEEDED(hr)) hr = graph->ConnectDirect(bridgeOutput.Get(), input.Get(), type);
        }
        if (type->cbFormat) CoTaskMemFree(type->pbFormat);
        if (type->pUnk) type->pUnk->Release();
        CoTaskMemFree(type);
        if (SUCCEEDED(hr)) break;
    }
    return hr;
}

extern "C" __declspec(dllexport) HRESULT WINAPI Gk3hdOpenMovie(
    IAMMultiMediaStream* stream, LPCWSTR filename, DWORD flags) {
    if (!stream || !filename) return E_POINTER;
    HANDLE input = CreateFileW(filename, GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL, nullptr);
    DWORD signature[3] = {}, count = 0;
    if (input != INVALID_HANDLE_VALUE) {
        ReadFile(input, signature, sizeof(signature), &count, nullptr);
        CloseHandle(input);
    }
    // Decode original RLE AVI files too: some Proton versions cannot connect
    // their system codec. No resizing/reencoding is involved. Native geometry,
    // color-key transparency and movie asset identity remain with the game.
    const bool matroska = count >= 4 && signature[0] == 0xa3df451a;
    const bool avi = count == sizeof(signature) && signature[0] == 0x46464952 && signature[2] == 0x20495641;
    if (!matroska && !avi)
        return stream->OpenFile(filename, flags);

    ComPtr<IGraphBuilder> graph;
    HRESULT hr = stream->GetFilterGraph(&graph);
    if (FAILED(hr) || !graph) return FAILED(hr) ? hr : E_UNEXPECTED;
    // Match the decoder's RGB32 directly, avoiding Wine's extra color converter.
    // In particular, an odd-width RGB565 surface has a different row pitch from
    // a padded DIB, which otherwise prevents the 41x51 fingerprint clips connecting.
    ComPtr<IMediaStream> primary;
    ComPtr<IDirectDrawMediaStream> drawing;
    hr = stream->GetMediaStream(MSPID_PrimaryVideo, &primary);
    if (SUCCEEDED(hr)) hr = primary.As(&drawing);
    DDSURFACEDESC format = {sizeof(format)};
    format.dwFlags = DDSD_PIXELFORMAT;
    format.ddpfPixelFormat.dwSize = sizeof(DDPIXELFORMAT);
    format.ddpfPixelFormat.dwFlags = DDPF_RGB;
    format.ddpfPixelFormat.dwRGBBitCount = 32;
    format.ddpfPixelFormat.dwRBitMask = 0xff0000;
    format.ddpfPixelFormat.dwGBitMask = 0x00ff00;
    format.ddpfPixelFormat.dwBBitMask = 0x0000ff;
    if (SUCCEEDED(hr)) hr = drawing->SetFormat(&format, nullptr);
    if (FAILED(hr)) return hr;
    ComPtr<IBaseFilter> source, video, audio;
    hr = createFilter(L"LAVSplitter.ax", L"{B98D13E7-55DB-4385-A33D-09FD1BA26338}", &source);
    if (FAILED(hr)) return hr;
    ComPtr<ILAVFSettings> splitterSettings;
    hr = source.As(&splitterSettings);
    if (SUCCEEDED(hr)) hr = splitterSettings->SetRuntimeConfig(TRUE);
    if (SUCCEEDED(hr)) hr = graph->AddFilter(source.Get(), L"GK3HD source");
    ComPtr<IFileSourceFilter> file;
    if (SUCCEEDED(hr)) hr = source.As(&file);
    if (SUCCEEDED(hr)) hr = file->Load(filename, nullptr);
    if (FAILED(hr)) return hr;

    hr = createVideo(&video);
    if (FAILED(hr)) return hr;
    ComPtr<ILAVVideoSettings> settings;
    hr = video.As(&settings);
    if (SUCCEEDED(hr)) hr = settings->SetRuntimeConfig(TRUE);
    if (SUCCEEDED(hr)) hr = settings->SetFormatConfiguration(Codec_MSRLE, TRUE);
    if (SUCCEEDED(hr)) hr = settings->SetHWAccel(HWAccel_None);
    if (SUCCEEDED(hr)) hr = settings->SetNumThreads(4);
    for (int pixel = 0; SUCCEEDED(hr) && pixel < LAVOutPixFmt_NB; ++pixel)
        hr = settings->SetPixelFormat(static_cast<LAVOutPixFmts>(pixel), pixel == LAVOutPixFmt_RGB32);
    if (SUCCEEDED(hr)) hr = settings->SetRGBOutputRange(2); // Full range, no gamma adjustment.
    if (SUCCEEDED(hr)) hr = graph->AddFilter(video.Get(), L"GK3HD AV1");
    if (FAILED(hr)) return hr;

    hr = createFilter(L"LAVAudio.ax", L"{E8E73B6B-4CB3-44A4-BE99-4F7BCB96E491}", &audio);
    if (FAILED(hr)) return hr;
    ComPtr<ILAVAudioSettings> audioSettings;
    hr = audio.As(&audioSettings);
    if (SUCCEEDED(hr)) hr = audioSettings->SetRuntimeConfig(TRUE);
    if (SUCCEEDED(hr)) hr = graph->AddFilter(audio.Get(), L"GK3HD FLAC");
    if (FAILED(hr)) return hr;

    ComPtr<IFilterGraph2> graph2;
    hr = graph.As(&graph2);
    if (FAILED(hr)) return hr;
    ComPtr<IEnumPins> pins;
    hr = source->EnumPins(&pins);
    if (FAILED(hr)) return hr;
    ComPtr<IPin> pin;
    bool videoConnected = false;
    while (pins->Next(1, pin.ReleaseAndGetAddressOf(), nullptr) == S_OK) {
        PIN_DIRECTION direction;
        if (FAILED(pin->QueryDirection(&direction)) || direction != PINDIR_OUTPUT) continue;
        const bool isVideo = mediaType(pin.Get(), MEDIATYPE_Video);
        const bool isAudio = mediaType(pin.Get(), MEDIATYPE_Audio);
        IBaseFilter* decoder = isVideo ? video.Get() : isAudio ? audio.Get() : nullptr;
        if (!decoder) continue;
        ComPtr<IPin> inputPin, decoded;
        hr = freePin(decoder, PINDIR_INPUT, &inputPin);
        if (SUCCEEDED(hr)) hr = graph->ConnectDirect(pin.Get(), inputPin.Get(), nullptr);
        if (SUCCEEDED(hr)) hr = freePin(decoder, PINDIR_OUTPUT, &decoded);
        if (SUCCEEDED(hr)) hr = isVideo ? connectVideo(graph.Get(), decoded.Get(), stream) :
            graph2->RenderEx(decoded.Get(), AM_RENDEREX_RENDERTOEXISTINGRENDERERS, nullptr);
        if (FAILED(hr)) return hr;
        videoConnected |= isVideo;
    }
    if (!videoConnected) return VFW_E_CANNOT_CONNECT;
    ComPtr<IMediaStreamFilter> sink;
    hr = stream->GetFilter(&sink);
    if (SUCCEEDED(hr)) hr = sink->SupportSeeking(TRUE);
    if (FAILED(hr)) return hr;

    // Wine's default graph clock can leave its first DirectDraw sample waiting
    // forever. A real reference clock keeps BOTH video and audio timed, unlike
    // disabling clock synchronization or running frames as fast as possible.
    ComPtr<IMediaFilter> timing;
    ComPtr<IReferenceClock> clock;
    hr = graph.As(&timing);
    if (SUCCEEDED(hr) && !(flags & AMMSF_NOCLOCK))
        hr = CoCreateInstance(CLSID_SystemClock, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&clock));
    if (SUCCEEDED(hr)) hr = timing->SetSyncSource(clock.Get());
    if (FAILED(hr)) return hr;
    return flags & AMMSF_RUN ? stream->SetState(STREAMSTATE_RUN) : S_OK;
}
