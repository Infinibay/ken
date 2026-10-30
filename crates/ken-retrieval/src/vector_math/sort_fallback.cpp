// The original Intel x86-simd-sort uses these standard-library fallbacks.
// Keep them as library calls: no libstdc++ implementation is vendored here.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
extern "C" int ken_vector_sort_fallback(const float *values, std::size_t *indices,
                                      std::size_t len, bool partition, std::size_t kth) noexcept {
    if (len < 2) return 0;
    if (!values || !indices || (partition && kth >= len)) return 1;
    auto less = [values](std::size_t a, std::size_t b) {
        if (std::isnan(values[a])) return false;
        if (std::isnan(values[b])) return true;
        return values[a] < values[b];
    };
    if (partition) std::nth_element(indices, indices + kth, indices + len, less);
    else std::sort(indices, indices + len, less);
    return 0;
}
extern "C" const char *ken_vector_sort_compiler() noexcept { return __VERSION__; }
extern "C" std::uint64_t ken_vector_sort_stdlib() noexcept {
#ifdef __GLIBCXX__
    return __GLIBCXX__;
#else
    return 0;
#endif
}
extern "C" std::uint32_t ken_vector_sort_gnu_version() noexcept {
#if defined(__GNUC__) && !defined(__clang__)
    return (__GNUC__ << 16) | (__GNUC_MINOR__ << 8) | __GNUC_PATCHLEVEL__;
#else
    return 0;
#endif
}
