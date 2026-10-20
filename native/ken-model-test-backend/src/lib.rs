//! Synthetic C ABI contract fixture. This is never a production model backend.
use ken_native_model_api::{
    ABI_VERSION, ApiError, BufferRegistry, HandleRegistry, KenBuffer, KenBytes, KenModelApiV1,
    MAX_DIAGNOSTIC, MAX_PAYLOAD, TransformerDevice, TransformerDtype, TransformerOpenRequest,
    TransformerOutput, TransformerPrepared, TransformerRunRequest, TransformerRunResult,
    checked_json, guarded,
};
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::BTreeMap,
    fs::OpenOptions,
    io::Write,
    path::PathBuf,
    sync::{Mutex, MutexGuard, OnceLock},
};

fn event(path: &PathBuf, name: &str) {
    if let Ok(mut stream) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(
            stream,
            "{}",
            json!({"event":name,"scope":"contract-fixture"})
        );
    }
}

struct Model {
    computation: Computation,
    log: PathBuf,
}

enum Computation {
    Scale(f64),
    Tokens {
        factor: f32,
        dimension: usize,
        vocabulary: u64,
        sequence: usize,
    },
}

impl Drop for Model {
    fn drop(&mut self) {
        event(&self.log, "model_closed");
    }
}

#[derive(Default)]
struct State {
    models: HandleRegistry<Model>,
    buffers: BufferRegistry,
    logs: BTreeMap<u64, PathBuf>,
    last_log: Option<PathBuf>,
}

fn state() -> MutexGuard<'static, State> {
    static STATE: OnceLock<Mutex<State>> = OnceLock::new();
    STATE
        .get_or_init(Mutex::default)
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

