//! Own a native model token and release every backend allocation before return.
use crate::{ModelError, transformer_runtime::TransformerModule};
use ken_native_model_api::{KenBuffer, KenBytes, MAX_DIAGNOSTIC, MAX_PAYLOAD, checked_bytes};
use serde::{Serialize, de::DeserializeOwned};
use std::sync::Arc;

fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(message.to_string())
}

/// No pointer to a native model crosses the ABI. Mutable execution serializes
/// a Send backend model; the last model token retains the mapped library.
pub(crate) struct NativeHandle {
    handle: u64,
    owner: Arc<TransformerModule>,
}

impl NativeHandle {
    pub(crate) fn open<T: DeserializeOwned>(
        owner: Arc<TransformerModule>,
        request: &impl Serialize,
    ) -> Result<(Self, T), ModelError> {
        let bytes = serde_json::to_vec(request)?;
        let span = KenBytes::new(&bytes).map_err(invalid)?;
        let mut handle = 0;
        let mut buffer = KenBuffer::EMPTY;
        // SAFETY: validated live API and initialized writable outputs; borrowed
        // request bytes live through this call. The backend contains unwinding.
        let status = unsafe { owner.api.open.unwrap()(span, &mut handle, &mut buffer) };
        let model = Self { handle, owner };
        let prepared = NativeBuffer::new(&model.owner, buffer).decode(status)?;
        if model.handle == 0 {
            return Err(invalid("successful native open returned no model token"));
        }
        Ok((model, prepared))
    }

    pub(crate) fn run<T: DeserializeOwned>(
        &mut self,
        request: &impl Serialize,
    ) -> Result<T, ModelError> {
        let bytes = serde_json::to_vec(request)?;
        let span = KenBytes::new(&bytes).map_err(invalid)?;
        let mut output = KenBuffer::EMPTY;
        // SAFETY: this model owns a live token and its mapped API, and &mut self
        // prevents concurrent calls into the same model. Backend output storage
        // remains immutable/live until its release function is called below.
        let status = unsafe { self.owner.api.run.unwrap()(self.handle, span, &mut output) };
        NativeBuffer::new(&self.owner, output).decode(status)
    }
}

impl Drop for NativeHandle {
    fn drop(&mut self) {
        if self.handle != 0 {
            // SAFETY: the owner is still live; this is the sole model-token owner.
            unsafe { self.owner.api.close.unwrap()(self.handle) };
            self.handle = 0;
        }
    }
}

struct NativeBuffer<'a> {
    owner: &'a TransformerModule,
    buffer: KenBuffer,
    active: bool,
}

impl<'a> NativeBuffer<'a> {
    fn new(owner: &'a TransformerModule, buffer: KenBuffer) -> Self {
        Self {
            owner,
            buffer,
            active: true,
        }
    }

    fn decode<T: DeserializeOwned>(mut self, status: i32) -> Result<T, ModelError> {
        let result = (|| {
            if self.buffer.len > 0 && self.buffer.allocation == 0 {
                return Err(invalid("native output lacks allocation token"));
            }
            // SAFETY: the trusted backend guarantees readable storage for an
            // in-bound non-null output until release. Bounds/null are checked
            // before access; arbitrary forged addresses violate this ABI.
            let bytes = unsafe {
                checked_bytes(
                    KenBytes {
                        ptr: self.buffer.ptr,
                        len: self.buffer.len,
                    },
                    if status == 0 {
                        MAX_PAYLOAD
                    } else {
                        MAX_DIAGNOSTIC
                    },
                )
            }
            .map_err(invalid)?;
            if status != 0 {
                return Err(invalid(format!(
                    "native status {status}: {}",
                    String::from_utf8_lossy(bytes)
                )));
            }
            serde_json::from_slice(bytes).map_err(ModelError::from)
        })();
        self.active = false;
        // SAFETY: release sees its original initialized descriptor, exactly once.
        let released = unsafe { self.owner.api.release.unwrap()(&mut self.buffer) };
        if released != 0 {
            return Err(invalid("native output release failed"));
        }
        result
    }
}

