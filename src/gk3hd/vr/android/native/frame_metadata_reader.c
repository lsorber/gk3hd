#include <jni.h>
#include "frame_metadata_reader.h"

JNIEXPORT jbyteArray JNICALL Java_org_gk3hd_standalone_MappedFrameMetadata_copy(JNIEnv* env,jclass type,jobject buffer){
    (void)type;
    if(!buffer)return NULL;
    void* address=(*env)->GetDirectBufferAddress(env,buffer);
    jlong capacity=(*env)->GetDirectBufferCapacity(env,buffer);
    if(capacity!=(jlong)GPMAP_BYTES)return NULL;
    uint8_t payload[GPMAP_PAYLOAD];
    if(!gpmap_copy(address,(size_t)capacity,payload))return NULL;
    jbyteArray output=(*env)->NewByteArray(env,GPMAP_PAYLOAD);
    if(output)(*env)->SetByteArrayRegion(env,output,0,GPMAP_PAYLOAD,(const jbyte*)payload);
    return output;
}
