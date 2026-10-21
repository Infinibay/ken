//! Exception-contained bounded JSON ABI; integer registries own every allocation.
use crate::model::Model;
use ken_native_model_api::{
    ABI_VERSION, ApiError, BACKEND_MLX, BufferRegistry, HandleRegistry, KenBuffer, KenBytes,
    KenModelApiV1, MAX_DIAGNOSTIC, MAX_PAYLOAD, TransformerOpenRequest, TransformerRunRequest,
    checked_json, guarded,
};
use std::sync::{Mutex, MutexGuard, OnceLock};

#[derive(Default)]
struct State {
    models: HandleRegistry<Model>,
    buffers: BufferRegistry,
}
fn state() -> MutexGuard<'static, State> {
    static STATE: OnceLock<Mutex<State>> = OnceLock::new();
    STATE
        .get_or_init(Mutex::default)
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn diagnostic(error: ApiError) -> KenBuffer {
    let mut text = error.to_string();
    let mut end = text.len().min(MAX_DIAGNOSTIC);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    text.truncate(end);
    state()
        .buffers
        .publish(text.into_bytes(), MAX_DIAGNOSTIC)
        .unwrap_or_default()
}

/// # Safety
/// Request bytes and initialized aligned writable outputs obey the shared ABI.
unsafe extern "C" fn open(input: KenBytes, handle: *mut u64, output: *mut KenBuffer) -> i32 {
    if handle.is_null()
        || output.is_null()
        || !handle.addr().is_multiple_of(std::mem::align_of::<u64>())
        || !output
            .addr()
            .is_multiple_of(std::mem::align_of::<KenBuffer>())
    {
        return 1;
    }
    unsafe {
        *handle = 0;
        *output = KenBuffer::EMPTY;
    }
    let result = guarded(|| {
        let request: TransformerOpenRequest = unsafe { checked_json(input, MAX_PAYLOAD) }?;
        let (model, prepared) =
            Model::prepare(request).map_err(|e| ApiError::Invalid(e.to_string()))?;
        let payload = serde_json::to_vec(&prepared)?;
        let mut state = state();
        let mut buffer = state.buffers.publish(payload, MAX_PAYLOAD)?;
        let handle = match state.models.insert(model) {
            Ok(handle) => handle,
            Err(error) => {
                state.buffers.release(&mut buffer)?;
                return Err(error);
            }
        };
        Ok((handle, buffer))
    });
    match result {
        Ok((token, buffer)) => {
            unsafe {
                *handle = token;
                *output = buffer;
            }
            0
        }
        Err(error) => {
            unsafe {
                *output = diagnostic(error);
            }
            1
        }
    }
}

/// # Safety
/// Input storage remains live; output is initialized aligned writable EMPTY data.
unsafe extern "C" fn run(handle: u64, input: KenBytes, output: *mut KenBuffer) -> i32 {
    if output.is_null()
        || !output
            .addr()
            .is_multiple_of(std::mem::align_of::<KenBuffer>())
    {
        return 1;
    }
    unsafe {
        *output = KenBuffer::EMPTY;
    }
    let result = guarded(|| {
        let request: TransformerRunRequest = unsafe { checked_json(input, MAX_PAYLOAD) }?;
        let mut state = state();
        let result = state
            .models
            .get(handle)?
            .run(request)
            .map_err(|e| ApiError::Invalid(e.to_string()))?;
        state
            .buffers
            .publish(serde_json::to_vec(&result)?, MAX_PAYLOAD)
    });
    match result {
        Ok(buffer) => {
            unsafe {
                *output = buffer;
            }
            0
        }
        Err(error) => {
            unsafe {
                *output = diagnostic(error);
            }
            1
        }
    }
}

/// # Safety
/// The owning module stays mapped throughout the call. Handles are registry tokens.
unsafe extern "C" fn close(handle: u64) -> i32 {
    match guarded(|| {
        drop(state().models.remove(handle)?);
        Ok(())
    }) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

/// # Safety
/// Buffer is initialized aligned writable descriptor data, never an object pointer.
unsafe extern "C" fn release(buffer: *mut KenBuffer) -> i32 {
    if buffer.is_null()
        || !buffer
            .addr()
            .is_multiple_of(std::mem::align_of::<KenBuffer>())
    {
        return 1;
    }
    match guarded(|| unsafe { state().buffers.release(&mut *buffer) }) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

static API: KenModelApiV1 = KenModelApiV1 {
    abi_version: ABI_VERSION,
    struct_bytes: std::mem::size_of::<KenModelApiV1>() as u32,
    backend: BACKEND_MLX,
    reserved: 0,
    open: Some(open),
    run: Some(run),
    close: Some(close),
    release: Some(release),
};

#[unsafe(no_mangle)]
pub extern "C" fn ken_model_api_v1() -> *const KenModelApiV1 {
    &API
}