impl State {
    fn publish(
        &mut self,
        payload: Vec<u8>,
        limit: usize,
        log: Option<PathBuf>,
    ) -> Result<KenBuffer, ApiError> {
        let buffer = self.buffers.publish(payload, limit)?;
        if let Some(log) = log {
            self.logs.insert(buffer.allocation, log);
        }
        Ok(buffer)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScaleOpen {
    factor: f64,
    lifecycle_log: PathBuf,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Open {
    Scale(ScaleOpen),
    Transformer(TransformerOpenRequest),
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Request {
    Scale(Run),
    Transformer(TransformerRunRequest),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Run {
    operation: Operation,
    values: Vec<f64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Operation {
    Scale,
    Panic,
}

fn diagnostic(error: ApiError) -> KenBuffer {
    let mut message = error.to_string();
    let mut end = message.len().min(MAX_DIAGNOSTIC);
    while !message.is_char_boundary(end) {
        end -= 1;
    }
    message.truncate(end);
    let mut state = state();
    let log = state.last_log.clone();
    state
        .publish(message.into_bytes(), MAX_DIAGNOSTIC, log)
        .unwrap_or_default()
}

/// # Safety
/// Output pointers must identify aligned writable initialized storage; request
/// bytes obey checked_json's live-memory contract. This fixture owns all tokens.
unsafe extern "C" fn open(input: KenBytes, handle: *mut u64, output: *mut KenBuffer) -> i32 {
    if handle.is_null() || output.is_null() {
        return 1;
    }
    // SAFETY: writable output storage is a caller obligation.
    unsafe {
        *handle = 0;
        *output = KenBuffer::EMPTY;
    }
    let result = guarded(|| {
        // SAFETY: the exported entry point requires checked_json's contract.
        let request: Open = unsafe { checked_json(input, MAX_PAYLOAD) }?;
        let (model, descriptor) = match request {
            Open::Scale(request) => {
                if !request.factor.is_finite() || !request.lifecycle_log.is_absolute() {
                    return Err(ApiError::Invalid(
                        "fixture requires finite factor and absolute owned log".into(),
                    ));
                }
                (
                    Model {
                        computation: Computation::Scale(request.factor),
                        log: request.lifecycle_log,
                    },
                    serde_json::to_vec(&json!({"scope":"contract-fixture","dimension":1}))?,
                )
            }
            Open::Transformer(request) => {
                request.validate_schema()?;
                let root = PathBuf::from(&request.snapshot);
                let config: serde_json::Value = serde_json::from_slice(
                    &std::fs::read(root.join("config.json"))
                        .map_err(|e| ApiError::Invalid(e.to_string()))?,
                )?;
                let dimension = config["hidden_size"]
                    .as_u64()
                    .filter(|&v| v > 0 && v <= 16)
                    .ok_or_else(|| ApiError::Invalid("invalid fixture dimension".into()))?
                    as usize;
                let vocabulary = config["vocab_size"]
                    .as_u64()
                    .filter(|&v| v > 0)
                    .ok_or_else(|| ApiError::Invalid("invalid fixture vocabulary".into()))?;
                let sequence = config["max_position_embeddings"]
                    .as_u64()
                    .filter(|&v| v > 0 && v <= 4096)
                    .ok_or_else(|| ApiError::Invalid("invalid fixture sequence".into()))?
                    as usize;
                let log = PathBuf::from(
                    config["contract_fixture_log"]
                        .as_str()
                        .ok_or_else(|| ApiError::Invalid("missing fixture log".into()))?,
                );
                if !log.is_absolute() {
                    return Err(ApiError::Invalid("absolute fixture log required".into()));
                }
                let factor: f32 = std::fs::read_to_string(root.join(&request.weight_files[0]))
                    .map_err(|e| ApiError::Invalid(e.to_string()))?
                    .parse()
                    .map_err(|_| ApiError::Invalid("invalid fixture multiplier".into()))?;
                if !factor.is_finite() {
                    return Err(ApiError::Invalid("nonfinite fixture multiplier".into()));
                }
                // This fixture performs CPU Float32 arithmetic, regardless of
                // requested device/dtype. Host tests must reject mismatches.
                let prepared = TransformerPrepared {
                    core_version: "1".into(),
                    device: TransformerDevice::Cpu,
                    dtype: TransformerDtype::Float32,
                    dimension,
                };
                (
                    Model {
                        computation: Computation::Tokens {
                            factor,
                            dimension,
                            vocabulary,
                            sequence,
                        },
                        log,
                    },
                    serde_json::to_vec(&prepared)?,
                )
            }
        };
        event(&model.log, "model_opened");
        let mut state = state();
        let log = model.log.clone();
        let mut buffer = state.publish(descriptor, MAX_PAYLOAD, Some(log.clone()))?;
        let handle = match state.models.insert(model) {
            Ok(handle) => handle,
            Err(error) => {
                state.logs.remove(&buffer.allocation);
                state.buffers.release(&mut buffer)?;
                return Err(error);
            }
        };
        state.last_log = Some(log);
        Ok((handle, buffer))
    });
    match result {
        Ok((value, buffer)) => {
            unsafe {
                *handle = value;
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
/// Request storage must be live and output must be aligned writable EMPTY data.
unsafe extern "C" fn run(handle: u64, input: KenBytes, output: *mut KenBuffer) -> i32 {
    if output.is_null() {
        return 1;
    }
    unsafe {
        *output = KenBuffer::EMPTY;
    }
    let result = guarded(|| {
        let request: Request = unsafe { checked_json(input, MAX_PAYLOAD) }?;
        let mut state = state();
        let model = state.models.get(handle)?;
        let payload = match (&model.computation, request) {
            (Computation::Scale(factor), Request::Scale(request)) => {
                if matches!(request.operation, Operation::Panic) {
                    panic!("controlled contract-fixture panic");
                }
                let values: Vec<_> = request.values.iter().map(|value| value * factor).collect();
                if values.iter().any(|value| !value.is_finite()) {
                    return Err(ApiError::Invalid("fixture nonfinite result".into()));
                }
                serde_json::to_vec(&json!({"scope":"contract-fixture","values":values}))?
            }
            (
                Computation::Tokens {
                    factor,
                    dimension,
                    vocabulary,
                    sequence,
                },
                Request::Transformer(request),
            ) => {
                request.validate(*vocabulary, *sequence, 64)?;
                if !matches!(request.output, TransformerOutput::Sentence) {
                    return Err(ApiError::Invalid(
                        "fixture only supports synthetic sentence output".into(),
                    ));
                }
                let values = request
                    .batch
                    .input_ids
                    .iter()
                    .zip(&request.batch.attention_mask)
                    .flat_map(|(ids, mask)| {
                        let sum: f32 = ids
                            .iter()
                            .zip(mask)
                            .filter(|(_, m)| **m == 1)
                            .map(|(id, _)| *id as f32)
                            .sum();
                        (0..*dimension).map(move |col| sum * factor + col as f32)
                    })
                    .collect();
                let result = TransformerRunResult {
                    rows: request.batch.input_ids.len(),
                    columns: *dimension,
                    values,
                };
                result.validate(result.rows, *dimension)?;
                serde_json::to_vec(&result)?
            }
            _ => {
                return Err(ApiError::Invalid(
                    "request does not match fixture computation".into(),
                ));
            }
        };
        let log = model.log.clone();
        state.publish(payload, MAX_PAYLOAD, Some(log))
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
/// The owning fixture library must remain mapped. Tokens are checked integers.
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
/// Buffer points to writable initialized descriptor storage. Its data pointer
/// is compared to owned registry storage and never dereferenced by release.
unsafe extern "C" fn release(buffer: *mut KenBuffer) -> i32 {
    if buffer.is_null() {
        return 1;
    }
    match guarded(|| {
        let mut state = state();
        let token = unsafe { (*buffer).allocation };
        unsafe { state.buffers.release(&mut *buffer) }?;
        if let Some(log) = state.logs.remove(&token) {
            event(&log, "buffer_released");
        }
        Ok(())
    }) {
        Ok(()) => 0,
        Err(_) => 1,
    }
}

static API: KenModelApiV1 = KenModelApiV1 {
    abi_version: ABI_VERSION,
    struct_bytes: std::mem::size_of::<KenModelApiV1>() as u32,
    backend: 0xffff_fffe,
    reserved: 0,
    open: Some(open),
    run: Some(run),
    close: Some(close),
    release: Some(release),
};

/// # Safety
/// The returned static table is valid only while this fixture library is mapped.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn ken_model_api_v1() -> *const KenModelApiV1 {
    &API
}
