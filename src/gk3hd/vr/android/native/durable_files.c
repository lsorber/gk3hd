#define _GNU_SOURCE
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

/* The Java caller verifies ownership and persists the prepared tree first. */
JNIEXPORT void JNICALL
Java_org_gk3hd_standalone_DurableFiles_renamePaths(JNIEnv* env,jclass type,jstring staged,jstring target,jboolean exchange) {
    (void)type;
    const char* a=(*env)->GetStringUTFChars(env,staged,NULL);
    if(!a)return;
    const char* b=(*env)->GetStringUTFChars(env,target,NULL);
    if(!b) {(*env)->ReleaseStringUTFChars(env,staged,a);return;}
    unsigned int flags=exchange?RENAME_EXCHANGE:RENAME_NOREPLACE;
    int result=(int)syscall(SYS_renameat2,AT_FDCWD,a,AT_FDCWD,b,flags);
    int error=errno;
    (*env)->ReleaseStringUTFChars(env,target,b);
    (*env)->ReleaseStringUTFChars(env,staged,a);
    if(result) {
        char message[256];
        snprintf(message,sizeof(message),"Cannot atomically update this player: %s",strerror(error));
        (*env)->ThrowNew(env,(*env)->FindClass(env,"java/io/IOException"),message);
    }
}
