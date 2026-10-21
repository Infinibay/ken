//! Versioned bytes and ownership boundary for optional native model modules.

mod registry;
mod request;
mod validation;
mod wire;

pub use registry::{BufferRegistry, HandleRegistry};
pub use request::{
    TransformerArchitecture, TransformerBatch, TransformerDevice, TransformerDeviceRequest,
    TransformerDtype, TransformerOpenRequest, TransformerOutput, TransformerPooling,
    TransformerPrepared, TransformerRunRequest, TransformerRunResult, TransformerWeightLayout,
};
pub use validation::{api_table, checked_bytes, checked_json, guarded};
pub use wire::{CloseFn, GetApiV1, KenBuffer, KenBytes, KenModelApiV1, OpenFn, ReleaseFn, RunFn};

pub const ABI_VERSION: u32 = 1;
pub const MAX_PAYLOAD: usize = 16 * 1024 * 1024;
pub const MAX_DIAGNOSTIC: usize = 64 * 1024;
pub const BACKEND_TORCH: u32 = 1;
pub const BACKEND_MLX: u32 = 2;

#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("invalid native model API: {0}")]
    Invalid(String),
    #[error("invalid native model payload: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native model operation panicked")]
    Panicked,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;
    use std::mem::size_of;

    unsafe extern "C" fn open(_: KenBytes, _: *mut u64, _: *mut KenBuffer) -> i32 {
        0
    }
    unsafe extern "C" fn run(_: u64, _: KenBytes, _: *mut KenBuffer) -> i32 {
        0
    }
    unsafe extern "C" fn close(_: u64) -> i32 {
        0
    }
    unsafe extern "C" fn release(_: *mut KenBuffer) -> i32 {
        0
    }

    fn table() -> KenModelApiV1 {
        KenModelApiV1 {
            abi_version: ABI_VERSION,
            struct_bytes: size_of::<KenModelApiV1>() as u32,
            backend: BACKEND_TORCH,
            reserved: 0,
            open: Some(open),
            run: Some(run),
            close: Some(close),
            release: Some(release),
        }
    }

    #[test]
    fn versioned_table_rejects_wrong_version_backend_and_missing_function() {
        let mut api = table();
        // SAFETY: each pointer refers to the live, aligned complete local table.
        assert!(unsafe { api_table(&api, BACKEND_TORCH) }.is_ok());
        api.abi_version = 0;
        assert!(unsafe { api_table(&api, BACKEND_TORCH) }.is_err());
        api.abi_version = ABI_VERSION;
        assert!(unsafe { api_table(&api, BACKEND_MLX) }.is_err());
        api.run = None;
        assert!(unsafe { api_table(&api, BACKEND_TORCH) }.is_err());
    }

    #[test]
    fn short_foreign_header_is_rejected_before_reading_function_slots() {
        #[repr(C, align(8))]
        struct Header {
            version: u32,
            bytes: u32,
        }
        let header = Header {
            version: ABI_VERSION,
            bytes: size_of::<Header>() as u32,
        };
        let pointer = (&header as *const Header).cast::<KenModelApiV1>();
        // SAFETY: the header lives for the call. Its size explicitly forbids a
        // complete-table read; no function-slot memory exists behind it.
        assert!(unsafe { api_table(pointer, BACKEND_TORCH) }.is_err());
        assert!(unsafe { api_table(std::ptr::null(), BACKEND_TORCH) }.is_err());
    }

    #[test]
    fn null_and_oversized_spans_are_rejected_before_reading_memory() {
        let empty = KenBytes {
            ptr: std::ptr::null(),
            len: 0,
        };
        // SAFETY: empty/null/oversized spans are permitted rejection inputs;
        // none supplies a readable positive-length span.
        assert_eq!(unsafe { checked_bytes(empty, MAX_PAYLOAD) }.unwrap(), b"");
        let null = KenBytes {
            ptr: std::ptr::null(),
            len: 1,
        };
        assert!(unsafe { checked_bytes(null, MAX_PAYLOAD) }.is_err());
        let oversized = KenBytes {
            ptr: std::ptr::NonNull::dangling().as_ptr(),
            len: MAX_PAYLOAD + 1,
        };
        assert!(unsafe { checked_bytes(oversized, MAX_PAYLOAD) }.is_err());
        assert_eq!(MAX_PAYLOAD, 16 * 1024 * 1024);
        assert_eq!(MAX_DIAGNOSTIC, 64 * 1024);
    }

    #[test]
    fn typed_json_rejects_duplicate_unknown_and_invalid_fields() {
        #[derive(Debug, Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Request {
            abi: u32,
        }
        let payload = br#"{"abi":1}"#;
        // SAFETY: every span borrows a live byte slice through parsing only.
        let parsed: Request =
            unsafe { checked_json(KenBytes::new(payload).unwrap(), MAX_PAYLOAD) }.unwrap();
        assert_eq!(parsed.abi, 1);
        for payload in [
            br#"{"abi":1,"abi":2}"#.as_slice(),
            br#"{"abi":1,"extra":0}"#,
            br#"{"abi":true}"#,
            &[0xff],
            b"{",
        ] {
            assert!(
                unsafe { checked_json::<Request>(KenBytes::new(payload).unwrap(), MAX_PAYLOAD) }
                    .is_err()
            );
        }
    }

    #[test]
    fn guarded_operation_returns_error_instead_of_unwinding() {
        assert_eq!(guarded(|| Ok(42)).unwrap(), 42);
        let result: Result<(), ApiError> = guarded(|| panic!("controlled backend panic"));
        assert!(matches!(result, Err(ApiError::Panicked)));
        let ordinary: Result<(), ApiError> =
            guarded(|| Err(ApiError::Invalid("controlled input".into())));
        assert!(matches!(ordinary, Err(ApiError::Invalid(_))));
    }

    #[test]
    fn batch_requires_rectangular_bounded_right_padded_real_tokens() {
        let valid = TransformerBatch {
            input_ids: vec![vec![1, 2, 0], vec![3, 4, 5]],
            attention_mask: vec![vec![1, 1, 0], vec![1, 1, 1]],
        };
        valid.validate(10, 3, 2).unwrap();
        assert!(valid.validate(10, 2, 2).is_err());
        assert!(valid.validate(10, 3, 1).is_err());
        for bad in [
            TransformerBatch {
                input_ids: vec![],
                attention_mask: vec![],
            },
            TransformerBatch {
                input_ids: vec![vec![]],
                attention_mask: vec![vec![]],
            },
            TransformerBatch {
                input_ids: vec![vec![1, 2]],
                attention_mask: vec![vec![1]],
            },
            TransformerBatch {
                input_ids: vec![vec![-1]],
                attention_mask: vec![vec![1]],
            },
            TransformerBatch {
                input_ids: vec![vec![10]],
                attention_mask: vec![vec![1]],
            },
            TransformerBatch {
                input_ids: vec![vec![1]],
                attention_mask: vec![vec![0]],
            },
            TransformerBatch {
                input_ids: vec![vec![1, 0, 2]],
                attention_mask: vec![vec![1, 0, 1]],
            },
            TransformerBatch {
                input_ids: vec![vec![1]],
                attention_mask: vec![vec![2]],
            },
        ] {
            assert!(bad.validate(10, 3, 2).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn projection_requires_two_distinct_registered_token_ids() {
        TransformerOutput::Sentence.validate(10).unwrap();
        TransformerOutput::MLXLast.validate(10).unwrap();
        TransformerOutput::YesMinusNo {
            true_id: 1,
            false_id: 2,
        }
        .validate(10)
        .unwrap();
        assert!(
            TransformerOutput::YesMinusNo {
                true_id: 2,
                false_id: 2
            }
            .validate(10)
            .is_err()
        );
        assert!(
            TransformerOutput::YesMinusNo {
                true_id: 10,
                false_id: 2
            }
            .validate(10)
            .is_err()
        );
    }

    #[test]
    fn opaque_model_handles_are_not_reused_and_own_values_until_close() {
        use std::sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        };
        struct Owned(Arc<AtomicUsize>);
        impl Drop for Owned {
            fn drop(&mut self) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
        }
        let drops = Arc::new(AtomicUsize::new(0));
        let mut registry = HandleRegistry::default();
        let first = registry.insert(Owned(Arc::clone(&drops))).unwrap();
        assert_ne!(first, 0);
        assert!(registry.get(first).is_ok());
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        drop(registry.remove(first).unwrap());
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert!(registry.get(first).is_err() && registry.remove(first).is_err());
        let second = registry.insert(Owned(Arc::clone(&drops))).unwrap();
        assert_ne!(first, second);
        drop(registry);
        assert_eq!(drops.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn backend_buffers_validate_ownership_and_release_exactly_once() {
        let mut registry = BufferRegistry::default();
        let mut buffer = registry
            .publish(b"real owned bytes".to_vec(), MAX_PAYLOAD)
            .unwrap();
        let mut stale = buffer;
        let mut wrong = buffer;
        wrong.len -= 1;
        assert!(registry.release(&mut wrong).is_err());
        assert_eq!(registry.len(), 1);
        // SAFETY: the owning registry and allocation stay live through the read.
        assert_eq!(
            unsafe {
                checked_bytes(
                    KenBytes {
                        ptr: buffer.ptr,
                        len: buffer.len,
                    },
                    MAX_PAYLOAD,
                )
            }
            .unwrap(),
            b"real owned bytes"
        );
        registry.release(&mut buffer).unwrap();
        assert!(buffer.ptr.is_null() && buffer.len == 0 && buffer.allocation == 0);
        assert!(registry.is_empty());
        assert!(registry.release(&mut stale).is_err());
        assert!(
            registry
                .publish(vec![0; MAX_DIAGNOSTIC + 1], MAX_DIAGNOSTIC)
                .is_err()
        );
        assert!(registry.is_empty());
    }

    #[test]
    fn model_wire_schemas_distinguish_requested_and_actual_state() {
        let input = serde_json::json!({"schema":1,"snapshot":"/owned/model",
            "architecture":"qwen3","weight_files":["model.safetensors"],
            "weight_layout":"unprefixed","dtype":"float16","device":{"kind":"auto"},
            "pooling":"last","normalize_modules":1});
        let request: TransformerOpenRequest = serde_json::from_value(input.clone()).unwrap();
        request.validate_schema().unwrap();
        assert_eq!(request.device, TransformerDeviceRequest::Auto);
        assert_eq!(request.dtype, TransformerDtype::Float16);
        let mut bad = input.clone();
        bad["executed_core_version"] = serde_json::json!("pretended");
        assert!(serde_json::from_value::<TransformerOpenRequest>(bad).is_err());
        let mut bad = request.clone();
        bad.schema = 2;
        assert!(bad.validate_schema().is_err());
        let prepared: TransformerPrepared = serde_json::from_value(serde_json::json!({
            "core_version":"2.9.0","device":{"kind":"cpu"},"dtype":"float32","dimension":1024
        }))
        .unwrap();
        assert_eq!(prepared.device, TransformerDevice::Cpu);
        assert_ne!(prepared.dtype, request.dtype);
    }

    #[test]
    fn open_weights_are_distinct_snapshot_relative_names() {
        let value = serde_json::json!({"schema":1,"snapshot":"/owned/model","architecture":"qwen3",
            "weight_files":["model.safetensors"],"weight_layout":"unprefixed","dtype":"float32",
            "device":{"kind":"cpu"},"pooling":"last","normalize_modules":1});
        let request: TransformerOpenRequest = serde_json::from_value(value).unwrap();
        for names in [
            vec!["../model.safetensors"],
            vec!["/model.safetensors"],
            vec!["nested/../model"],
            vec!["a\\model"],
            vec!["model.safetensors", "model.safetensors"],
        ] {
            let mut bad = request.clone();
            bad.weight_files = names.iter().map(|v| (*v).into()).collect();
            assert!(bad.validate_schema().is_err(), "{names:?}");
        }
    }

    #[test]
    fn native_result_requires_exact_shape_complete_finite_values() {
        let valid = TransformerRunResult {
            rows: 2,
            columns: 2,
            values: vec![1., 2., 3., 4.],
        };
        valid.validate(2, 2).unwrap();
        assert!(valid.validate(1, 2).is_err());
        assert!(valid.validate(2, 3).is_err());
        let mut bad = valid.clone();
        bad.values.pop();
        assert!(bad.validate(2, 2).is_err());
        let mut bad = valid;
        bad.values[0] = f32::NAN;
        assert!(bad.validate(2, 2).is_err());
    }
}

mod qwen3;
pub use qwen3::Qwen3Config;

mod parameter_header;
pub use parameter_header::validate_parameter_header;
