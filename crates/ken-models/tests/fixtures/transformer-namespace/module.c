#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
extern int ken_namespace_bridge(void);
typedef struct { const uint8_t *ptr; size_t len; } KenBytes;
typedef struct { const uint8_t *ptr; size_t len; uint64_t allocation; } KenBuffer;
typedef struct {
    uint32_t abi_version, struct_bytes, backend, reserved;
    int32_t (*open)(KenBytes, uint64_t *, KenBuffer *);
    int32_t (*run)(uint64_t, KenBytes, KenBuffer *);
    int32_t (*close)(uint64_t);
    int32_t (*release)(KenBuffer *);
} KenModelApiV1;
static int32_t output(const char *json, KenBuffer *out) {
    size_t len = strlen(json); uint8_t *bytes = malloc(len);
    if (!bytes) return 1;
    memcpy(bytes, json, len); out->ptr = bytes; out->len = len;
    out->allocation = (uint64_t)(uintptr_t)bytes; return 0;
}
static int32_t model_open(KenBytes request, uint64_t *handle, KenBuffer *out) {
    (void)request; *handle = 1;
    return output("{\"core_version\":\"2.9.0\",\"device\":{\"kind\":\"cpu\"},\"dtype\":\"float32\",\"dimension\":2}", out);
}
static int32_t model_run(uint64_t handle, KenBytes request, KenBuffer *out) {
    (void)handle; (void)request;
    return output("{\"rows\":1,\"columns\":2,\"values\":[22,23]}", out);
}
static int32_t model_close(uint64_t handle) { (void)handle; return 0; }
static int32_t model_release(KenBuffer *buffer) {
    if (buffer->allocation != (uint64_t)(uintptr_t)buffer->ptr) return 1;
    free((void *)buffer->ptr); memset(buffer, 0, sizeof(*buffer)); return 0;
}
static KenModelApiV1 api = {1, sizeof(KenModelApiV1), 1, 0, model_open, model_run, model_close, model_release};
const KenModelApiV1 *ken_model_api_v1(void) {
    return ken_namespace_bridge() == 23 ? &api : NULL;
}
