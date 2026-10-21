// Exact libtorch APIs; owned fixed buffers cross this internal C boundary.
#include <ATen/Version.h>
#ifdef __APPLE__
#include <ATen/detail/MPSHooksInterface.h>
#include <ATen/mps/MPSAllocatorInterface.h>
#endif
#include <cstdio>
#include <exception>
#include <stdexcept>

extern "C" int ken_torch_build_config(char* value, size_t capacity, char* error,
                                    size_t error_capacity) noexcept {
  try {
    if (!value || capacity == 0) throw std::invalid_argument("missing build configuration output");
    const auto config = at::show_config();
    if (config.size() >= capacity) throw std::runtime_error("native build configuration exceeds bound");
    std::snprintf(value, capacity, "%s", config.c_str());
    return 0;
  } catch (const std::exception& failure) {
    if (error && error_capacity) std::snprintf(error, error_capacity, "%s", failure.what());
    return 1;
  } catch (...) {
    if (error && error_capacity) std::snprintf(error, error_capacity, "unknown native configuration failure");
    return 1;
  }
}

#ifdef __APPLE__
struct KenMpsMemory {
  size_t allocated_bytes;
  size_t driver_bytes;
  size_t recommended_bytes;
  size_t high_watermark_bytes;
};

extern "C" int ken_torch_mps_control(unsigned action, KenMpsMemory* memory,
                                   char* error, size_t capacity) noexcept {
  try {
    if (!memory) throw std::invalid_argument("missing MPS statistics output");
    const auto& hooks = at::detail::getMPSHooks();
    if (action == 0) hooks.setMemoryFraction(0.7);
    else if (action == 1) hooks.emptyCache();
    else throw std::invalid_argument("unknown MPS control operation");
    auto* allocator = at::mps::getIMPSAllocator();
    if (!allocator) throw std::runtime_error("MPS allocator unavailable");
    *memory = {hooks.getCurrentAllocatedMemory(), hooks.getDriverAllocatedMemory(),
               hooks.getRecommendedMaxMemory(), allocator->getHighWatermarkLimit()};
    return 0;
  } catch (const std::exception& failure) {
    if (error && capacity) std::snprintf(error, capacity, "%s", failure.what());
    return 1;
  } catch (...) {
    if (error && capacity) std::snprintf(error, capacity, "unknown native MPS failure");
    return 1;
  }
}
#endif
