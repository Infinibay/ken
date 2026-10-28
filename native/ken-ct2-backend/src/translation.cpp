// CPU adapter around the registered CTranslate2 core; no Python API is used.
#include "ken_translation_api.h"
#include <ctranslate2/translator.h>
#include <ken-ct2/backend.h>
#include <algorithm>
#include <climits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::string text(KenCt2Span span) {
  if (span.len && !span.data) throw std::invalid_argument("null token data");
  return span.len ? std::string(reinterpret_cast<const char*>(span.data), span.len) : std::string();
}
void bytes(KenCt2Buffer* output, const uint8_t* data, size_t len) {
  if (!output) throw std::invalid_argument("output buffer required");
  auto allocation = std::make_unique<uint8_t[]>(len);
  if (len) std::copy(data, data + len, allocation.get());
  *output = {allocation.release(), len};
}
template<class Action> uint32_t attempt(KenCt2Buffer* error, Action action) noexcept {
  if (!error) return 1;
  *error = {};
  try { action(); return 0; }
  catch (const std::exception& e) {
    try {
      const std::string message = e.what();
      bytes(error, reinterpret_cast<const uint8_t*>(message.data()), message.size());
    } catch (...) {}
  } catch (...) {
    try {
      const std::string message = "unknown native translation exception";
      bytes(error, reinterpret_cast<const uint8_t*>(message.data()), message.size());
    } catch (...) {}
  }
  return 1;
}
ctranslate2::ReplicaPoolConfig pool(const KenCt2Policy& policy) {
  ctranslate2::ReplicaPoolConfig config;
  config.num_threads_per_replica = policy.intra_threads;
  return config;
}
struct Session {
  ctranslate2::Translator translator;
  ctranslate2::TranslationOptions options;
  Session(const std::string& path, const KenCt2Policy& policy)
    : translator(path, ctranslate2::Device::CPU, ctranslate2::ComputeType::INT8,
                 {0}, false, pool(policy)) {
    options.beam_size = policy.beam_size;
    options.max_input_length = policy.max_input_length;
    options.max_decoding_length = policy.max_decoding_length;
  }
};
uint32_t info(KenCt2Info* output, KenCt2Buffer* error) noexcept {
  return attempt(error, [&] {
    if (!output) throw std::invalid_argument("native runtime info required");
    *output = {4, 8, 2,
      static_cast<uint32_t>(ctranslate2::cpu::get_gemm_backend(ctranslate2::ComputeType::FLOAT32)),
      static_cast<uint32_t>(ctranslate2::cpu::get_gemm_backend(ctranslate2::ComputeType::INT8))};
  });
}
uint32_t create(KenCt2Span path, const KenCt2Policy* policy, void** output, KenCt2Buffer* error) noexcept {
  if (output) *output = nullptr;
  return attempt(error, [&] {
    if (!output || !policy || !policy->intra_threads || policy->intra_threads > INT_MAX
        || policy->inter_threads != 1 || !policy->beam_size || !policy->max_input_length
        || !policy->max_decoding_length) throw std::invalid_argument("valid native translation policy required");
    auto directory = text(path);
    if (directory.empty() || directory.find('\0') != std::string::npos)
      throw std::invalid_argument("native model directory required");
    auto session = std::make_unique<Session>(directory, *policy);
    *output = session.release();
  });
}
void integer(std::vector<uint8_t>& out, uint64_t value) {
  for (unsigned i = 0; i != 8; ++i) out.push_back(static_cast<uint8_t>(value >> (i * 8)));
}
uint32_t translate(void* handle, const KenCt2Span* input, size_t count,
                   KenCt2Buffer* output, KenCt2Buffer* error) noexcept {
  if (output) *output = {};
  return attempt(error, [&] {
    if (!handle || !output || (count && !input)) throw std::invalid_argument("native session and token spans required");
    std::vector<std::string> tokens;
    tokens.reserve(count);
    for (size_t i = 0; i < count; ++i) tokens.push_back(text(input[i]));
    auto& session = *static_cast<Session*>(handle);
    const auto results = session.translator.translate_batch({tokens}, session.options);
    if (results.size() != 1 || results[0].hypotheses.size() != 1)
      throw std::runtime_error("native translator returned an invalid hypothesis count");
    const auto& hypothesis = results[0].hypotheses[0];
    std::vector<uint8_t> encoded;
    integer(encoded, hypothesis.size());
    for (const auto& token : hypothesis) {
      integer(encoded, token.size());
      encoded.insert(encoded.end(), token.begin(), token.end());
    }
    bytes(output, encoded.data(), encoded.size());
  });
}
size_t replicas(void* handle) noexcept {
  return handle ? static_cast<Session*>(handle)->translator.num_replicas() : 0;
}
void destroy(void* handle) noexcept { delete static_cast<Session*>(handle); }
void free_buffer(KenCt2Buffer buffer) noexcept { delete[] buffer.data; }
const KenTranslationApiV1 api = {1, sizeof(KenTranslationApiV1), info, create, translate,
                                replicas, destroy, free_buffer};
}
extern "C" const KenTranslationApiV1* ken_translation_api_v1(void) { return &api; }
