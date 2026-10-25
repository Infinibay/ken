//! A real ONNX session owns its verified files and returns only owned vectors.
use crate::{
    FastEmbedDevice, FastEmbedDeviceRequest, FastEmbedModel, FastEmbedNotice, FastEmbedTokens,
    ModelError, NativeOnnxRuntime, RuntimeIdentity, VerifiedModelFiles,
};
use ort::{
    environment::Environment,
    ep::{self, ExecutionProvider},
    session::{Session, builder::GraphOptimizationLevel},
    value::{Tensor, TensorElementType},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

const SESSION_THREADS: [usize; 2] = [0, 0];
const SESSION_OPTIMIZATION: GraphOptimizationLevel = GraphOptimizationLevel::All;
const SESSION_CPU_ARENA: bool = true;

fn invalid(error: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(format!("FastEmbed: {error}"))
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FastEmbedProviderAttempt {
    pub providers: Vec<String>,
    pub error: Option<String>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FastEmbedPreparation {
    pub device: FastEmbedDevice,
    pub configured_providers: Vec<String>,
    pub attempts: Vec<FastEmbedProviderAttempt>,
    pub runtime: Option<RuntimeIdentity>,
    pub model_fingerprint: String,
    pub declared_artifacts_fingerprint: String,
    pub verified_artifacts_fingerprint: Option<String>,
    pub notices: Vec<FastEmbedNotice>,
}
impl FastEmbedPreparation {
    pub(crate) fn unprepared(model: &FastEmbedModel) -> Self {
        Self {
            device: FastEmbedDevice::Unknown,
            configured_providers: Vec::new(),
            attempts: Vec::new(),
            runtime: None,
            model_fingerprint: model.fingerprint(),
            declared_artifacts_fingerprint: model.assets().fingerprint(),
            verified_artifacts_fingerprint: None,
            notices: model.advisories().to_vec(),
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FastEmbedTensorI64 {
    pub shape: Vec<usize>,
    pub values: Vec<i64>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FastEmbedBatchTrace {
    pub inputs: BTreeMap<String, FastEmbedTensorI64>,
    pub output_shape: Vec<usize>,
    pub output_dtype: String,
}
pub struct EmbeddingBatch {
    pub vectors: Vec<Vec<f32>>,
    pub trace: FastEmbedBatchTrace,
}

pub struct EmbeddingSession {
    // Rust drops fields in declaration order: the session is destroyed first.
    session: Session,
    _files: Arc<VerifiedModelFiles>,
    model: FastEmbedModel,
    input_names: Vec<String>,
    output: String,
    report: FastEmbedPreparation,
}

fn construct(
    environment: &Environment,
    path: &std::path::Path,
    providers: &[String],
) -> Result<Session, ModelError> {
    let providers = providers
        .iter()
        .map(|name| match name.as_str() {
            "CUDAExecutionProvider" => Ok(ep::CUDA::default().build().error_on_failure()),
            "ROCMExecutionProvider" => Ok(ep::ROCm::default().build().error_on_failure()),
            "CPUExecutionProvider" => Ok(ep::CPU::default()
                .with_arena_allocator(SESSION_CPU_ARENA)
                .build()
                .error_on_failure()),
            _ => Err(invalid("unsupported execution provider")),
        })
        .collect::<Result<Vec<_>, _>>()?;
    Session::builder(environment)
        .map_err(invalid)?
        .with_optimization_level(SESSION_OPTIMIZATION)
        .map_err(invalid)?
        .with_intra_threads(SESSION_THREADS[0])
        .map_err(invalid)?
        .with_inter_threads(SESSION_THREADS[1])
        .map_err(invalid)?
        .with_execution_providers(providers)
        .map_err(invalid)?
        .commit_from_file(path)
        .map_err(invalid)
}

impl EmbeddingSession {
    pub fn prepare(
        model: &FastEmbedModel,
        files: Arc<VerifiedModelFiles>,
        runtime: NativeOnnxRuntime,
        request: &FastEmbedDeviceRequest,
    ) -> Result<Self, ModelError> {
        let environment = runtime.environment()?;
        let mut available = Vec::new();
        if request.preference() != "cpu" {
            if ep::CUDA::is_available().unwrap_or(false) {
                available.push("CUDAExecutionProvider");
            }
            if ep::ROCm::is_available().unwrap_or(false) {
                available.push("ROCMExecutionProvider");
            }
        }
        Self::prepare_with_plan(
            model,
            files,
            runtime,
            request,
            &environment,
            request.providers_for(&available),
        )
    }
    fn prepare_with_plan(
        model: &FastEmbedModel,
        files: Arc<VerifiedModelFiles>,
        runtime: NativeOnnxRuntime,
        request: &FastEmbedDeviceRequest,
        environment: &Environment,
        mut providers: Vec<String>,
    ) -> Result<Self, ModelError> {
        if files.fingerprint() != model.assets().fingerprint() {
            return Err(invalid("verified files do not accredit model"));
        }
        crate::verify_onnx_dependencies(model.graph(), &files)?;
        let path = files.artifact_path(model.graph())?;
        let mut attempts = Vec::new();
        let gpu = providers.iter().any(|name| name != "CPUExecutionProvider");
        let mut notices = model.advisories().to_vec();
        if gpu && request.invalid_ids() {
            notices.push(FastEmbedNotice {
                kind: "device_ids".into(),
                message: "ignoring invalid KEN_EMBED_DEVICE_ID".into(),
            });
        }
        let first = construct(environment, &path, &providers);
        attempts.push(FastEmbedProviderAttempt {
            providers: providers.clone(),
            error: first.as_ref().err().map(ToString::to_string),
        });
        let session = match first {
            Ok(session) => session,
            Err(error) if gpu => {
                notices.push(FastEmbedNotice {
                    kind: "gpu_fallback".into(),
                    message: format!("GPU embedder init failed ({error}); falling back to CPU"),
                });
                providers = vec!["CPUExecutionProvider".into()];
                let cpu = construct(environment, &path, &providers);
                attempts.push(FastEmbedProviderAttempt {
                    providers: providers.clone(),
                    error: cpu.as_ref().err().map(ToString::to_string),
                });
                cpu?
            }
            Err(error) => return Err(error),
        };
        let mut seen = BTreeSet::new();
        let mut input_names = Vec::new();
        for input in session.inputs() {
            let name = input.name();
            if !seen.insert(name)
                || input.dtype().tensor_type() != Some(TensorElementType::Int64)
                || !matches!(
                    name,
                    "input_ids" | "attention_mask" | "token_type_ids" | "task_id"
                )
                || (name == "task_id" && model.task_id().is_none())
            {
                return Err(invalid("unsupported graph input or I64 input type"));
            }
            input_names.push(name.to_owned());
        }
        if !seen.contains("input_ids") {
            return Err(invalid("graph requires input_ids"));
        }
        let output = session
            .outputs()
            .first()
            .ok_or_else(|| invalid("graph output absent"))?
            .name()
            .to_owned();
        let report = FastEmbedPreparation {
            device: if providers.len() > 1 {
                FastEmbedDevice::Gpu
            } else {
                FastEmbedDevice::Cpu
            },
            configured_providers: providers,
            attempts,
            runtime: runtime.loaded_identity()?,
            verified_artifacts_fingerprint: Some(files.fingerprint().into()),
            notices,
            ..FastEmbedPreparation::unprepared(model)
        };
        Ok(Self {
            session,
            _files: files,
            model: model.clone(),
            input_names,
            output,
            report,
        })
    }
    pub fn preparation(&self) -> &FastEmbedPreparation {
        &self.report
    }
    pub fn thread_policy(&self) -> [usize; 2] {
        SESSION_THREADS
    }
    pub fn cpu_arena(&self) -> bool {
        SESSION_CPU_ARENA
    }
    pub fn optimization(&self) -> &str {
        match SESSION_OPTIMIZATION {
            GraphOptimizationLevel::Disable => "ORT_DISABLE_ALL",
            GraphOptimizationLevel::Level1 => "ORT_ENABLE_BASIC",
            GraphOptimizationLevel::Level2 => "ORT_ENABLE_EXTENDED",
            GraphOptimizationLevel::Level3 => "ORT_ENABLE_LAYOUT",
            GraphOptimizationLevel::All => "ORT_ENABLE_ALL",
            _ => "unrecognized",
        }
    }
    pub fn run(&mut self, tokens: &FastEmbedTokens) -> Result<EmbeddingBatch, ModelError> {
        let [rows, width] = tokens.shape;
        let count = rows
            .checked_mul(width)
            .ok_or_else(|| invalid("token dimensions overflow"))?;
        if rows == 0
            || width == 0
            || tokens.ids.len() != count
            || tokens.attention_mask.len() != count
            || tokens.ids.iter().any(|id| *id < 0)
            || tokens
                .attention_mask
                .iter()
                .any(|mask| !matches!(mask, 0 | 1))
        {
            return Err(invalid("invalid I64 token batch"));
        }
        let mut inputs = BTreeMap::new();
        for name in &self.input_names {
            let (shape, values) = match name.as_str() {
                "input_ids" => (tokens.shape.to_vec(), tokens.ids.clone()),
                "attention_mask" => (tokens.shape.to_vec(), tokens.attention_mask.clone()),
                "token_type_ids" => (tokens.shape.to_vec(), vec![0; count]),
                "task_id" => (
                    vec![],
                    vec![
                        self.model
                            .task_id()
                            .ok_or_else(|| invalid("task ID absent"))?,
                    ],
                ),
                _ => return Err(invalid("unsupported input")),
            };
            inputs.insert(name.clone(), FastEmbedTensorI64 { shape, values });
        }
        let feeds = inputs
            .iter()
            .map(|(name, tensor)| {
                Tensor::from_array((tensor.shape.clone(), tensor.values.clone()))
                    .map(|value| (name.as_str(), value))
                    .map_err(invalid)
            })
            .collect::<Result<Vec<_>, _>>()?;
        let outputs = self.session.run(feeds).map_err(invalid)?;
        let output = outputs
            .get(&self.output)
            .ok_or_else(|| invalid("missing first output"))?;
        let (shape, values) = output.try_extract_tensor::<f32>().map_err(invalid)?;
        let shape = shape
            .iter()
            .map(|size| usize::try_from(*size).map_err(invalid))
            .collect::<Result<Vec<_>, _>>()?;
        let vectors = self.model.pool(values, &shape, tokens)?;
        Ok(EmbeddingBatch {
            vectors,
            trace: FastEmbedBatchTrace {
                inputs,
                output_shape: shape,
                output_dtype: "float32".into(),
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::{fs, path::PathBuf};
    fn fixture(graph: &str) -> (tempfile::TempDir, FastEmbedModel, Arc<VerifiedModelFiles>) {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("1111111111111111111111111111111111111111");
        let private = temp.path().join("private");
        fs::create_dir(&source).unwrap();
        fs::create_dir(&private).unwrap();
        let graph = fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("tests/fixtures/fastembed")
                .join(format!("{graph}.onnx")),
        )
        .unwrap();
        let mut artifacts = serde_json::Map::new();
        for (name, bytes) in [
            ("model.onnx", graph.as_slice()),
            ("config.json", b"{}".as_slice()),
            ("tokenizer.json", b"{}"),
            ("tokenizer_config.json", b"{}"),
            ("special_tokens_map.json", b"{}"),
        ] {
            fs::write(source.join(name), bytes).unwrap();
            artifacts.insert(
                name.into(),
                json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))}),
            );
        }
        let model=FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/fallback","assets":{"model_id":"test/fallback","revision":"1111111111111111111111111111111111111111","artifacts":artifacts},"graph":"model.onnx","dimension":2,"pooling":"raw","task_id":null,"advisories":[]}).to_string()).unwrap();
        let files = Arc::new(
            model
                .assets()
                .verify_files(&crate::ModelFileSource::new(&source, &private).unwrap())
                .unwrap(),
        );
        (temp, model, files)
    }
    fn runtime() -> NativeOnnxRuntime {
        NativeOnnxRuntime::from_json(
            include_str!("../resources/onnx-runtime-libraries.json"),
            &PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").expect("prepare KEN_ORT_LIBRARY")),
        )
        .unwrap()
    }
    #[test]
    fn actual_gpu_registration_failure_rebuilds_cpu_and_cpu_failures_propagate() {
        let request = FastEmbedDeviceRequest::from_inputs(Some("gpu"), None);
        let runtime = runtime();
        let environment = runtime.environment().unwrap();
        for gpu in ["CUDAExecutionProvider", "ROCMExecutionProvider"] {
            let (_temp, model, files) = fixture("clip");
            // Force only this private plan, not availability: registration runs the real
            // C API against the pinned CPU core and must fail before the CPU retry.
            let mut session = EmbeddingSession::prepare_with_plan(
                &model,
                files,
                runtime.clone(),
                &request,
                &environment,
                vec![gpu.into(), "CPUExecutionProvider".into()],
            )
            .unwrap();
            let report = session.preparation();
            assert_eq!(report.device, FastEmbedDevice::Cpu);
            assert_eq!(report.attempts.len(), 2);
            assert!(report.attempts[0].error.is_some());
            assert!(report.attempts[1].error.is_none());
            assert_eq!(
                session
                    .run(&FastEmbedTokens {
                        shape: [1, 2],
                        ids: vec![3, 4],
                        attention_mask: vec![1, 1]
                    })
                    .unwrap()
                    .vectors,
                vec![vec![3., 4.]]
            );
        }
        let (temp, model, files) = fixture("invalid_operator");
        let failure = EmbeddingSession::prepare(
            &model,
            files,
            runtime,
            &FastEmbedDeviceRequest::from_inputs(Some("cpu"), None),
        );
        assert!(failure.is_err());
        assert!(
            failure
                .err()
                .unwrap()
                .to_string()
                .contains("NoSuchKenOperator")
        );
        assert_eq!(
            fs::read_dir(temp.path().join("private")).unwrap().count(),
            0
        );
    }
}
