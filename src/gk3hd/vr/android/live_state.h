#pragma once

/* Explicit bounded workbench observation only. Never writes game memory or
 * generates input. Reads the launcher's owned child, or the explicitly
 * selected private in-game observer's own process, through its handle. */
#include <math.h>
#include <wchar.h>

typedef struct {
    DWORD engine,text,cameraType,saveType,restoreType,panel,panelState,sceneFrames,inputState;
    DWORD locationNames,timeNames,timeType,consoleScope,consoleType;
} LiveStateConfig;

static int live_read(HANDLE child,DWORD address,void* output,SIZE_T size) {
    SIZE_T copied=0;
    /* Large-address-aware game processes can own readable objects above 2 GiB.
     * Keep the 32-bit user-address/size bounds; let the OS validate mappings. */
    return address>=0x10000 && size<=1024 && address<0xffff0000u &&
        size<=0xffff0000u-address &&
        ReadProcessMemory(child,(void*)(uintptr_t)address,output,size,&copied) && copied==size;
}
static DWORD live_word(HANDLE child,DWORD address) {
    DWORD result=0;live_read(child,address,&result,sizeof(result));return result;
}
static int live_token(const char* token) {
    if(!token||strlen(token)!=32) return 0;
    for(int i=0;i<32;i++) if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f'))) return 0;
    return 1;
}
static LiveStateConfig live_config(void) {
    LiveStateConfig result={0};FILE* input=fopen("diagnostic-points.txt","r");
    if(!input) return result;
    char line[192],label[25];unsigned long address;unsigned count=0;
    while(count++<32&&fgets(line,sizeof(line),input)) {
        if(sscanf(line,"%24s %lx",label,&address)!=2||address<0x400000||address>=0x8000000) continue;
        if(!strcmp(label,"test_engine_global")) result.engine=address;
        else if(!strcmp(label,"test_text_state")) result.text=address;
        else if(!strcmp(label,"test_camera_type")) result.cameraType=address;
        else if(!strcmp(label,"test_save_type")) result.saveType=address;
        else if(!strcmp(label,"test_restore_type")) result.restoreType=address;
        else if(!strcmp(label,"panel_frame")) result.panel=address;
        else if(!strcmp(label,"test_panel_state")) result.panelState=address;
        else if(!strcmp(label,"scene_frames")) result.sceneFrames=address;
        else if(!strcmp(label,"test_input_state")) result.inputState=address;
        else if(!strcmp(label,"test_location_names")) result.locationNames=address;
        else if(!strcmp(label,"test_time_names")) result.timeNames=address;
        else if(!strcmp(label,"test_time_type")) result.timeType=address;
        else if(!strcmp(label,"test_console_scope")) result.consoleScope=address;
        else if(!strcmp(label,"test_console_type")) result.consoleType=address;
    }
    fclose(input);return result;
}
static int live_string(FILE* out,HANDLE child,DWORD box,DWORD offset) {
    DWORD data[2]={0};char text[129]={0};
    int known=live_read(child,box+offset,data,sizeof(data))&&data[1]<=128&&
       (!data[1]||live_read(child,data[0],text,data[1]));
    if(!known) data[1]=0;
    fputc('"',out);
    for(DWORD i=0;i<data[1];i++) {
        unsigned ch=(unsigned char)text[i];
        if(ch=='"'||ch=='\\') {fputc('\\',out);fputc(ch,out);}
        else if(ch<32||ch>=127) fprintf(out,"\\u%04x",ch);
        else fputc(ch,out);
    }
    fputc('"',out);
    return known;
}
static void live_controls(FILE* out,HANDLE child,DWORD node,DWORD parent,unsigned depth,unsigned* emitted,DWORD* visited) {
    if(depth>6||*emitted>=64) return;
    DWORD header[11]={0};
    if(!live_read(child,node,header,sizeof(header))||!(header[6]&255)) return;
    /* Not every widget owns a child vector at +0x4c. Text/font fields can look
     * like a small readable vector, but its pointees are not UI nodes. Reject
     * impossible rectangles before they consume the bounded observation, and
     * never enumerate the same object twice through aliases/cycles. */
    for(unsigned i=7;i<11;i++) if((LONG)header[i]<-16384||(LONG)header[i]>16384) return;
    if((LONG)header[9]<(LONG)header[7]||(LONG)header[10]<(LONG)header[8]) return;
    for(unsigned i=0;i<*emitted;i++) if(visited[i]==node) return;
    visited[*emitted]=node;
    if(*emitted) fputc(',',out);
    (*emitted)++;
    fprintf(out,"{\"type\":%lu,\"parent_type\":%lu,\"rect\":[%ld,%ld,%ld,%ld],\"state\":%lu}",
        header[0],parent,(LONG)header[7],(LONG)header[8],(LONG)header[9],(LONG)header[10],live_word(child,node+0x98));
    DWORD children[2]={0},pointers[64]={0};
    if(!live_read(child,node+0x4c,children,sizeof(children))||children[1]>64||
       !live_read(child,children[0],pointers,children[1]*sizeof(DWORD))) return;
    for(DWORD i=0;i<children[1]&&*emitted<64;i++) live_controls(out,child,pointers[i],header[0],depth+1,emitted,visited);
}
static int live_identifier(HANDLE child,DWORD table,DWORD identifier,DWORD limit,unsigned length,char output[5]) {
    unsigned char text[5]={0};
    if(!table||identifier==0||identifier>=limit||length<1||length>4||
       table>0xffff0000u-limit*sizeof(DWORD))return 0;
    DWORD address=live_word(child,table+identifier*sizeof(DWORD));
    if(!address||!live_read(child,address,text,length+1)||text[length])return 0;
    for(unsigned i=0;i<length;i++)
        if(!((text[i]>='A'&&text[i]<='Z')||(text[i]>='a'&&text[i]<='z')||(text[i]>='0'&&text[i]<='9')))return 0;
    memcpy(output,text,length+1);return 1;
}
static void live_scene(FILE* out,HANDLE child,DWORD services,DWORD layer,DWORD type,const LiveStateConfig* config) {
    DWORD current=services ? live_word(child,services+0x60) : 0;
    DWORD identifiers[2]={0};char location[5]={0},time[5]={0};
    int known=current&&live_read(child,current+0x10,identifiers,sizeof(identifiers));
    // During a time-block card, the visible target can precede gameplay state.
    if(known&&config->timeType&&type==config->timeType)
        known=live_read(child,layer+0x3cc,&identifiers[1],sizeof(DWORD));
    if(known&&live_identifier(child,config->locationNames,identifiers[0],84,3,location)&&
       live_identifier(child,config->timeNames,identifiers[1],18,4,time))
        fprintf(out,"\"scene\":{\"location\":\"%s\",\"timeblock\":\"%s\"},",location,time);
    else fputs("\"scene\":null,",out);
}
static void live_write(FILE* out,HANDLE child,DWORD pid,const LiveStateConfig* config,const char* token) {
    DWORD engine=live_word(child,config->engine);
    DWORD services=engine ? live_word(child,engine+0x444) : 0;
    DWORD manager=services ? live_word(child,services+0x44) : 0;
    DWORD layer=manager ? live_word(child,manager+0x58) : 0;
    if(manager&&!layer) {
        DWORD end=live_word(child,manager+0x44);
        if(end>=16) layer=live_word(child,end-16);
    }
    DWORD type=layer ? live_word(child,layer) : 0;
    HWND foreground=GetForegroundWindow();DWORD foregroundPid=0;wchar_t foregroundClass[64]={0};
    if(foreground){GetWindowThreadProcessId(foreground,&foregroundPid);GetClassNameW(foreground,foregroundClass,64);}
    fprintf(out,"{\"token\":\"%s\",\"pid\":%lu,\"tick_ms\":%llu,\"layer_type\":%lu,\"reader\":\"%s\",",
        token,pid,(unsigned long long)GetTickCount64(),type,child==GetCurrentProcess() ? "self" : "remote");
    live_scene(out,child,services,layer,type,config);
    // This observes an active Draw scope, not whether an unobserved console
    // is closed. Never turn a missing/transient owner into visibility proof.
    DWORD console=live_word(child,config->consoleScope),consoleHeader[11]={0};
    if(config->consoleType&&console&&live_read(child,console,consoleHeader,sizeof(consoleHeader))&&consoleHeader[0]==config->consoleType) {
        fprintf(out,"\"console_draw\":{\"flags\":%lu,\"visible\":%s,\"rect\":[%ld,%ld,%ld,%ld]},",
            consoleHeader[6],(consoleHeader[6]&255) ? "true" : "false",(LONG)consoleHeader[7],(LONG)consoleHeader[8],(LONG)consoleHeader[9],(LONG)consoleHeader[10]);
    }
    else fputs("\"console_draw\":null,",out);
    // Game::OnKeyDown and Console::Show use this same owned mini-console.
    // Resolve it fresh from its actual owner, including between Draw scopes.
    // Unknown/unreadable is not closed. No historical object cache is needed.
    DWORD ownedConsole=0;
    if(services&&live_read(child,services+0x4c,&ownedConsole,sizeof(ownedConsole)))
        fprintf(out,"\"console_present\":%s,",ownedConsole ? "true" : "false");
    else fputs("\"console_present\":null,",out);
    if(config->consoleType&&ownedConsole&&live_read(child,ownedConsole,consoleHeader,sizeof(consoleHeader))&&consoleHeader[0]==config->consoleType) {
        fprintf(out,"\"console_state\":{\"visible\":%s},",(consoleHeader[6]&255) ? "true" : "false");
        fprintf(out,"\"owned_console\":{\"address\":%lu,\"matches_draw\":%s,\"visible\":%s},",
            ownedConsole,ownedConsole==console ? "true" : "false",(consoleHeader[6]&255) ? "true" : "false");
    } else fputs("\"console_state\":null,\"owned_console\":null,",out);
    DWORD modifiers=0;
    if(engine&&live_read(child,engine+0x518,&modifiers,sizeof(modifiers)))fprintf(out,"\"key_modifiers\":%lu,",modifiers);
    else fputs("\"key_modifiers\":null,",out);
    fprintf(out,"\"game_foreground\":%s,",foregroundPid==pid&&!wcscmp(foregroundClass,L"SierraGEngineWindow") ? "true" : "false");
    fputs("\"controls\":[",out);
    unsigned emitted=0;DWORD visited[64]={0};
    if(layer) live_controls(out,child,layer,0,0,&emitted,visited);
    fputs("],\"rows\":[",out);
    const char* rowsStatus="not_applicable";
    DWORD rowsExpected=0,rowsRead=0;int rowsKnown=0;
    DWORD failedRow=0,failedBox=0,failedReadError=0;int failedProbe=-1;
    if(layer&&type&&(type==config->saveType||type==config->restoreType)) {
        DWORD rows[2]={0};
        rowsStatus="unreadable_range";
        if(live_read(child,layer+0x2b4,rows,sizeof(rows))) {
            rowsStatus="invalid_range";
            if(rows[1]>=rows[0]&&(rows[1]-rows[0])%0x4c==0) {
                rowsExpected=(rows[1]-rows[0])/0x4c;rowsKnown=1;
                rowsStatus=rowsExpected>64 ? "limit_exceeded" : "complete";
            }
        }
        if(rowsKnown&&rowsExpected<=64) {
            for(DWORD row=rows[0];row<rows[1];row+=0x4c) {
                DWORD box=0,rect[4]={0};
                if(!live_read(child,row+0x20,&box,sizeof(box))) {rowsStatus="unreadable_item";break;}
                if(!box) {rowsStatus="missing_item";break;}
                if(!live_read(child,box+0x1c,rect,sizeof(rect))) {
                    rowsStatus="unreadable_rectangle";failedRow=row;failedBox=box;
                    /* Diagnose a rejected address without changing the reader's
                     * policy or treating the probe as a usable catalog entry. */
                    if(box<=0xffffffffu-0x1c-sizeof(rect)) {
                        SIZE_T copied=0;SetLastError(0);
                        failedProbe=ReadProcessMemory(child,(void*)(uintptr_t)(box+0x1c),rect,sizeof(rect),&copied)&&copied==sizeof(rect);
                        failedReadError=GetLastError();
                    }
                    break;
                }
                if(rowsRead) fputc(',',out);
                fprintf(out,"{\"rect\":[%ld,%ld,%ld,%ld],\"name\":",(LONG)rect[0],(LONG)rect[1],(LONG)rect[2],(LONG)rect[3]);
                int nameKnown=live_string(out,child,box,0x3c);fputc('}',out);rowsRead++;
                if(!nameKnown) {rowsStatus="unreadable_name";break;}
            }
        }
    }
    /* A failed/bounded observation is not proof of an empty native catalog.
     * A readable zero-length range still says nothing about async scan completion. */
    fprintf(out,"],\"rows_status\":\"%s\",\"rows_read\":%lu,\"rows_expected\":",rowsStatus,rowsRead);
    if(rowsKnown) fprintf(out,"%lu",rowsExpected);else fputs("null",out);
    if(failedRow) fprintf(out,",\"rows_failure\":{\"row\":%lu,\"box\":%lu,\"direct_read\":%d,\"error\":%lu}",
        failedRow,failedBox,failedProbe,failedReadError);
    /* Read the whole fixed-width mailbox, including renderer availability and
     * returned intent. An empty editor alone cannot distinguish a missed
     * controller edge from native rejection. Never dereference bridge pointers. */
    DWORD text[23]={0};
    int hasText=config->text&&live_read(child,config->text,text,sizeof(text));
    if(!hasText) memset(text,0,sizeof(text));
    fprintf(out,",\"text_epoch\":%lu,\"text_accepted\":%lu,\"editor_type\":%lu,\"text\":",
        text[2],text[8],text[0] ? live_word(child,text[0]) : 0);
    live_string(out,child,text[0],0x34);
    fputs(",\"text_state\":[",out);
    if(hasText) for(unsigned i=0;i<23;i++) fprintf(out,i ? ",%lu" : "%lu",text[i]);
    fputc(']',out);
    fputs(",\"camera\":[",out);
    DWORD camera=services ? live_word(child,services+0x28) : 0;
    float values[5]={0};
    if(camera&&config->cameraType&&live_word(child,camera)==config->cameraType&&
       live_read(child,camera+0x13c,values,sizeof(values))) {
        int valid=1;for(unsigned i=0;i<5;i++) if(!isfinite(values[i])||fabs(values[i])>1000000) valid=0;
        if(valid) for(unsigned i=0;i<5;i++) fprintf(out,i ? ",%.9g" : "%.9g",values[i]);
    }
    fputs("],\"panel\":[",out);
    DWORD panel[47]={0};
    if(config->panel&&live_read(child,config->panel,panel,sizeof(panel)))
        for(unsigned i=0;i<47;i++) fprintf(out,i ? ",%lu" : "%lu",panel[i]);
    fputs("],\"panel_state\":[",out);
    DWORD panelState[18]={0};
    if(config->panelState&&live_read(child,config->panelState,panelState,sizeof(panelState)))
        for(unsigned i=0;i<18;i++) fprintf(out,i ? ",%lu" : "%lu",panelState[i]);
    fputs("],\"input_state\":[",out);
    DWORD inputState[34]={0};
    if(config->inputState&&live_read(child,config->inputState,inputState,sizeof(inputState)))
        for(unsigned i=0;i<34;i++) fprintf(out,i ? ",%lu" : "%lu",inputState[i]);
    fputs("],\"scene_frames\":",out);
    DWORD sceneFrames=0;
    if(config->sceneFrames&&live_read(child,config->sceneFrames,&sceneFrames,sizeof(sceneFrames)))
        fprintf(out,"%lu",sceneFrames);
    else fputs("null",out);
    fputs("}\n",out);
}
static int live_snapshot(HANDLE child,DWORD pid,const LiveStateConfig* config,const char* token) {
    FILE* out=fopen("standalone-state.tmp","w");if(!out) return 0;
    live_write(out,child,pid,config,token);
    int okay=!ferror(out);if(fclose(out)) okay=0;
    return okay&&MoveFileExA("standalone-state.tmp","standalone-state.json",MOVEFILE_REPLACE_EXISTING);
}
