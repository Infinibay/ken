//! Length-preserving, owned-buffer boundary for the registered CT2 CPU module.
use crate::ModelError;
use std::{ffi::c_void, mem, ptr, slice};

pub(crate) fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Runtime(message.to_string())
}
#[repr(C)]
pub(crate) struct Span {
    pub data: *const u8,
    pub len: usize,
}
impl Span {
    pub fn new(bytes: &[u8]) -> Self {
        Self {
            data: bytes.as_ptr(),
            len: bytes.len(),
        }
    }
}
#[repr(C)]
#[derive(Default)]
pub(crate) struct Buffer {
    pub data: *mut u8,
    pub len: usize,
}
#[repr(C)]
pub(crate) struct Policy {
    pub intra_threads: u32,
    pub inter_threads: u32,
    pub beam_size: u32,
    pub max_input_length: u32,
    pub max_decoding_length: u32,
}
pub(crate) const POLICY: Policy = Policy {
    intra_threads: 2,
    inter_threads: 1,
    beam_size: 1,
    max_input_length: 1024,
    max_decoding_length: 256,
};
#[repr(C)]
#[derive(Default)]
pub(crate) struct Info {
    pub major: u32,
    pub minor: u32,
    pub patch: u32,
    pub float_backend: u32,
    pub int8_backend: u32,
}
#[repr(C)]
#[derive(Clone, Copy)]
pub(crate) struct Api {
    pub abi_version: u32,
    pub struct_size: u32,
    pub info: Option<unsafe extern "C" fn(*mut Info, *mut Buffer) -> u32>,
    pub create:
        Option<unsafe extern "C" fn(Span, *const Policy, *mut *mut c_void, *mut Buffer) -> u32>,
    pub translate: Option<
        unsafe extern "C" fn(*mut c_void, *const Span, usize, *mut Buffer, *mut Buffer) -> u32,
    >,
    pub num_replicas: Option<unsafe extern "C" fn(*mut c_void) -> usize>,
    pub destroy: Option<unsafe extern "C" fn(*mut c_void)>,
    pub free_buffer: Option<unsafe extern "C" fn(Buffer)>,
}
pub(crate) type Getter = unsafe extern "C" fn() -> *const Api;

/// The authenticated getter promises a readable, aligned two-u32 prefix.
pub(crate) unsafe fn table(raw: *const Api) -> Result<Api, ModelError> {
    if raw.is_null() || !(raw as usize).is_multiple_of(mem::align_of::<Api>()) {
        return Err(invalid("invalid translation ABI pointer"));
    }
    // Read the prefix before accessing any optional table entries.
    let prefix = unsafe { ptr::read(raw.cast::<[u32; 2]>()) };
    if prefix != [1, mem::size_of::<Api>() as u32] {
        return Err(invalid("unsupported translation ABI version or size"));
    }
    let api = unsafe { ptr::read(raw) };
    if api.info.is_none()
        || api.create.is_none()
        || api.translate.is_none()
        || api.num_replicas.is_none()
        || api.destroy.is_none()
        || api.free_buffer.is_none()
    {
        return Err(invalid("incomplete translation ABI"));
    }
    Ok(api)
}

impl Api {
    /// Copy before releasing through the allocator belonging to this module.
    pub unsafe fn take(&self, buffer: Buffer) -> Result<Vec<u8>, ModelError> {
        let result = if buffer.len > 64 * 1024 * 1024 || (buffer.len != 0 && buffer.data.is_null())
        {
            Err(invalid("invalid translation ABI buffer"))
        } else if buffer.len == 0 {
            Ok(Vec::new())
        } else {
            Ok(unsafe { slice::from_raw_parts(buffer.data, buffer.len) }.to_vec())
        };
        unsafe { self.free_buffer.expect("validated API")(buffer) };
        result
    }
    pub unsafe fn status(&self, status: u32, error: Buffer) -> Result<(), ModelError> {
        let bytes = unsafe { self.take(error)? };
        if status == 0 && bytes.is_empty() {
            Ok(())
        } else {
            Err(invalid(String::from_utf8(bytes).unwrap_or_else(|_| {
                "invalid native translation error".into()
            })))
        }
    }
}

pub(crate) fn hypothesis(bytes: &[u8]) -> Result<Vec<String>, ModelError> {
    fn integer(input: &mut &[u8]) -> Result<usize, ModelError> {
        let prefix = input
            .get(..8)
            .ok_or_else(|| invalid("truncated translation frame"))?;
        let value = u64::from_le_bytes(prefix.try_into().expect("eight bytes"));
        *input = &input[8..];
        usize::try_from(value).map_err(invalid)
    }
    let mut input = bytes;
    let count = integer(&mut input)?;
    if count > input.len() / 8 {
        return Err(invalid("invalid translation token count"));
    }
    let mut tokens = Vec::with_capacity(count);
    for _ in 0..count {
        let len = integer(&mut input)?;
        let token = input
            .get(..len)
            .ok_or_else(|| invalid("truncated translation token"))?;
        tokens.push(std::str::from_utf8(token).map_err(invalid)?.into());
        input = &input[len..];
    }
    if !input.is_empty() {
        return Err(invalid("trailing translation frame bytes"));
    }
    Ok(tokens)
}
