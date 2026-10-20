//! C-compatible values only; allocation ownership never crosses this boundary.
use crate::{ApiError, MAX_PAYLOAD};

/// Borrowed bytes. The caller keeps their storage live until the call returns.
#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct KenBytes {
    pub ptr: *const u8,
    pub len: usize,
}

impl KenBytes {
    pub fn new(bytes: &[u8]) -> Result<Self, ApiError> {
        if bytes.len() > MAX_PAYLOAD {
            return Err(ApiError::Invalid("payload exceeds bound".into()));
        }
        Ok(Self {
            ptr: bytes.as_ptr(),
            len: bytes.len(),
        })
    }
}

/// Backend-owned immutable output, released only by the backend's release call.
/// `allocation` is an opaque registry token, never a cast Rust object pointer.
#[derive(Clone, Copy, Debug)]
#[repr(C)]
pub struct KenBuffer {
    pub ptr: *const u8,
    pub len: usize,
    pub allocation: u64,
}

impl KenBuffer {
    pub const EMPTY: Self = Self {
        ptr: std::ptr::null(),
        len: 0,
        allocation: 0,
    };
}

impl Default for KenBuffer {
    fn default() -> Self {
        Self::EMPTY
    }
}

pub type OpenFn = unsafe extern "C" fn(KenBytes, *mut u64, *mut KenBuffer) -> i32;
pub type RunFn = unsafe extern "C" fn(u64, KenBytes, *mut KenBuffer) -> i32;
pub type CloseFn = unsafe extern "C" fn(u64) -> i32;
pub type ReleaseFn = unsafe extern "C" fn(*mut KenBuffer) -> i32;
pub type GetApiV1 = unsafe extern "C" fn() -> *const KenModelApiV1;

/// Nullable slots let the host validate an incomplete foreign table without
/// creating an invalid Rust non-null function-pointer value. A validated table
/// has all four slots. Its code remains usable only while its library is mapped.
#[derive(Clone, Copy)]
#[repr(C)]
pub struct KenModelApiV1 {
    pub abi_version: u32,
    pub struct_bytes: u32,
    pub backend: u32,
    pub reserved: u32,
    pub open: Option<OpenFn>,
    pub run: Option<RunFn>,
    pub close: Option<CloseFn>,
    pub release: Option<ReleaseFn>,
}
