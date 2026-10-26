//! Effective selectors relevant to the pinned x86 MLAS numerical implementation.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub fn features() -> Vec<(&'static str, bool)> {
    let avx2 = std::is_x86_feature_detected!("avx2");
    // CPUID is available on supported x86_64 targets; leaf7 data is only
    // used as feature bits, and AVX variants also require OS-supported AVX2.
    let (leaf, sub) = {
        (std::arch::x86_64::__cpuid_count(7, 0), std::arch::x86_64::__cpuid_count(7, 1))
    };
    vec![
        ("sse41", std::is_x86_feature_detected!("sse4.1")),
        ("avx", std::is_x86_feature_detected!("avx")),
        ("avx2", avx2),
        ("fma", std::is_x86_feature_detected!("fma")),
        ("f16c", std::is_x86_feature_detected!("f16c")),
        ("avx512f", std::is_x86_feature_detected!("avx512f")),
        ("avx512bw", std::is_x86_feature_detected!("avx512bw")),
        ("avx512dq", std::is_x86_feature_detected!("avx512dq")),
        ("avx512vl", std::is_x86_feature_detected!("avx512vl")),
        ("avx512vnni", std::is_x86_feature_detected!("avx512vnni")),
        ("avx_vnni", avx2 && leaf.eax >= 1 && sub.eax & (1 << 4) != 0),
        ("avx_vnni_int8", avx2 && leaf.eax >= 1 && sub.edx & (1 << 4) != 0),
        ("amx_tile_hardware", leaf.edx & (1 << 24) != 0),
        ("amx_int8_hardware", leaf.edx & (1 << 25) != 0),
        ("hybrid", leaf.edx & (1 << 15) != 0),
    ]
}
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub fn json() -> String {
    let fields = features().into_iter().map(|(name, value)| format!("\"{name}\":{value}")).collect::<Vec<_>>().join(",");
    format!("{{\"format\":\"ken-x86-capabilities/1\",\"target\":\"linux-x86_64\",\"features\":{{{fields}}}}}")
}