impl Drop for NativeBuffer<'_> {
    fn drop(&mut self) {
        if self.active {
            // SAFETY: this unwind/error guard still borrows the live API owner.
            unsafe { self.owner.api.release.unwrap()(&mut self.buffer) };
        }
    }
}

#[cfg(test)]
mod tests {
    use super::NativeHandle;
    use crate::NativeTransformerRuntime;
    use serde_json::{Value, json};
    use sha2::{Digest, Sha256};
    use std::{path::Path, sync::Arc};

    #[test]
    fn buffers_close_before_model_and_module_and_execution_can_change_thread() {
        let directory = tempfile::tempdir().unwrap();
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let target = root.join(".ken/rust-migration/m2-optional/api-fixture-target");
        assert!(
            std::process::Command::new(env!("CARGO"))
                .args(["build", "--offline", "--manifest-path"])
                .arg(root.join("native/ken-model-test-backend/Cargo.toml"))
                .env("CARGO_TARGET_DIR", &target)
                .status()
                .unwrap()
                .success()
        );
        let source = target.join("debug").join(format!(
            "{}ken_model_test_backend{}",
            std::env::consts::DLL_PREFIX,
            std::env::consts::DLL_SUFFIX
        ));
        let bytes = std::fs::read(&source).unwrap();
        std::fs::write(directory.path().join("core.dat"), b"abc").unwrap();
        let registration = json!({"format":"ken-native-transformer/1","backend":"contract-fixture","runtimes":[{
            "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"1",
            "module":{"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))},
            "libraries":{"core.dat":{"bytes":3,"sha256":format!("{:x}",Sha256::digest(b"abc"))}}
        }]});
        let runtime = NativeTransformerRuntime::from_json(
            &registration.to_string(),
            &source,
            directory.path(),
        )
        .unwrap();
        let owner = runtime.owner().unwrap();
        let weak = Arc::downgrade(&owner);
        let log = directory.path().join("lifecycle.jsonl");
        let (handle, prepared): (NativeHandle, Value) =
            NativeHandle::open(owner, &json!({"factor":2.0,"lifecycle_log":log})).unwrap();
        assert_eq!(prepared["scope"], "contract-fixture");
        drop(runtime);
        assert!(weak.upgrade().is_some());
        let mut handle = std::thread::spawn(move || handle).join().unwrap();
        let value: Value = handle
            .run(&json!({"operation":"scale","values":[2.0,4.0]}))
            .unwrap();
        assert_eq!(value["values"], json!([4.0, 8.0]));
        assert!(
            handle
                .run::<Value>(&json!({"operation":"panic","values":[]}))
                .is_err()
        );
        let value: Value = handle
            .run(&json!({"operation":"scale","values":[3.0]}))
            .unwrap();
        assert_eq!(value["values"], json!([6.0]));
        assert!(
            handle
                .run::<Value>(&json!({"unknown":"malformed"}))
                .is_err()
        );
        let events = std::fs::read_to_string(&log).unwrap();
        assert!(!events.contains("model_closed"));
        assert_eq!(
            events
                .lines()
                .filter(|v| v.contains("buffer_released"))
                .count(),
            5
        );
        drop(handle);
        assert!(
            weak.upgrade().is_none(),
            "last handle must release the mapped module owner"
        );
        let events = std::fs::read_to_string(&log).unwrap();
        assert_eq!(
            events
                .lines()
                .filter(|v| v.contains("model_closed"))
                .count(),
            1
        );
        assert!(events.lines().last().unwrap().contains("model_closed"));
        let runtime = NativeTransformerRuntime::from_json(
            &registration.to_string(),
            &source,
            directory.path(),
        )
        .unwrap();
        let bad_log = directory.path().join("failed-open.jsonl");
        assert!(
            NativeHandle::open::<u64>(
                runtime.owner().unwrap(),
                &json!({"factor":2.0,"lifecycle_log":bad_log})
            )
            .is_err(),
            "an invalid preparation reply must close its partially opened model"
        );
        let events: Vec<Value> = std::fs::read_to_string(bad_log)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(
            events
                .iter()
                .map(|event| event["event"].as_str().unwrap())
                .collect::<Vec<_>>(),
            vec!["model_opened", "buffer_released", "model_closed"]
        );
    }
}
