#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <wchar.h>
#include "../child_job.h"

static HANDLE processes[12];
static unsigned processCount,checks;
static wchar_t ownPath[MAX_PATH],handoff[MAX_PATH];
static void cleanup(void) {
    for(unsigned i=0;i<processCount;i++) {
        if(WaitForSingleObject(processes[i],0)==WAIT_TIMEOUT) {
            TerminateProcess(processes[i],90);WaitForSingleObject(processes[i],5000);
        }
        CloseHandle(processes[i]);
    }
    if(handoff[0]) DeleteFileW(handoff);
}
static void require(int ok,const char *message) {
    if(!ok) {fprintf(stderr,"FAIL: %s (error %lu)\n",message,GetLastError());cleanup();ExitProcess(1);}
    ++checks;
}
static PROCESS_INFORMATION child(const wchar_t *arguments,HANDLE job) {
    wchar_t command[2*MAX_PATH+40];
    STARTUPINFOW startup={sizeof(startup)};PROCESS_INFORMATION info={0};
    require(_snwprintf_s(command,sizeof(command)/sizeof(command[0]),_TRUNCATE,
        L"\"%ls\" %ls",ownPath,arguments)>0,"bounded child command");
    require(CreateProcessW(ownPath,command,NULL,NULL,FALSE,CREATE_SUSPENDED|CREATE_NO_WINDOW,
        NULL,NULL,&startup,&info),"create owned test child");
    require(processCount<sizeof(processes)/sizeof(processes[0]),"bounded process ownership");
    processes[processCount++]=info.hProcess;
    if(job) require(AssignProcessToJobObject(job,info.hProcess),"bind child before execution");
    require(ResumeThread(info.hThread)==1,"resume owned child");CloseHandle(info.hThread);return info;
}
static int owner(const wchar_t *path) {
    HANDLE job=standalone_child_job();require(job!=NULL,"owner job creation");
    PROCESS_INFORMATION info=child(L"--child",job);
    HANDLE file=CreateFileW(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    require(file!=INVALID_HANDLE_VALUE,"open owned handoff");
    DWORD data[2]={GetCurrentProcessId(),info.dwProcessId},written=0;
    require(WriteFile(file,data,sizeof(data),&written,NULL)&&written==sizeof(data)&&
        FlushFileBuffers(file),"publish exact owner/child identity");CloseHandle(file);
    Sleep(30000);CloseHandle(job);cleanup();return 2;
}
int wmain(int argc,wchar_t **argv) {
    DWORD length=GetModuleFileNameW(NULL,ownPath,MAX_PATH);
    require(length>0&&length<MAX_PATH,"actual executable path");
    if(argc==2&&!wcscmp(argv[1],L"--child")) {Sleep(30000);return 3;}
    if(argc==2&&!wcscmp(argv[1],L"--exit")) return 0;
    if(argc==3&&!wcscmp(argv[1],L"--owner")) return owner(argv[2]);
    require(argc==1,"supported test invocation");
    HANDLE job=standalone_child_job();require(job!=NULL,"job creation");
    DWORD flags=0;
    require(GetHandleInformation(job,&flags)&&!(flags&HANDLE_FLAG_INHERIT),"job handle cannot leak into child");
    PROCESS_INFORMATION first=child(L"--child",job);BOOL member=FALSE;
    require(IsProcessInJob(first.hProcess,job,&member)&&member,"actual child membership");
    CloseHandle(job);
    require(WaitForSingleObject(first.hProcess,5000)==WAIT_OBJECT_0,"last job handle closes child");

    job=standalone_child_job();require(job!=NULL,"normal-exit job");
    PROCESS_INFORMATION normal=child(L"--exit",job);DWORD code=1;
    require(WaitForSingleObject(normal.hProcess,5000)==WAIT_OBJECT_0&&
        GetExitCodeProcess(normal.hProcess,&code)&&!code,"normal exit result preserved");CloseHandle(job);

    wchar_t temp[MAX_PATH],arguments[MAX_PATH+20];
    length=GetTempPathW(MAX_PATH,temp);require(length>0&&length<MAX_PATH,"bounded temporary directory");
    require(GetTempFileNameW(temp,L"gk3",0,handoff),"unique owned handoff file");
    require(_snwprintf_s(arguments,sizeof(arguments)/sizeof(arguments[0]),_TRUNCATE,
        L"--owner \"%ls\"",handoff)>0,"bounded owner arguments");
    PROCESS_INFORMATION unrelated=child(L"--child",NULL);
    PROCESS_INFORMATION parent=child(arguments,NULL);
    DWORD ids[2]={0},read=0;ULONGLONG deadline=GetTickCount64()+5000;
    do {
        HANDLE file=CreateFileW(handoff,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);
        if(file!=INVALID_HANDLE_VALUE) {
            if(!ReadFile(file,ids,sizeof(ids),&read,NULL)) read=0;
            CloseHandle(file);
        }
        if(read==sizeof(ids)) break;
        Sleep(1);
    } while(GetTickCount64()<deadline&&WaitForSingleObject(parent.hProcess,0)==WAIT_TIMEOUT);
    require(read==sizeof(ids)&&ids[0]==parent.dwProcessId&&ids[1]!=ids[0],"exact suspended-child ownership handoff");
    HANDLE owned=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION|PROCESS_TERMINATE,FALSE,ids[1]);
    require(owned!=NULL&&processCount<sizeof(processes)/sizeof(processes[0]),"retain exact owned child handle");
    processes[processCount++]=owned;
    require(WaitForSingleObject(owned,0)==WAIT_TIMEOUT,"owned descendant initially alive");
    require(TerminateProcess(parent.hProcess,91)&&WaitForSingleObject(parent.hProcess,5000)==WAIT_OBJECT_0,
        "simulate only owned launcher loss");
    require(WaitForSingleObject(owned,5000)==WAIT_OBJECT_0,"launcher loss stops its descendant");
    require(WaitForSingleObject(unrelated.hProcess,0)==WAIT_TIMEOUT,"unrelated sibling preserved");
    cleanup();printf("Child lifetime: %u behavior checks passed\n",checks);return 0;
}
