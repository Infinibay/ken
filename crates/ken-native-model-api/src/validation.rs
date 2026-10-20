//! Validate the byte/table boundary before deserialization or native dispatch.
use crate::{ABI_VERSION, ApiError, KenBytes, KenModelApiV1, MAX_PAYLOAD};
use serde::de::DeserializeOwned;
use std::{
    mem::{align_of, size_of},
    panic::{AssertUnwindSafe, catch_unwind},
};

/// Validate a foreign header before reading the complete API table.
///
/// # Safety
/// A non-null aligned pointer must identify readable live memory containing the
/// two-u32 header. A header claiming the exact current table size must actually
/// provide that complete C-compatible table. Non-null function slots must be
/// valid functions with the declared C ABI. Their library must remain mapped
/// through every subsequent use of the returned table. These requirements are
/// supplied by trusted registered backend code, not established by null checks.
pub unsafe fn api_table(
    pointer: *const KenModelApiV1,
    backend: u32,
) -> Result<KenModelApiV1, ApiError> {
    if pointer.is_null() || !pointer.addr().is_multiple_of(align_of::<KenModelApiV1>()) {
        return Err(ApiError::Invalid("null or unaligned API table".into()));
    }
    #[repr(C)]
    struct Header {
        version: u32,
        bytes: u32,
    }
    // SAFETY: the caller guarantees only this live prefix until its size is checked.
    let header = unsafe { pointer.cast::<Header>().read() };
    if header.version != ABI_VERSION || header.bytes as usize != size_of::<KenModelApiV1>() {
        return Err(ApiError::Invalid(
            "incompatible API version or table size".into(),
        ));
    }
    // SAFETY: a matching size makes the complete-table caller guarantee applicable.
    let table = unsafe { pointer.read() };
    if backend == 0
        || table.backend != backend
        || table.reserved != 0
        || table.open.is_none()
        || table.run.is_none()
        || table.close.is_none()
        || table.release.is_none()
    {
        return Err(ApiError::Invalid(
            "wrong backend or incomplete API table".into(),
        ));
    }
    Ok(table)
}

/// Borrow a bounded span without interpreting its bytes.
///
/// # Safety
/// For a positive length within both bounds and a non-null pointer, the caller
/// must supply immutable readable storage for that full length, live for the
/// chosen return lifetime. Empty/null/oversized spans are accepted as validation
/// inputs and never dereferenced. Arbitrary forged positive in-bound addresses
/// are outside the ABI contract and cannot be authenticated by this function.
pub unsafe fn checked_bytes<'a>(span: KenBytes, limit: usize) -> Result<&'a [u8], ApiError> {
    if span.len > limit.min(MAX_PAYLOAD) {
        return Err(ApiError::Invalid("payload exceeds bound".into()));
    }
    if span.len == 0 {
        return Ok(&[]);
    }
    if span.ptr.is_null() {
        return Err(ApiError::Invalid("null positive-length payload".into()));
    }
    // SAFETY: nonempty bounded storage and its lifetime are caller obligations.
    Ok(unsafe { std::slice::from_raw_parts(span.ptr, span.len) })
}

/// Deserialize an owned request; schema structs must deny unknown fields.
///
/// # Safety
/// The nonempty in-bound storage requirements of [`checked_bytes`] apply for
/// this call only. The returned deserialized value cannot borrow that storage.
pub unsafe fn checked_json<T: DeserializeOwned>(
    span: KenBytes,
    limit: usize,
) -> Result<T, ApiError> {
    // SAFETY: this function requires the same input storage contract.
    let bytes = unsafe { checked_bytes(span, limit) }?;
    Ok(serde_json::from_slice(bytes)?)
}

/// Contain Rust unwinding before an exported C ABI function returns. Backend
/// callers still own cleanup of their registry entries and temporary buffers.
pub fn guarded<T>(operation: impl FnOnce() -> Result<T, ApiError>) -> Result<T, ApiError> {
    catch_unwind(AssertUnwindSafe(operation)).map_err(|_| ApiError::Panicked)?
}
