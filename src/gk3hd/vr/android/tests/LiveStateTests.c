#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "live_state.h"

static void check(int condition,const char* message) {if(!condition) {puts(message);exit(1);}}
static FILE* snapshots;
static void observe(char* output,size_t size,const LiveStateConfig* config) {
    FILE* file=tmpfile();check(file!=NULL,"Cannot create isolated observer fixture");
    live_write(file,GetCurrentProcess(),123,config,"0123456789abcdef0123456789abcdef");
    check(!ferror(file),"Observer output failed");rewind(file);
    size_t count=fread(output,1,size-1,file);output[count]=0;fclose(file);
    if(snapshots) check(fwrite(output,1,count,snapshots)==count,"Cannot retain observer fixture JSON");
}
int main(int argc,char** argv) {
    check(argc<=2,"Expected at most one snapshot output path");
    if(argc==2) {snapshots=fopen(argv[1],"wb");check(snapshots!=NULL,"Cannot create snapshot output");}
    check(live_token("0123456789abcdef0123456789abcdef"),"Valid observation token rejected");
    check(!live_token(NULL)&&!live_token("abc")&&!live_token("0123456789abcdef0123456789abcdeX"),"Malformed observation token accepted");
    DWORD engine[330]={0},services[64]={0},manager[32]={0},layer[256]={0};
    DWORD editor[48]={0},camera[100]={0},rows[20]={0},name[32]={0},text[23]={0};
    char description[]="vr \"save\"\\test";
    DWORD enginePointer=(DWORD)(uintptr_t)engine;
    engine[0x444/4]=(DWORD)(uintptr_t)services;
    services[0x44/4]=(DWORD)(uintptr_t)manager;
    services[0x28/4]=(DWORD)(uintptr_t)camera;
    manager[0x58/4]=(DWORD)(uintptr_t)layer;
    layer[0]=0x123456;layer[6]=1;layer[7]=10;layer[8]=20;layer[9]=1280;layer[10]=800;
    layer[0x2b4/4]=(DWORD)(uintptr_t)rows;layer[0x2b8/4]=(DWORD)(uintptr_t)rows+0x4c;
    rows[0x20/4]=(DWORD)(uintptr_t)name;
    name[7]=100;name[8]=200;name[9]=500;name[10]=230;
    name[0x3c/4]=(DWORD)(uintptr_t)description;name[0x40/4]=(DWORD)strlen(description);
    editor[0]=0x765432;editor[0x34/4]=(DWORD)(uintptr_t)description;editor[0x38/4]=(DWORD)strlen(description);
    text[0]=(DWORD)(uintptr_t)editor;text[2]=42;text[8]=7;
    camera[0]=0x345678;float values[5]={1,2,3,4,5};memcpy(camera+0x13c/4,values,sizeof(values));
    LiveStateConfig config={(DWORD)(uintptr_t)&enginePointer,(DWORD)(uintptr_t)text,camera[0],layer[0],0};
    char output[16384];observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Missing scene identity fabricated a location");
    check(strstr(output,"\"game_foreground\":false")!=NULL,"Unrelated foreground window fabricated native focus");
    DWORD console[11]={0},consoleScope=(DWORD)(uintptr_t)console;
    config.consoleScope=(DWORD)(uintptr_t)&consoleScope;config.consoleType=0x765432;
    console[0]=config.consoleType;console[7]=5;console[8]=10;console[9]=500;console[10]=250;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_draw\":{\"flags\":0,\"visible\":false,\"rect\":[5,10,500,250]}")!=NULL,"Active hidden console draw was not observed");
    console[6]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_draw\":{\"flags\":1,\"visible\":true")!=NULL,"Active visible console draw was not observed");
    console[0]=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_draw\":null")!=NULL,"Unrelated owner fabricated a console");
    consoleScope=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_draw\":null")!=NULL,"Unreadable owner fabricated console visibility");
    consoleScope=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_draw\":null")!=NULL,"Absent draw scope fabricated closed-console proof");
    check(strstr(output,"\"console_state\":null")!=NULL,"Invalidated object fabricated current visibility");
    check(strstr(output,"\"console_present\":false")!=NULL,"Known absent owned console was not distinguished");
    consoleScope=(DWORD)(uintptr_t)console;console[0]=config.consoleType;console[6]=1;
    services[0x4c/4]=(DWORD)(uintptr_t)console;
    observe(output,sizeof(output),&config);
    consoleScope=0;console[6]=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_state\":{\"visible\":false}")!=NULL,"Current closed state not read after the Draw scope ended");
    services[0x4c/4]=(DWORD)(uintptr_t)console;observe(output,sizeof(output),&config);
    check(strstr(output,"\"matches_draw\":false,\"visible\":false")!=NULL,"Owned mini-console was not observed independently");
    DWORD secondConsole[11]={0};secondConsole[0]=config.consoleType;secondConsole[6]=1;
    services[0x4c/4]=(DWORD)(uintptr_t)secondConsole;observe(output,sizeof(output),&config);
    check(strstr(output,"\"matches_draw\":false,\"visible\":true")!=NULL,"Different owned mini-console was not distinguished");
    services[0x4c/4]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"owned_console\":null")!=NULL,"Unreadable owned console fabricated state");
    check(strstr(output,"\"console_present\":true")!=NULL,"Unreadable non-null console was incorrectly called absent");
    services[0x4c/4]=(DWORD)(uintptr_t)console;
    console[6]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_state\":{\"visible\":true}")!=NULL,"Owned object retained a stale visibility value");
    console[0]=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"console_state\":null")!=NULL,"Changed object type retained a stale visibility value");
    engine[0x518/4]=0x18;observe(output,sizeof(output),&config);
    check(strstr(output,"\"key_modifiers\":24")!=NULL,"Native keyboard modifiers were not observed");
    engine[0x518/4]=0;
    DWORD gameState[8]={0},locations[84]={0},times[18]={0};
    char location[]="LBY",time[]="110a",targetTime[]="202p",badName[]="A!B";
    services[0x60/4]=(DWORD)(uintptr_t)gameState;gameState[4]=1;gameState[5]=2;
    locations[1]=(DWORD)(uintptr_t)location;times[2]=(DWORD)(uintptr_t)time;times[3]=(DWORD)(uintptr_t)targetTime;
    config.locationNames=(DWORD)(uintptr_t)locations;config.timeNames=(DWORD)(uintptr_t)times;config.timeType=0x654321;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":{\"location\":\"LBY\",\"timeblock\":\"110a\"}")!=NULL,"Retail tables did not identify the actual scene");
    DWORD oldType=layer[0];layer[0]=config.timeType;layer[0x3cc/4]=3;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"timeblock\":\"202p\"")!=NULL,"Visible time-block target was not observed");
    layer[0]=oldType;
    for(unsigned invalid=0;invalid<3;invalid++) {
        gameState[4]=invalid==0 ? 0 : invalid==1 ? 84 : 0xffffffff;
        observe(output,sizeof(output),&config);
        check(strstr(output,"\"scene\":null")!=NULL,"Invalid native location ID fabricated a scene");
    }
    gameState[4]=1;locations[1]=(DWORD)(uintptr_t)badName;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Malformed native name fabricated a scene");
    locations[1]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Unreadable native name fabricated a scene");
    locations[1]=(DWORD)(uintptr_t)location;gameState[5]=18;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Invalid native time ID fabricated a scene");
    char unterminated[]="R25x";locations[1]=(DWORD)(uintptr_t)unterminated;gameState[5]=2;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Unterminated native location fabricated a scene");
    locations[1]=(DWORD)(uintptr_t)location;
    gameState[5]=2;config.locationNames=0xfffffffcu;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene\":null")!=NULL,"Wrapped native table fabricated a scene");
    config.locationNames=(DWORD)(uintptr_t)locations;observe(output,sizeof(output),&config);
    check(strstr(output,"\"layer_type\":1193046")!=NULL,"Native layer was not observed");
    check(strstr(output,"\"rect\":[100,200,500,230]")!=NULL,"Save row bounds were not observed");
    check(strstr(output,"vr \\\"save\\\"\\\\test")!=NULL,"Native string was not JSON escaped");
    check(strstr(output,"\"text_epoch\":42,\"text_accepted\":7")!=NULL,"Editor acknowledgement missing");
    check(strstr(output,"\"text_state\":[")!=NULL,"Keyboard mailbox evidence missing");
    check(strstr(output,"\"rows_status\":\"complete\",\"rows_read\":1,\"rows_expected\":1")!=NULL,"Complete catalog was not distinguished from missing evidence");
    DWORD rowBegin=layer[0x2b4/4],rowEnd=layer[0x2b8/4],rowBox=rows[0x20/4],nameData=name[0x3c/4],nameSize=name[0x40/4];
    /* Wine can allocate the catalog and label above 2 GiB after scene loads.
     * Exercise real mapped high memory, not mocked pointer arithmetic. */
    BYTE* high=NULL;
    for(DWORD address=0x81000000u;address<0xf0000000u&&!high;address+=0x1000000u)
        high=(BYTE*)VirtualAlloc((void*)(uintptr_t)address,65536,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    check(high!=NULL,"Cannot allocate high-address observer fixture; link LARGEADDRESSAWARE");
    DWORD* highRows=(DWORD*)high;DWORD* highName=(DWORD*)(high+0x100);
    memcpy(highName,name,sizeof(name));highRows[0x20/4]=(DWORD)(uintptr_t)highName;
    layer[0x2b4/4]=(DWORD)(uintptr_t)highRows;layer[0x2b8/4]=(DWORD)(uintptr_t)highRows+0x4c;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"rect\":[100,200,500,230]")!=NULL&&
        strstr(output,"\"rows_status\":\"complete\",\"rows_read\":1,\"rows_expected\":1")!=NULL,
        "Readable high-address catalog was rejected");
    layer[0x2b4/4]=rowBegin;layer[0x2b8/4]=rowEnd;
    check(VirtualFree(high,0,MEM_RELEASE),"Cannot release high-address fixture");
    DWORD invalidRead=0;
    check(!live_read(GetCurrentProcess(),0xfffffffcu,&invalidRead,sizeof(invalidRead)),"Reserved top address accepted");
    check(!live_read(GetCurrentProcess(),1,&invalidRead,sizeof(invalidRead)),"Invalid low address accepted");
    layer[0x2b8/4]=rowBegin;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows\":[],\"rows_status\":\"complete\",\"rows_read\":0,\"rows_expected\":0")!=NULL,"Known empty range lost");
    layer[0x2b8/4]=rowBegin+1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"invalid_range\",\"rows_read\":0,\"rows_expected\":null")!=NULL,"Misaligned range fabricated an empty catalog");
    layer[0x2b8/4]=rowBegin-1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"invalid_range\"")!=NULL,"Reversed range fabricated an empty catalog");
    layer[0x2b8/4]=rowBegin+65*0x4c;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"limit_exceeded\",\"rows_read\":0,\"rows_expected\":65")!=NULL,"Bounded catalog was called empty");
    layer[0x2b8/4]=rowEnd;rows[0x20/4]=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"missing_item\",\"rows_read\":0,\"rows_expected\":1")!=NULL,"Missing row box was called an empty catalog");
    rows[0x20/4]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"unreadable_rectangle\"")!=NULL,"Unreadable row box was not distinguished");
    rows[0x20/4]=rowBox;name[0x3c/4]=1;name[0x40/4]=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"unreadable_name\",\"rows_read\":1,\"rows_expected\":1")!=NULL,"Unreadable name was called a complete catalog");
    name[0x40/4]=0;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"complete\"")!=NULL,"Readable empty name was called an unavailable read");
    name[0x3c/4]=nameData;name[0x40/4]=nameSize;
    SYSTEM_INFO system;GetSystemInfo(&system);SIZE_T page=system.dwPageSize;DWORD protection=0;
    BYTE* guarded=(BYTE*)VirtualAlloc(NULL,page*2,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    check(guarded!=NULL&&VirtualProtect(guarded+page,page,PAGE_NOACCESS,&protection),"Cannot create bounded-read fixture");
    DWORD* guardedLayer=(DWORD*)(guarded+page-0x2b8);guardedLayer[0]=layer[0];guardedLayer[6]=1;
    manager[0x58/4]=(DWORD)(uintptr_t)guardedLayer;observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"unreadable_range\",\"rows_read\":0,\"rows_expected\":null")!=NULL,"Partly unreadable range fabricated zero entries");
    manager[0x58/4]=(DWORD)(uintptr_t)layer;
    layer[0x2b4/4]=(DWORD)(uintptr_t)(guarded+page);layer[0x2b8/4]=layer[0x2b4/4]+0x4c;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"rows_status\":\"unreadable_item\",\"rows_read\":0,\"rows_expected\":1")!=NULL,"Unreadable item storage fabricated an empty range");
    layer[0x2b4/4]=rowBegin;layer[0x2b8/4]=rowEnd;
    check(VirtualFree(guarded,0,MEM_RELEASE),"Cannot release bounded-read fixture");
    text[15]=1;text[16]=24;text[17]=42;text[18]=1;text[19]=42;text[20]=1;text[21]=97;text[22]=123;
    observe(output,sizeof(output),&config);
    check(strstr(output,",1,24,42,1,42,1,97,123]")!=NULL,"Renderer keyboard intent was not observed");
    check(strstr(output,"\"camera\":[1,2,3,4,5]")!=NULL,"Camera state was not observed");
    check(strstr(output,"\"scene_frames\":null")!=NULL,"Missing scene counter fabricated throughput");
    check(strstr(output,"\"input_state\":[]")!=NULL,"Missing input state fabricated controller evidence");
    DWORD inputState[34]={1,885,733};config.inputState=(DWORD)(uintptr_t)inputState;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"input_state\":[1,885,733,")!=NULL,"Controller dispatch state was not observed");
    config.inputState=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"input_state\":[]")!=NULL,"Invalid input address fabricated controller evidence");
    DWORD frameCounter=0;config.sceneFrames=(DWORD)(uintptr_t)&frameCounter;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene_frames\":0")!=NULL,"Valid zero frame count lost");
    frameCounter=1234;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene_frames\":1234")!=NULL,"Native produced-frame count not observed");
    config.sceneFrames=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"scene_frames\":null")!=NULL,"Invalid counter address fabricated throughput");
    DWORD stack[4]={(DWORD)(uintptr_t)layer,0,1,0};
    manager[0x58/4]=0;manager[0x44/4]=(DWORD)(uintptr_t)(stack+4);
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"layer_type\":1193046")!=NULL,"Stack fallback did not read the complete native entry");
    DWORD cycle=(DWORD)(uintptr_t)layer;layer[0x4c/4]=(DWORD)(uintptr_t)&cycle;layer[0x50/4]=1;
    observe(output,sizeof(output),&config);check(strlen(output)<8192,"Cyclic UI graph was not bounded");
    DWORD leaf[48]={0},button[48]={0},garbage[48]={0},aliases[64],siblings[2];
    leaf[0]=0x111111;leaf[6]=1;leaf[7]=10;leaf[8]=20;leaf[9]=100;leaf[10]=50;
    button[0]=0x222222;button[6]=1;button[7]=120;button[8]=30;button[9]=150;button[10]=50;
    garbage[0]=0x333333;garbage[6]=1;garbage[7]=0x12345678;garbage[9]=0x23456789;
    for(unsigned i=0;i<64;i++) aliases[i]=(DWORD)(uintptr_t)garbage;
    leaf[0x4c/4]=(DWORD)(uintptr_t)aliases;leaf[0x50/4]=64;
    siblings[0]=(DWORD)(uintptr_t)leaf;siblings[1]=(DWORD)(uintptr_t)button;
    layer[0x4c/4]=(DWORD)(uintptr_t)siblings;layer[0x50/4]=2;
    observe(output,sizeof(output),&config);
    check(strstr(output,"\"rect\":[120,30,150,50]")!=NULL,"False leaf children hid a later real button");
    check(strstr(output,"\"type\":3355443,")==NULL,"Font/code data fabricated a visible widget");
    aliases[0]=(DWORD)(uintptr_t)leaf;leaf[0x50/4]=1;
    observe(output,sizeof(output),&config);
    char* first=strstr(output,"\"type\":1118481,");
    check(first&&strstr(first+1,"\"type\":1118481,")==NULL,"Aliased widget was emitted more than once");
    check(strstr(output,"\"rect\":[120,30,150,50]")!=NULL,"A cyclic leaf hid a later sibling");
    config.engine=1;config.text=1;observe(output,sizeof(output),&config);
    check(strstr(output,"\"layer_type\":0,")!=NULL&&strstr(output,"\"controls\":[]")!=NULL,"Invalid graph fabricated a live layer");
    check(strstr(output,"\"scene\":null")!=NULL,"Invalid graph fabricated scene identity");
    check(strstr(output,"\"camera\":[]")!=NULL,"Invalid graph fabricated camera state");
    check(strstr(output,"\"text_state\":[]")!=NULL,"Invalid mailbox fabricated keyboard evidence");
    if(snapshots) check(fclose(snapshots)==0,"Cannot finish snapshot output");
    puts("Live observation passed: read-only graphs, retail scene identity, bounded cycles, editor/rows/camera, escaped strings and missing state");
    return 0;
}
