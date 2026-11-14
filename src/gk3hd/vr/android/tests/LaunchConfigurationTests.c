/* Exercise the actual launcher parser without creating a child or using XR. */
#define main Gk3hdLauncherMain
#include "../WineLauncher.c"
#undef main

#define REQUIRE(test) do {if(!(test)){fprintf(stderr,"Failed: %s\n",#test);return 1;}} while(0)

static FILE* configuration(unsigned count,const char* replacement,unsigned at,const char* suffix) {
    FILE* file=tmpfile();if(!file) return NULL;
    fprintf(file,"%u\n",count);
    for(unsigned i=0;i<count;i++) {
        if(replacement&&i==at) fprintf(file,"%s\n",replacement);
        else fprintf(file,"%x\n",0x400000+4*i);
    }
    if(suffix) fputs(suffix,file);
    rewind(file);return file;
}

int main(void) {
    DWORD words[MAX_LAUNCH_SWITCHES]={0};unsigned count=0,checks=0;
    for(unsigned wanted=9;wanted<=MAX_LAUNCH_SWITCHES;wanted++) {
        FILE* file=configuration(wanted,NULL,0,"\n \t\r\n");REQUIRE(file);
        REQUIRE(read_launch_switches(file,words,&count));fclose(file);
        REQUIRE(count==wanted);
        for(unsigned i=0;i<count;i++) REQUIRE(words[i]==0x400000+4*i);
        checks++;
    }
    const char* invalid[]={"0","3ffffc","8000000","400001","-ffbffffc","+400000","xyz","ffffffffffffffffffffffffffffffffffffffff"};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        FILE* file=configuration(10,invalid[i],9,NULL);REQUIRE(file);
        count=0;REQUIRE(!read_launch_switches(file,words,&count));fclose(file);
        REQUIRE(count==0);checks++;
    }
    FILE* duplicate=configuration(10,"400000",9,NULL);REQUIRE(duplicate);
    REQUIRE(!read_launch_switches(duplicate,words,&count));fclose(duplicate);checks++;
    FILE* trailing=configuration(10,NULL,0,"400040\n");REQUIRE(trailing);
    REQUIRE(!read_launch_switches(trailing,words,&count));fclose(trailing);checks++;
    for(unsigned bad=0;bad<=MAX_LAUNCH_SWITCHES+1;bad++) {
        if(bad>=9&&bad<=MAX_LAUNCH_SWITCHES) continue;
        FILE* file=configuration(bad,NULL,0,NULL);REQUIRE(file);
        REQUIRE(!read_launch_switches(file,words,&count));fclose(file);checks++;
    }
    FILE* shortFile=configuration(9,NULL,0,NULL);REQUIRE(shortFile);
    /* One extra declared word without a tenth payload is rejected. */
    FILE* incomplete=tmpfile();REQUIRE(incomplete);fputs("10\n",incomplete);
    char line[32];REQUIRE(fgets(line,sizeof(line),shortFile));
    while(fgets(line,sizeof(line),shortFile)) fputs(line,incomplete);
    rewind(incomplete);REQUIRE(!read_launch_switches(incomplete,words,&count));
    fclose(shortFile);fclose(incomplete);checks++;
    puts("Standalone activation: core/explicit stereo output, bounds, uniqueness, alignment and malformed/truncated input passed");
    printf("%u launcher configuration cases passed; no child or XR runtime started\n",checks);
    return 0;
}
