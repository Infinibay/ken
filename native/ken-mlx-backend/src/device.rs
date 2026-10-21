//! Executing MLX identity and hardware availability, without Python.
use crate::{CoreError, invalid};
use std::ffi::CStr;
pub fn core_version() -> Result<String, CoreError> {
    // SAFETY: native string constructors own a valid handle; free is called on
    // both success and failure, after copying any borrowed UTF-8 bytes.
    unsafe {
        let mut text = mlx_sys::mlx_string_new();
        let status = mlx_sys::mlx_version(&mut text);
        let result = if status != 0 {
            Err(invalid("MLX did not report its version"))
        } else {
            let pointer = mlx_sys::mlx_string_data(text);
            if pointer.is_null() {
                Err(invalid("MLX returned no version string"))
            } else {
                CStr::from_ptr(pointer)
                    .to_str()
                    .map(str::to_owned)
                    .map_err(|_| invalid("invalid native MLX version"))
            }
        };
        mlx_sys::mlx_string_free(text);
        result
    }
}
pub fn gpu_available() -> Result<bool, CoreError> {
    let mut available = false;
    // SAFETY: initialized writable bool remains live through the bounded call.
    if unsafe { mlx_sys::mlx_metal_is_available(&mut available) } != 0 {
        return Err(invalid("MLX GPU availability query failed"));
    }
    Ok(available)
}

use std::{
    ffi::CString,
    os::unix::ffi::OsStrExt,
    path::{Path, PathBuf},
    sync::Mutex,
};
static MEMORY_LOCK: Mutex<()> = Mutex::new(());
/// Bound only retired buffers; never raise a lower caller cap or live limit.
pub fn bound_free_cache() -> Result<(), CoreError> {
    let _lock = MEMORY_LOCK
        .lock()
        .map_err(|_| invalid("MLX memory policy lock poisoned"))?;
    let maximum = 512 * 1024 * 1024;
    let prior = mlx_rs::memory::set_cache_limit(maximum)?;
    if prior < maximum {
        mlx_rs::memory::set_cache_limit(prior)?;
    }
    Ok(())
}
fn configure_shader(path: &Path) -> Result<(), CoreError> {
    let file = std::fs::File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid("registered MLX shader is missing or empty"));
    }
    let name = CString::new(path.as_os_str().as_bytes())
        .map_err(|_| invalid("invalid MLX shader path"))?;
    // SAFETY: nul-terminated owned path is live throughout the exception-contained call.
    if unsafe { mlx_sys::mlx_metal_set_metallib_path(name.as_ptr()) } != 0 {
        return Err(invalid("MLX rejected the registered shader path"));
    }
    Ok(())
}
fn module_directory() -> Result<PathBuf, CoreError> {
    let mut info = std::mem::MaybeUninit::<libc::Dl_info>::zeroed();
    // SAFETY: dladdr receives an address inside this module and aligned output
    // storage. We copy its borrowed filename while the module remains mapped.
    let status = unsafe {
        libc::dladdr(
            crate::ken_model_api_v1 as *const () as *const libc::c_void,
            info.as_mut_ptr(),
        )
    };
    if status == 0 {
        return Err(invalid("MLX module location unavailable"));
    }
    let info = unsafe { info.assume_init() };
    if info.dli_fname.is_null() {
        return Err(invalid("MLX module filename unavailable"));
    }
    let path = PathBuf::from(std::ffi::OsStr::from_bytes(
        unsafe { CStr::from_ptr(info.dli_fname) }.to_bytes(),
    ));
    path.parent()
        .filter(|p| p.is_absolute())
        .map(Path::to_path_buf)
        .ok_or_else(|| invalid("absolute MLX module location required"))
}
pub(crate) fn prepare() -> Result<(), CoreError> {
    if core_version()? != "0.32.3" {
        return Err(invalid("executing MLX core version mismatch"));
    }
    if !gpu_available()? {
        return Err(invalid("actual MLX Apple GPU unavailable"));
    }
    configure_shader(&module_directory()?.join("lib/mlx.metallib"))?;
    bound_free_cache()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn absent_shader_fails_before_a_global_path_change() {
        let directory = tempfile::tempdir().unwrap();
        assert!(configure_shader(&directory.path().join("mlx.metallib")).is_err());
        std::fs::write(directory.path().join("empty.metallib"), b"").unwrap();
        assert!(configure_shader(&directory.path().join("empty.metallib")).is_err());
    }
    #[test]
    fn cache_bound_preserves_lower_limits_and_live_memory_limit() {
        let original = mlx_rs::memory::set_cache_limit(0).unwrap();
        let host = mlx_rs::memory::memory_limit().unwrap();
        for prior in [0, 64 * 1024 * 1024, 1024 * 1024 * 1024] {
            mlx_rs::memory::set_cache_limit(prior).unwrap();
            bound_free_cache().unwrap();
            let actual = mlx_rs::memory::set_cache_limit(prior).unwrap();
            assert_eq!(actual, prior.min(512 * 1024 * 1024));
        }
        mlx_rs::memory::set_cache_limit(original).unwrap();
        assert_eq!(mlx_rs::memory::memory_limit().unwrap(), host);
    }
}
