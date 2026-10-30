//! Profile-specific NumPy2.4.4 FLOAT ArgQSort/ArgQSelect, not a stable sort.
use super::{Result, RetrievalError};
use std::ffi::{CStr, c_char};
const PROFILE: &str = "numpy-2.4.4-linux-x86-v3";
const COMMIT: &str = "5adb33411f3cea8bdbafa9d91bd75bc4bf19c7dd";
unsafe extern "C" {
    fn ken_vector_sort_fallback(
        values: *const f32,
        indices: *mut usize,
        len: usize,
        partition: bool,
        kth: usize,
    ) -> i32;
    fn ken_vector_sort_compiler() -> *const c_char;
    fn ken_vector_sort_stdlib() -> u64;
    fn ken_vector_sort_gnu_version() -> u32;
}
#[derive(Clone, Debug, serde::Serialize)]
pub struct OrderingIdentity {
    pub profile: String,
    pub compiler: String,
    pub stdlib: u64,
    pub source_commit: String,
    pub original_compiler: String,
}
fn unsupported(message: &str) -> RetrievalError {
    RetrievalError::Version(format!(
        "unqualified NumPy float32 ordering profile: {message}"
    ))
}
pub(super) fn profile() -> Result<&'static str> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        if !std::is_x86_feature_detected!("avx2")
            || !std::is_x86_feature_detected!("fma")
            || !std::is_x86_feature_detected!("bmi1")
            || !std::is_x86_feature_detected!("bmi2")
            || !std::is_x86_feature_detected!("f16c")
            || !std::is_x86_feature_detected!("lzcnt")
            || std::is_x86_feature_detected!("avx512f")
        {
            return Err(unsupported(
                "requires the registered Linux x86-V3 CPU dispatcher",
            ));
        }
        // The fallback's actual compiler remains part of the qualified identity.
        // A different standard library must pass a new exact permutation capture.
        if unsafe { ken_vector_sort_gnu_version() } != ((16 << 16) | (2 << 8) | 1)
            || unsafe { ken_vector_sort_stdlib() } == 0
        {
            return Err(unsupported(
                "requires the qualified GNU16.2.1 standard-library fallback",
            ));
        }
        Ok(PROFILE)
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        Err(unsupported("only Linux x86-V3 is registered"))
    }
}
pub(super) fn identity() -> Result<OrderingIdentity> {
    profile()?;
    let compiler = unsafe {
        let pointer = ken_vector_sort_compiler();
        if pointer.is_null() {
            return Err(unsupported("missing compiler identity"));
        }
        CStr::from_ptr(pointer)
            .to_str()
            .map_err(|_| unsupported("invalid compiler identity"))?
            .to_owned()
    };
    Ok(OrderingIdentity {
        profile: PROFILE.into(),
        compiler,
        stdlib: unsafe { ken_vector_sort_stdlib() },
        source_commit: COMMIT.into(),
        original_compiler: "GCC14.2.1 (NumPy2.4.4 wheel)".into(),
    })
}
fn fallback(values: &[f32], indices: &mut [usize], kth: Option<usize>) -> Result<()> {
    if indices.len() < 2 {
        return Ok(());
    }
    debug_assert!(indices.iter().all(|i| *i < values.len()));
    // SAFETY: values is immutable, indices is a disjoint owned permutation with
    // readable/writable len elements; every index and optional kth is in bounds.
    let result = unsafe {
        ken_vector_sort_fallback(
            values.as_ptr(),
            indices.as_mut_ptr(),
            indices.len(),
            kth.is_some(),
            kth.unwrap_or(0),
        )
    };
    if result == 0 {
        Ok(())
    } else {
        Err(super::invalid("native index fallback rejected its shape"))
    }
}
fn initial(len: usize) -> Result<Vec<usize>> {
    let mut indices = vec![];
    indices
        .try_reserve_exact(len)
        .map_err(|e| super::invalid(format!("index ordering allocation: {e}")))?;
    indices.extend(0..len);
    Ok(indices)
}
fn validate(indices: &[usize], len: usize) -> Result<()> {
    let mut seen = vec![false; len];
    for index in indices {
        if *index >= len || seen[*index] {
            return Err(super::invalid("native index ordering is not a permutation"));
        }
        seen[*index] = true;
    }
    Ok(())
}
pub(super) fn descending(values: &[f32]) -> Result<Vec<usize>> {
    profile()?;
    let negated: Vec<_> = values.iter().map(|value| -value).collect();
    let mut indices = initial(values.len())?;
    if negated.iter().any(|v| v.is_nan()) {
        fallback(&negated, &mut indices, None)?;
    } else if negated.windows(2).any(|v| v[1] < v[0]) {
        run(&negated, &mut indices, None)?;
    }
    validate(&indices, values.len())?;
    Ok(indices)
}
pub(super) fn select(values: &[f32], kth: usize) -> Result<Vec<usize>> {
    profile()?;
    if values.is_empty() {
        return Ok(vec![]);
    }
    if kth >= values.len() {
        return Err(super::invalid("partition kth is outside the vector"));
    }
    let mut indices = initial(values.len())?;
    if values.iter().any(|v| v.is_nan()) {
        fallback(values, &mut indices, Some(kth))?;
    } else {
        run(values, &mut indices, Some(kth))?;
    }
    validate(&indices, values.len())?;
    Ok(indices)
}
fn run(values: &[f32], indices: &mut [usize], kth: Option<usize>) -> Result<()> {
    if indices.len() < 2 {
        return Ok(());
    }
    let mut pending = vec![(0, indices.len(), 2 * indices.len().ilog2())];
    while let Some((begin, end, depth)) = pending.pop() {
        if depth == 0 {
            fallback(values, &mut indices[begin..end], None)?;
            continue;
        }
        if end - begin <= 256 {
            super::network::sort(values, &mut indices[begin..end]);
            continue;
        }
        let pivot = super::network::median(values, indices, begin, end);
        let (middle, smallest, biggest) =
            super::partition::partition(values, indices, begin, end, pivot);
        if pivot != biggest && kth.is_none_or(|k| k >= middle) {
            pending.push((middle, end, depth - 1));
        }
        if pivot != smallest && kth.is_none_or(|k| k < middle) {
            pending.push((begin, middle, depth - 1));
        }
    }
    Ok(())
}
