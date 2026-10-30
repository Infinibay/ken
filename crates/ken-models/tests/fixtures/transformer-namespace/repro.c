#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef struct { const uint8_t *ptr; size_t len; } KenBytes;
typedef struct { const uint8_t *ptr; size_t len; uint64_t allocation; } KenBuffer;
typedef struct { uint32_t version, bytes, backend, reserved;
 int32_t(*open)(KenBytes,uint64_t*,KenBuffer*);int32_t(*run)(uint64_t,KenBytes,KenBuffer*);
 int32_t(*close)(uint64_t);int32_t(*release)(KenBuffer*); } Api;
static void *required(void *handle) { if (!handle) { fprintf(stderr,"%s\n",dlerror()); } return handle; }
int main(int argc,char **argv) {
 if (argc != 6) return 2;
 void *host=required(dlopen(argv[2],RTLD_NOW|RTLD_GLOBAL));if(!host)return 3;
 int (*marker)(void)=dlsym(host,"ken_namespace_marker");if(!marker||marker()!=11)return 4;
 void *leaf=NULL,*bridge=NULL,*module=NULL;
 if(!strcmp(argv[1],"plain")) module=required(dlopen(argv[5],RTLD_NOW|RTLD_LOCAL));
 else if(!strcmp(argv[1],"naive")) module=required(dlmopen(LM_ID_NEWLM,argv[5],RTLD_NOW|RTLD_LOCAL));
 else {
   leaf=required(dlmopen(LM_ID_NEWLM,argv[3],RTLD_NOW|RTLD_LOCAL));if(!leaf)return 5;
   Lmid_t ns; if(dlinfo(leaf,RTLD_DI_LMID,&ns))return 6;
   bridge=required(dlmopen(ns,argv[4],RTLD_NOW|RTLD_LOCAL));if(!bridge)return 7;
   module=required(dlmopen(ns,argv[5],RTLD_NOW|RTLD_LOCAL));
 }
 if(!module)return 8;
 const Api*(*get)(void)=dlsym(module,"ken_model_api_v1");const Api *api=get?get():NULL;
 if(!api){fprintf(stderr,"wrong same-SONAME dependency selected\n");return 41;}
 KenBuffer out={0};uint64_t handle=0;KenBytes input={(const uint8_t*)"{}",2};
 if(api->open(input,&handle,&out)||!out.ptr||api->release(&out)||api->run(handle,input,&out)||api->release(&out)||api->close(handle))return 9;
 if(marker()!=11)return 10;
 dlclose(module);if(bridge)dlclose(bridge);if(leaf)dlclose(leaf);dlclose(host);
 puts("isolated dependency binding and backend allocation/release preserved");return 0;
}
