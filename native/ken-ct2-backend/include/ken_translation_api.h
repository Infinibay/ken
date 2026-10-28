#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef struct { const uint8_t* data; size_t len; } KenCt2Span;
typedef struct { uint8_t* data; size_t len; } KenCt2Buffer;
typedef struct {
  uint32_t intra_threads, inter_threads, beam_size, max_input_length, max_decoding_length;
} KenCt2Policy;
typedef struct {
  uint32_t major, minor, patch, float_backend, int8_backend;
} KenCt2Info;
typedef struct {
  uint32_t abi_version, struct_size;
  uint32_t (*info)(KenCt2Info*, KenCt2Buffer*);
  uint32_t (*create)(KenCt2Span, const KenCt2Policy*, void**, KenCt2Buffer*);
  uint32_t (*translate)(void*, const KenCt2Span*, size_t, KenCt2Buffer*, KenCt2Buffer*);
  size_t (*num_replicas)(void*);
  void (*destroy)(void*);
  void (*free_buffer)(KenCt2Buffer);
} KenTranslationApiV1;
__attribute__((visibility("default"))) const KenTranslationApiV1* ken_translation_api_v1(void);
#ifdef __cplusplus
}
#endif
