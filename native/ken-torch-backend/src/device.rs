//! Observed native software identity and original MPS allocator controls.
use crate::{CoreError, invalid};
use std::ffi::{CStr, c_char, c_int};

unsafe extern "C" {
    fn ken_torch_build_config(
        value: *mut c_char,
        capacity: usize,
        error: *mut c_char,
        error_capacity: usize,
    ) -> c_int;
    #[cfg(target_os = "macos")]
    fn ken_torch_mps_control(
        action: u32,
        memory: *mut MpsMemory,
        error: *mut c_char,
        capacity: usize,
    ) -> c_int;
}

#[derive(Default, Clone, Copy, Debug)]
#[repr(C)]
pub struct MpsMemory {
    pub allocated_bytes: usize,
    pub driver_bytes: usize,
    pub recommended_bytes: usize,
    pub high_watermark_bytes: usize,
}

pub fn core_version() -> Result<String, CoreError> {
    let mut value = vec![0_u8; 64 * 1024];
    let mut error = [0_u8; 1024];
    // SAFETY: both initialized writable buffers have their exact supplied sizes;
    // the private C++ bridge contains every exception and bounds all writes.
    let status = unsafe {
        ken_torch_build_config(
            value.as_mut_ptr().cast(),
            value.len(),
            error.as_mut_ptr().cast(),
            error.len(),
        )
    };
    if status != 0 {
        return Err(invalid(message(&error)));
    }
    let config = message(&value);
    let version = config
        .split("TORCH_VERSION=")
        .nth(1)
        .and_then(|v| v.split(|c: char| c == ',' || c.is_whitespace()).next())
        .filter(|v| !v.is_empty())
        .ok_or_else(|| invalid("executing native core did not report its version"))?;
    Ok(version.into())
}

pub fn prepare_mps() -> Result<MpsMemory, CoreError> {
    mps_control(0)
}
pub fn empty_mps_cache() -> Result<MpsMemory, CoreError> {
    mps_control(1)
}

#[cfg(target_os = "macos")]
fn mps_control(action: u32) -> Result<MpsMemory, CoreError> {
    if !tch::utils::has_mps() {
        return Err(invalid("MPS unavailable"));
    }
    let mut memory = MpsMemory::default();
    let mut error = [0_u8; 1024];
    // SAFETY: initialized aligned statistics and bounded error storage remain
    // live throughout the exception-contained call to the actual MPS hooks.
    let status = unsafe {
        ken_torch_mps_control(action, &mut memory, error.as_mut_ptr().cast(), error.len())
    };
    if status != 0 {
        return Err(invalid(message(&error)));
    }
    Ok(memory)
}

#[cfg(not(target_os = "macos"))]
fn mps_control(_action: u32) -> Result<MpsMemory, CoreError> {
    Err(invalid("MPS unavailable on this platform"))
}

fn message(bytes: &[u8]) -> String {
    CStr::from_bytes_until_nul(bytes)
        .map(|v| v.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "invalid bounded native diagnostic".into())
}
