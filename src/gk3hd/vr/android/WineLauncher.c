/* Standalone launcher. Activate only our suspended child.
 * It does not edit the executable on disk or any Wine/Windows registry key.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include "live_state.h"
#include "window_observation.h"
#include "child_job.h"
#include "renderer_failure.h"

/* Shared activation words, optionally followed by the explicit
 * stereo-only output contract. Reject malformed input before creating a child.
 * The small diagnostic/desktop activation set remains a valid caller too. */
enum { MAX_LAUNCH_SWITCHES = 11 };
static int read_launch_switches(FILE* config,DWORD switches[MAX_LAUNCH_SWITCHES],unsigned int* count) {
    char token[32];unsigned int wanted=0;
    if(fscanf(config,"%31s",token)!=1) return 0;
    if(!strcmp(token,"9")) wanted=9;
    else if(!strcmp(token,"10")) wanted=10;
    else if(!strcmp(token,"11")) wanted=11;
    else return 0;
    for(unsigned int i=0;i<wanted;i++) {
        if(fscanf(config,"%31s",token)!=1) return 0;
        for(const unsigned char* c=(const unsigned char*)token;*c;c++) if(!isxdigit(*c)) return 0;
        errno=0;unsigned long address=strtoul(token,NULL,16);
        if(errno==ERANGE||address<0x400000||address>=0x8000000||address%4) return 0;
        for(unsigned int prior=0;prior<i;prior++) if(switches[prior]==(DWORD)address) return 0;
        switches[i]=(DWORD)address;
    }
    char extra;
    if(fscanf(config," %c",&extra)==1||ferror(config)) return 0;
    *count=wanted;return 1;
}

static int word(HANDLE process,DWORD address,DWORD *value,int write) {
    SIZE_T count=0;
    BOOL ok=write ? WriteProcessMemory(process,(void *)(uintptr_t)address,value,sizeof(*value),&count)
                  : ReadProcessMemory(process,(void *)(uintptr_t)address,value,sizeof(*value),&count);
    return ok && count==sizeof(*value);
}
static void diagnostic_snapshot(HANDLE process) {
    FILE* config=fopen("diagnostic-points.txt","r");
    if(!config) return;
    char label[25],line[192];unsigned long address=0;unsigned int words=0,records=0;
    while(records++<12 && fgets(line,sizeof(line),config)) {
        unsigned long offsets[3]={0};
        int fields=sscanf(line,"%24s %lx %u %lx %lx %lx",label,&address,&words,
                          &offsets[0],&offsets[1],&offsets[2]);
        if(fields<3) break;
        if(address<0x400000||address>=0x8000000||words<1||words>48) break;
        int valid=1;
        for(int step=0;step<fields-3;step++) {
            DWORD pointer=0;
            if(offsets[step]>0x10000||!word(process,address,&pointer,0)||
               pointer<0x10000||pointer>=0x7fff0000) {valid=0;break;}
            address=pointer+offsets[step];
        }
        if(!valid) continue;
        DWORD values[48]={0};SIZE_T copied=0;
        if(!ReadProcessMemory(process,(void*)(uintptr_t)address,values,words*4,&copied)||copied!=words*4) break;
        printf("Snapshot %s",label);
        for(unsigned int i=0;i<words;i++) printf(" %08lx",(unsigned long)values[i]);
        putchar('\n');
    }
    fclose(config);fflush(stdout);
}
/* Workbench-only timeout evidence. Inspect only the suspended/owned child, and
 * resume each sampled thread immediately, including failed context reads. */
