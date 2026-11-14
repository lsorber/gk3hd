#pragma once
#include <windows.h>

/* The standalone launcher owns this unnamed, non-inherited job. If its host
 * kills the launcher, closing its last handle also stops only its game child
 * and descendants. Unrelated Wine processes are never assigned to it. */
static HANDLE standalone_child_job(void) {
    HANDLE job=CreateJobObjectW(NULL,NULL);
    if(!job) return NULL;
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits={0};
    limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if(!SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,(DWORD)sizeof(limits))) {
        DWORD error=GetLastError();CloseHandle(job);SetLastError(error);return NULL;
    }
    return job;
}
