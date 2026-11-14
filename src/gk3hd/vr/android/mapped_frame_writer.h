#pragma once
#include "frame_metadata.h"
#include <windows.h>
#include <cstdint>
#include <string>
#include <cstring>

namespace gk3hd::frame_metadata {
class MappedWriter {
  HANDLE file_=INVALID_HANDLE_VALUE,mapping_=nullptr;
  volatile LONG* words_=nullptr;uint32_t sequence_=0;
  std::wstring ownedPath_;
public:
  MappedWriter()=default;
  MappedWriter(const MappedWriter&)=delete;MappedWriter& operator=(const MappedWriter&)=delete;
  ~MappedWriter(){if(words_)UnmapViewOfFile(const_cast<LONG*>(words_));if(mapping_)CloseHandle(mapping_);if(file_!=INVALID_HANDLE_VALUE)CloseHandle(file_);if(!ownedPath_.empty())DeleteFileW(ownedPath_.c_str());}
  bool claim(const std::wstring& path){
    static_assert(sizeof(LONG)==4&&Bytes==320,"Shared snapshot word size changed");
    if(file_!=INVALID_HANDLE_VALUE)return words_!=nullptr;
    if(!words_){
      file_=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
      if(file_==INVALID_HANDLE_VALUE)return false;
      ownedPath_=path;
      mapping_=CreateFileMappingW(file_,nullptr,PAGE_READWRITE,0,1024,nullptr);
      if(!mapping_)return false;
      words_=static_cast<volatile LONG*>(MapViewOfFile(mapping_,FILE_MAP_READ|FILE_MAP_WRITE,0,0,1024));
      if(!words_)return false;
      InterlockedExchange(words_,LONG(0x324d5047u));InterlockedExchange(words_+1,1);
      InterlockedExchange(words_+2,1024);InterlockedExchange(words_+3,320);
    }
    return words_!=nullptr;
  }
  bool publish(const std::wstring& path,const Encoded& bytes){
    if(sequence_==UINT32_MAX||!claim(path))return false;
    uint32_t next=sequence_+1;uint32_t start=16+(next&1u)*80;
    for(unsigned i=0;i<80;i++){
      uint32_t value=0;std::memcpy(&value,bytes.data()+i*4,4);
      InterlockedExchange(words_+start+i,static_cast<LONG>(value));
    }
    // Full-fence publication after every payload word. No per-frame OS I/O.
    InterlockedExchange(words_+4,static_cast<LONG>(next));sequence_=next;return true;
  }
};
}