static void describe_timeout(const PROCESS_INFORMATION *child) {
    WindowObservation windows={child->dwProcessId,16};
    EnumWindows(describe_owned_top_window,(LPARAM)&windows);
    HANDLE modules=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE|TH32CS_SNAPMODULE32,child->dwProcessId);
    if(modules!=INVALID_HANDLE_VALUE) {
        MODULEENTRY32 module={sizeof(module)};
        if(Module32First(modules,&module)) do {
            printf("Module %08lx +%08lx %s\n",(unsigned long)(uintptr_t)module.modBaseAddr,
                (unsigned long)module.modBaseSize,module.szModule);
            if(_stricmp(module.szModule,"ddraw.dll")==0) printf("DirectDraw path: %s\n",module.szExePath);
        } while(Module32Next(modules,&module));
        CloseHandle(modules);
    }
    HANDLE threads=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    if(threads==INVALID_HANDLE_VALUE) {
        printf("Thread snapshot failed: %lu\n",GetLastError());fflush(stdout);return;
    }
    THREADENTRY32 thread={sizeof(thread)};unsigned int sampled=0,matched=0,contexts=0;
    if(Thread32First(threads,&thread)) do {
        if(thread.th32OwnerProcessID!=child->dwProcessId) continue;
        matched++;
        if(sampled++>=32) continue;
        HANDLE handle=OpenThread(THREAD_SUSPEND_RESUME|THREAD_GET_CONTEXT,FALSE,thread.th32ThreadID);
        if(!handle) {printf("Thread %lu open failed: %lu\n",thread.th32ThreadID,GetLastError());continue;}
        if(SuspendThread(handle)!=(DWORD)-1) {
            CONTEXT context={0};context.ContextFlags=CONTEXT_CONTROL;
            if(GetThreadContext(handle,&context)) {
                contexts++;
                DWORD stack[20]={0};SIZE_T bytes=0;
                ReadProcessMemory(child->hProcess,(void *)(uintptr_t)context.Esp,stack,sizeof(stack),&bytes);
                printf("Thread %lu EIP=%08lx ESP=%08lx EBP=%08lx stack",thread.th32ThreadID,
                    (unsigned long)context.Eip,(unsigned long)context.Esp,(unsigned long)context.Ebp);
                for(SIZE_T i=0;i<bytes/sizeof(DWORD);i++) printf(" %08lx",(unsigned long)stack[i]);
                putchar('\n');
                DWORD frame=context.Ebp;
                printf("Frame chain %lu",thread.th32ThreadID);
                for(unsigned int i=0;i<12 && frame>=context.Esp && frame-context.Esp<0x100000;i++) {
                    DWORD link[2]={0};SIZE_T copied=0;
                    if(!ReadProcessMemory(child->hProcess,(void *)(uintptr_t)frame,link,sizeof(link),&copied)||copied!=sizeof(link)) break;
                    printf(" %08lx",(unsigned long)link[1]);
                    if(link[0]<=frame) break;
                    frame=link[0];
                }
                putchar('\n');
            } else printf("Thread %lu context failed: %lu\n",thread.th32ThreadID,GetLastError());
            if(ResumeThread(handle)==(DWORD)-1)
                printf("Thread %lu resume failed: %lu\n",thread.th32ThreadID,GetLastError());
        } else printf("Thread %lu suspend failed: %lu\n",thread.th32ThreadID,GetLastError());
        CloseHandle(handle);
    } while(Thread32Next(threads,&thread));
    printf("Thread observation pid=%lu matched=%u sampled=%u contexts=%u enumeration_error=%lu\n",
        child->dwProcessId,matched,sampled<32 ? sampled : 32,contexts,GetLastError());
    CloseHandle(threads);fflush(stdout);
}
static int launch(int argc,char **argv) {
    if(argc==2 && strcmp(argv[1],"--runtime-check")==0) {
        HMODULE runtime=LoadLibraryW(L"openxr_wxr32.dll");
        if(!runtime) {fprintf(stderr,"Runtime LoadLibrary failed: %lu\n",GetLastError());return 1;}
        printf("Runtime loader entry=%s\n",GetProcAddress(runtime,"xrNegotiateLoaderRuntimeInterface") ? "present" : "missing");
        FreeLibrary(runtime);return 0;
    }
    STARTUPINFOW startup={sizeof(startup)};
    PROCESS_INFORMATION child={0};
    wchar_t command[]=L"GK3-VR.exe -window -width 1280 -height 800";
    DWORD switches[MAX_LAUNCH_SWITCHES],value=0,desktopSwitch=0;
    unsigned int count=0;
    int interactive=argc==2 && strcmp(argv[1],"--play")==0;
    int desktop=argc==3 && strcmp(argv[2],"--desktop-control")==0;
    int result=1,seconds=(argc==2||desktop) ? atoi(argv[1]) : 0;
    const char* observation=getenv("GK3HD_STANDALONE_OBSERVE");
    const char* selfObservation=getenv("GK3HD_TEST_SELF_OBSERVATION");
    const char* sampleStacks=getenv("GK3HD_STANDALONE_STACKS");
    if(observation&&(interactive||!live_token(observation))) {
        fputs("Live observation requires a bounded test and a 32-digit hexadecimal token\n",stderr);return 2;
    }
    if(sampleStacks&&(!observation||strcmp(sampleStacks,"1"))) {
        fputs("Stack sampling requires an explicit bounded observation test\n",stderr);return 2;
    }
    if(selfObservation&&(!observation||strcmp(selfObservation,"1")||sampleStacks)) {
        fputs("Self observation requires a bounded token and excludes remote stack sampling\n",stderr);return 2;
    }
    LiveStateConfig observationConfig=live_config();
    FILE *config=NULL;
    if(!interactive && (seconds<1||seconds>720)) {
        fputs("Specify --play or a bounded test duration, 1..720 seconds\n",stderr);return 2;
    }
    /* No console is visible in the headset. Keep one bounded-name launch log;
     * diagnostics for the owned child still use their separate inherited handle. */
    if(interactive || getenv("GK3HD_STANDALONE_LAUNCH")) {
        HWND console=GetConsoleWindow();
        if(console) ShowWindow(console,SW_HIDE);
        if(!freopen("standalone-launch.log","w",stdout)) return 1;
        if(!freopen("standalone-launch-error.log","w",stderr)) return 1;
    }
    printf("Standalone settings: prototype=%s, DirectDraw=%s\n",
        getenv("GK3HD_XR_PROTOTYPE") ? getenv("GK3HD_XR_PROTOTYPE") : "unset",
        getenv("WINEDLLOVERRIDES") ? getenv("WINEDLLOVERRIDES") : "unset");fflush(stdout);
    if(observation) {printf("Workbench native stack observations=%s\n",sampleStacks ? "enabled" : "disabled");fflush(stdout);}
    config=fopen("launch-switches.txt","r");
    if(!config) {perror("launch-switches.txt");return 2;}
    if(!read_launch_switches(config,switches,&count)) {fclose(config);return 2;}
    fclose(config);
    if(desktop) {
        unsigned long address=0;int found=0;
        config=fopen("desktop-input-switch.txt","r");
        if(!config) {perror("desktop-input-switch.txt");return 2;}
        int valid=fscanf(config,"%lx",&address)==1;fclose(config);
        for(unsigned int i=0;i<count;i++) if(switches[i]==address) found=1;
        if(!valid||!found) {fputs("Desktop input switch is not in the verified activation set\n",stderr);return 2;}
        desktopSwitch=(DWORD)address;
    }
    SECURITY_ATTRIBUTES inherit={sizeof(inherit),NULL,TRUE};
    char outputName[80];
    snprintf(outputName,sizeof(outputName),"child-%llu.log",GetTickCount64());
    HANDLE input=CreateFileW(L"NUL",GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,&inherit,OPEN_EXISTING,0,NULL);
    HANDLE output=CreateFileA(outputName,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,&inherit,CREATE_NEW,0,NULL);
    if(input==INVALID_HANDLE_VALUE||output==INVALID_HANDLE_VALUE) {
        fprintf(stderr,"Child log/input setup failed: %lu\n",GetLastError());
        if(input!=INVALID_HANDLE_VALUE) CloseHandle(input);
        if(output!=INVALID_HANDLE_VALUE) CloseHandle(output);
        return 1;
    }
    startup.dwFlags=STARTF_USESTDHANDLES;
    startup.hStdInput=input;startup.hStdOutput=output;startup.hStdError=output;
    HANDLE job=standalone_child_job();
    if(!job) {
        fprintf(stderr,"Cannot establish owned game lifetime: %lu\n",GetLastError());
        CloseHandle(input);CloseHandle(output);return 1;
    }
    HANDLE rendererFailure=standalone_renderer_failure();
    if(!rendererFailure&&GetLastError()!=ERROR_SUCCESS) {
        fprintf(stderr,"Cannot establish this session's renderer failure channel: %lu\n",GetLastError());
        CloseHandle(job);CloseHandle(input);CloseHandle(output);return 1;
    }
    HANDLE rendererSetup=NULL;
    if(rendererFailure&&standalone_renderer_setup_requested()) {
        rendererSetup=standalone_renderer_setup_timer();
        if(!rendererSetup) {
            char session[33];
            fprintf(stderr,"Cannot establish this session's graphics setup deadline: %lu\n",GetLastError());
            if(standalone_renderer_session_token(session))fprintf(stderr,"GK3HD_RENDERER_FAULT %s\n",session);
            CloseHandle(rendererFailure);CloseHandle(job);CloseHandle(input);CloseHandle(output);return 1;
        }
    }
    BOOL created=CreateProcessW(L"GK3-VR.exe",command,NULL,NULL,TRUE,CREATE_SUSPENDED,NULL,NULL,&startup,&child);
    DWORD createError=GetLastError();
    CloseHandle(input);CloseHandle(output);
    printf("Child diagnostics: %s\n",outputName);fflush(stdout);
    if(!created) {
        fprintf(stderr,"CreateProcess failed: %lu\n",createError);CloseHandle(job);
        if(rendererSetup)CloseHandle(rendererSetup);
        if(rendererFailure)CloseHandle(rendererFailure);return 1;
    }
    if(!AssignProcessToJobObject(job,child.hProcess)) {
        fprintf(stderr,"Cannot bind owned game to launcher lifetime: %lu\n",GetLastError());goto done;
    }
    printf("Bound owned child %lu to launcher lifetime\n",child.dwProcessId);fflush(stdout);
    for(unsigned int i=0;i<count;i++) {
        if(!word(child.hProcess,switches[i],&value,0)||value!=0) {
            fputs("Dormant VR activation state differs from the compiled player\n",stderr);goto done;
        }
    }
    for(unsigned int i=0;i<count;i++) {
        value=switches[i]==desktopSwitch ? 0 : 1;
        if(!word(child.hProcess,switches[i],&value,1)) goto done;
    }
    for(unsigned int i=0;i<count;i++) {
        DWORD expected=switches[i]==desktopSwitch ? 0 : 1;
        if(!word(child.hProcess,switches[i],&value,0)||value!=expected) goto done;
    }
    if(ResumeThread(child.hThread)!=1) goto done;
    printf("Activated %u VR switches in owned child %lu%s\n",count-(desktop?1:0),child.dwProcessId,
        desktop ? "; diagnostic desktop input, no tracking override" : "");fflush(stdout);
    DWORD wait;
    if(!interactive && getenv("GK3HD_STANDALONE_LAUNCH")) {
        ULONGLONG deadline=GetTickCount64()+(ULONGLONG)seconds*1000;
        ULONGLONG snapshotAt=GetTickCount64()+5000;
        ULONGLONG observeAt=GetTickCount64();
        ULONGLONG stacksAt=GetTickCount64()+20000;unsigned sampledStacks=0;
        for(;;) {
            ULONGLONG now=GetTickCount64();
            DWORD remaining=now>=deadline ? 0 : (DWORD)(deadline-now);
            DWORD interval=observation ? 200 : 1000;
            wait=standalone_wait_child(child.hProcess,rendererFailure,rendererSetup,remaining>interval ? interval : remaining);
            if(wait!=WAIT_TIMEOUT||GetTickCount64()>=deadline) break;
            if(observation&&!selfObservation&&GetTickCount64()>=observeAt) {
                live_snapshot(child.hProcess,child.dwProcessId,&observationConfig,observation);
                observeAt=GetTickCount64()+200;
            }
            /* The Save flow spends its first 30+ seconds loading and typing.
             * Keep the opt-in sample bound, but cover the later failure too,
             * not only three healthy startup/menu snapshots. */
            if(sampleStacks&&sampledStacks<6&&GetTickCount64()>=stacksAt) {
                describe_timeout(&child);sampledStacks++;stacksAt=GetTickCount64()+10000;
            }
            if(!selfObservation&&GetTickCount64()>=snapshotAt) {
                diagnostic_snapshot(child.hProcess);snapshotAt=GetTickCount64()+5000;
            }
        }
    } else wait=standalone_wait_child(child.hProcess,rendererFailure,rendererSetup,interactive ? INFINITE : seconds*1000);
    if(wait==WAIT_FAILED) {fprintf(stderr,"Child wait failed: %lu\n",GetLastError());goto done;}
    if(wait==WAIT_OBJECT_0+1||wait==WAIT_OBJECT_0+2) {
        char session[33];
        if(standalone_renderer_session_token(session))fprintf(stderr,"GK3HD_RENDERER_FAULT %s\n",session);
        fputs(wait==WAIT_OBJECT_0+2
            ? "Compressed graphics setup timed out. Restart GK3HD VR to try ordinary rendering.\n"
            : "The graphics runtime failed; stopping only this session's game. Restart GK3HD VR to try again.\n",stderr);
        fflush(stderr);goto done;
    }
    if(wait==WAIT_TIMEOUT) {
        if(!selfObservation) diagnostic_snapshot(child.hProcess);
        PostThreadMessageW(child.dwThreadId,WM_QUIT,0,0);
        if(WaitForSingleObject(child.hProcess,5000)==WAIT_TIMEOUT) {
            if(sampleStacks) describe_timeout(&child);
            fputs("Owned child did not quit within the grace period\n",stderr);goto done;
        }
    }
    if(GetExitCodeProcess(child.hProcess,&value)) {printf("Owned child exit=%lu\n",value);result=value==0 ? 0 : 1;}
done:
    if(WaitForSingleObject(child.hProcess,0)==WAIT_TIMEOUT) {
        TerminateProcess(child.hProcess,1);WaitForSingleObject(child.hProcess,5000);
    }
    CloseHandle(child.hThread);CloseHandle(child.hProcess);CloseHandle(job);
    if(rendererSetup)CloseHandle(rendererSetup);
    if(rendererFailure)CloseHandle(rendererFailure);
    return result;
}

int main(int argc,char **argv) {
    int result=launch(argc,argv);
    char session[33];
    // Wine's desktop process can exit successfully after the owned launcher
    // failed. Record the actual result under this launch's identity.
    if(result!=0&&getenv("GK3HD_STANDALONE_LAUNCH")&&standalone_renderer_session_token(session)) {
        fflush(stderr);
        FILE *log=fopen("standalone-launch-error.log","a");
        if(log) {
            fprintf(log,"\nGK3HD_GUEST_EXIT %s %d\n",session,result);
            fclose(log);
        }
    }
    return result;
}
