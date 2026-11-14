#include "frame_metadata_publisher.h"
#include <filesystem>
#include <iostream>
#include <stdexcept>

using namespace gk3hd::frame_metadata;
static unsigned checks;
static void require(bool value) {checks++;if(!value)throw std::runtime_error("Frame publisher contract failed");}
struct Reader {
    HANDLE file=INVALID_HANDLE_VALUE,mapping=nullptr;
    const uint8_t* data=nullptr;
    explicit Reader(const std::wstring& path) {
        file=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,
            OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        require(file!=INVALID_HANDLE_VALUE);
        LARGE_INTEGER size{};require(GetFileSizeEx(file,&size)&&size.QuadPart==1024);
        mapping=CreateFileMappingW(file,nullptr,PAGE_READONLY,0,0,nullptr);require(mapping!=nullptr);
        data=static_cast<const uint8_t*>(MapViewOfFile(mapping,FILE_MAP_READ,0,0,1024));require(data!=nullptr);
    }
    ~Reader() {if(data)UnmapViewOfFile(data);if(mapping)CloseHandle(mapping);if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);}
    uint32_t value(unsigned index) const {return word(data,index*4);}
    Snapshot snapshot(uint32_t expected) const {
        require(value(0)==0x324d5047u&&value(1)==1&&value(2)==1024&&value(3)==320&&value(4)==expected);
        for(unsigned i=5;i<16;i++)require(value(i)==0);
        for(unsigned i=176;i<256;i++)require(value(i)==0);
        auto result=decode(data+(16+(expected&1u)*80)*4,320);require(result.has_value());return *result;
    }
};
int wmain(int argc,wchar_t** argv) {
    try {
        require(argc==2);std::filesystem::path directory(argv[1]);
        std::filesystem::create_directories(directory);
        SetEnvironmentVariableA("GK3HD_FRAME_SESSION",nullptr);
        Publisher absent(directory.c_str());require(!absent.active());
        SetEnvironmentVariableA("GK3HD_FRAME_SESSION","not-a-session");
        Publisher malformed(directory.c_str());require(!malformed.active());
        const char* token="0123456789abcdef0123456789abcdef";
        SetEnvironmentVariableA("GK3HD_FRAME_SESSION",token);
        std::wstring owned;
        {
            Publisher publisher(directory.c_str());require(publisher.active());owned=publisher.destination();
            require(!publisher.begin(0,640,64,2,0,1));
            require(!publisher.begin(1,640,64,2,2,1));
            require(publisher.begin(1,640,64,2,0,0x80000001u).has_value());
            Reader reader(owned);require(reader.value(4)==0);
            require(publisher.commitSubmitted());auto first=reader.snapshot(1);
            require(first.latest==1&&first.images[0].pose==0x80000001u);
            Publisher collision(directory.c_str());require(!collision.active());
            require(publisher.begin(1,640,64,2,1,0xffffffffu,9).has_value());
            require(publisher.commitSubmitted());auto second=reader.snapshot(2);
            require(second.epoch==first.epoch&&second.images[1].pose==0xffffffffu&&
                second.images[1].movie==9&&second.images[0].movie==0);
            require(publisher.begin(1,640,64,2,0,42).has_value());publisher.cancel();
            require(!publisher.commitSubmitted());require(reader.snapshot(2).latest==2);
            require(publisher.begin(1,640,64,2,0,43).has_value());require(publisher.commitSubmitted());
            auto cancelled=reader.snapshot(3);require(cancelled.latest==1&&cancelled.epoch!=first.epoch);
            require(publisher.begin(2,768,64,3,2,44).has_value());require(publisher.commitSubmitted());
            auto resized=reader.snapshot(4);require(resized.width==768&&resized.count==3&&resized.epoch!=cancelled.epoch);
            {
                Publisher::PendingGuard guard{publisher};
                require(publisher.begin(2,768,64,3,1,45).has_value());
            }
            require(!publisher.commitSubmitted());require(reader.snapshot(4).latest==1);
            // A scope ending after successful submission must keep its epoch.
            {
                Publisher::PendingGuard guard{publisher};
                require(publisher.begin(2,768,64,3,0,46).has_value());require(publisher.commitSubmitted());
            }
            auto restart=reader.snapshot(5);require(restart.epoch!=resized.epoch);
            require(publisher.begin(2,768,64,3,1,47).has_value());require(publisher.commitSubmitted());
            require(reader.snapshot(6).epoch==restart.epoch);
        }
        require(!std::filesystem::exists(owned));
        SetEnvironmentVariableA("GK3HD_FRAME_SESSION",nullptr);
        std::cout<<checks<<" Win32 mapped publication, submission/cancel, epochs, collision and cleanup checks passed\n";
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<" after "<<checks<<" checks\n";return 1;}
}
