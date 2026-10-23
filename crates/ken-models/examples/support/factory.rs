//! Thin outside-checkout consumer: requested operations in, actual observations out.
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ContextInput, EncoderSpec, LegacyRuntimeIdentity,
    ManagedEncoder, ModelCatalog, ModelError, ModelFactory, NativeOnnxRuntime,
    NativeTransformerRuntime, PreparedModelResources, TransformerDeviceRequest,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    sync::Arc,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    format: String,
    policy: String,
    cache_root: PathBuf,
    private_parent: PathBuf,
    bundled_npz: PathBuf,
    source_overrides: BTreeMap<String, PathBuf>,
    device: TransformerDeviceRequest,
    fastembed_device: String,
    onnx: Option<Onnx>,
    torch: Option<Transformer>,
    mlx: Option<Transformer>,
    selection: Selection,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Onnx {
    registration: Value,
    library: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Transformer {
    registration: Value,
    module: PathBuf,
    core_root: PathBuf,
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Selection {
    Encoder {
        spec: EncoderSpec,
        legacy: LegacyRuntimeIdentity,
    },
    LegacyEncoder {
        name: String,
    },
    Judge {
        spec: EncoderSpec,
        legacy: LegacyRuntimeIdentity,
    },
    Context,
    Reranker,
    Expansion,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    call: Call,
}
#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Call {
    Query {
        text: String,
    },
    Passages {
        texts: Vec<String>,
    },
    Count {
        text: String,
    },
    Dimension,
    ConcurrentQuery {
        text: String,
        workers: usize,
    },
    Score {
        query: String,
        documents: Vec<String>,
        purpose: String,
    },
    Expand {
        text: String,
    },
}
fn invalid(message: &str) -> ModelError {
    ModelError::Registration(message.into())
}

pub(crate) fn parse(bytes: &[u8]) -> Result<Request, Box<dyn std::error::Error>> {
    if bytes.len() > ken_native_model_api::MAX_PAYLOAD {
        return Err("oversized factory request".into());
    }
    let request: Request = serde_json::from_slice(bytes)?;
    let mut ids = BTreeSet::new();
    if request.format != "ken-model-factory-request/1"
        || !matches!(request.policy.as_str(), "public" | "offline")
        || !matches!(
            request.fastembed_device.as_str(),
            "cpu" | "gpu" | "cuda" | "auto"
        )
        || [
            &request.cache_root,
            &request.private_parent,
            &request.bundled_npz,
        ]
        .iter()
        .any(|p| !p.is_absolute())
        || request.source_overrides.values().any(|p| !p.is_absolute())
        || request.cases.is_empty()
        || request.cases.len() > 128
        || request.cases.iter().any(|c| {
            c.id.is_empty()
                || !ids.insert(&c.id)
                || matches!(c.call,Call::ConcurrentQuery{workers,..}if !(1..=8).contains(&workers))
        })
    {
        return Err("explicit bounded factory configuration required".into());
    }
    if request
        .onnx
        .as_ref()
        .is_some_and(|r| !r.library.is_absolute())
        || [&request.torch, &request.mlx]
            .into_iter()
            .flatten()
            .any(|r| !r.module.is_absolute() || !r.core_root.is_absolute())
    {
        return Err("absolute prepared native runtime paths required".into());
    }
    Ok(request)
}
fn transformer(
    declaration: &Option<Transformer>,
) -> Result<Option<NativeTransformerRuntime>, ModelError> {
    declaration
        .as_ref()
        .map(|r| {
            NativeTransformerRuntime::from_json(
                &r.registration.to_string(),
                &r.module,
                &r.core_root,
            )
        })
        .transpose()
}
enum Owner {
    Encoder(Arc<ManagedEncoder>),
    Judge(Arc<ken_models::RelevanceJudge>),
    Context(Arc<ken_models::ContextEncoder>),
    Reranker(Arc<ken_models::OnnxReranker>),
    Expansion(Arc<ken_models::LocalQueryExpansion>),
}
impl Owner {
    fn prepared(&self) -> Result<bool, ModelError> {
        match self {
            Self::Encoder(x) => x.is_prepared(),
            Self::Judge(x) => Ok(x.preparation()?.is_some()),
            Self::Context(x) => x.is_prepared(),
            Self::Reranker(x) => x.is_prepared(),
            Self::Expansion(x) => Ok(x.is_loaded()),
        }
    }
    fn preparation(&self) -> Result<Value, ModelError> {
        Ok(match self {
            Self::Encoder(x) => serde_json::to_value(x.preparation()?)?,
            Self::Judge(x) => serde_json::to_value(x.preparation()?)?,
            Self::Context(x) => json!({"prepared":x.is_prepared()?}),
            Self::Reranker(x) => json!({"prepared":x.is_prepared()?}),
            Self::Expansion(x) => serde_json::to_value(x.runtime_identity()?)?,
        })
    }
    fn call(&self, call: &Call) -> Result<Value, ModelError> {
        match (self, call) {
            (Self::Encoder(x), Call::Query { text }) => {
                Ok(json!({"vectors":[x.embed_query(text)?]}))
            }
            (Self::Encoder(x), Call::Passages { texts }) => Ok(
                json!({"vectors":x.embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?}),
            ),
            (Self::Encoder(x), Call::Count { text }) => Ok(json!({"count":x.token_count(text)?})),
            (Self::Encoder(x), Call::Dimension) => Ok(json!({"dimension":x.dim()?})),
            (Self::Encoder(x), Call::ConcurrentQuery { text, workers }) => {
                let vectors = std::thread::scope(|scope| {
                    let jobs: Vec<_> = (0..*workers)
                        .map(|_| scope.spawn(|| x.embed_query(text)))
                        .collect();
                    jobs.into_iter()
                        .map(|j| {
                            j.join()
                                .map_err(|_| invalid("native query thread panicked"))?
                        })
                        .collect::<Result<Vec<_>, ModelError>>()
                })?;
                Ok(json!({"vectors":vectors}))
            }
            (
                Self::Judge(x),
                Call::Score {
                    query,
                    documents,
                    purpose,
                },
            ) => Ok(
                json!({"scores":x.score(query,&documents.iter().map(String::as_str).collect::<Vec<_>>(),purpose)?}),
            ),
            (Self::Context(x), Call::Query { text }) => Ok(
                json!({"tokens":x.tokenize(text,ContextInput::Query)?,"vectors":[x.embed_query(text)?]}),
            ),
            (Self::Context(x), Call::Passages { texts }) => Ok(
                json!({"vectors":x.embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?}),
            ),
            (
                Self::Reranker(x),
                Call::Score {
                    query, documents, ..
                },
            ) => Ok(serde_json::to_value(x.score(
                query,
                &documents.iter().map(String::as_str).collect::<Vec<_>>(),
            )?)?),
            (Self::Expansion(x), Call::Expand { text }) => {
                Ok(serde_json::to_value(x.expand_detailed(text)?)?)
            }
            _ => Err(invalid("operation is not supported by the selected role")),
        }
    }
}
fn error(error: ModelError) -> Value {
    let kind = match error {
        ModelError::RelevanceEmptyDocuments => "IndexError",
        ModelError::RelevanceBudget | ModelError::RelevanceNonfinite | ModelError::Tokenizer(_) => {
            "ValueError"
        }
        _ => "RuntimeError",
    };
    json!({"kind":kind,"message":error.to_string()})
}
pub(crate) fn run(bytes: &[u8]) -> Result<(), Box<dyn std::error::Error>> {
    let request = parse(bytes)?;
    let mut resources = PreparedModelResources::new(&request.private_parent, &request.bundled_npz)?;
    resources.source_overrides = request.source_overrides;
    resources.transformer_device = request.device;
    resources.fastembed_device =
        ken_models::FastEmbedDeviceRequest::from_inputs(Some(&request.fastembed_device), None);
    resources.onnx = request
        .onnx
        .as_ref()
        .map(|r| NativeOnnxRuntime::from_json(&r.registration.to_string(), &r.library))
        .transpose()?;
    resources.torch = transformer(&request.torch)?;
    resources.mlx = transformer(&request.mlx)?;
    let observed = resources.clone();
    let factory = ModelFactory::new(
        ModelCatalog::built_in()?,
        ArtifactCache::new(&request.cache_root)?,
        resources,
        if request.policy == "offline" {
            AcquisitionPolicy::Offline
        } else {
            AcquisitionPolicy::Public
        },
    );
    let (owner, selection, key) = match request.selection {
        Selection::Encoder { spec, legacy } => {
            let x = factory.encoder(&spec, &legacy)?;
            let selection = json!({"role":"encoder","family":x.family(),"spec":spec,"requested_device":request.device});
            (Owner::Encoder(x), selection, json!(spec.key(&legacy)?))
        }
        Selection::LegacyEncoder { name } => {
            let x = factory.legacy_encoder(&name)?;
            let selection = json!({"role":"encoder","family":x.family(),"name":name,"requested_device":request.fastembed_device});
            (Owner::Encoder(x), selection, Value::Null)
        }
        Selection::Judge { spec, legacy } => {
            let x = factory.judge(&spec, &legacy)?;
            (
                Owner::Judge(x),
                json!({"role":"judge","spec":spec,"requested_device":request.device}),
                json!(spec.key(&legacy)?),
            )
        }
        Selection::Context => (
            Owner::Context(factory.context()?),
            json!({"role":"context"}),
            Value::Null,
        ),
        Selection::Reranker => (
            Owner::Reranker(factory.reranker()?),
            json!({"role":"reranker"}),
            Value::Null,
        ),
        Selection::Expansion => (
            Owner::Expansion(factory.expansion()?),
            json!({"role":"expansion"}),
            Value::Null,
        ),
    };
    let initial = owner.prepared()?;
    let after_empty = if let Owner::Encoder(x) = &owner {
        x.embed_passages(&[])?;
        x.is_prepared()?
    } else {
        initial
    };
    let mut rows = Vec::new();
    for case in request.cases {
        let before = owner.prepared()?;
        let result = owner.call(&case.call);
        let mut row = json!({"id":case.id,"before_prepared":before,"prepared":owner.prepared()?,"preparation":owner.preparation()?});
        match result {
            Ok(result) => row["result"] = result,
            Err(e) => row["error"] = error(e),
        }
        rows.push(row);
    }
    let runtime = json!({"onnx":observed.onnx.as_ref().map(|r|r.loaded_identity()).transpose()?,
        "torch":observed.torch.as_ref().map(|r|r.loaded_identity()).transpose()?,"mlx":observed.mlx.as_ref().map(|r|r.loaded_identity()).transpose()?});
    println!(
        "{}",
        json!({"format":"ken-model-factory-observation/1","policy":request.policy,"selection":selection,"compatible_key":key,
        "initial_prepared":initial,"after_empty_prepared":after_empty,"rows":rows,"runtime":runtime})
    );
    Ok(())
}

pub(crate) fn read(path: &Path) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    use std::io::Read;
    if !path.is_absolute() {
        return Err("absolute factory request required".into());
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    use std::os::unix::fs::OpenOptionsExt;
    options.custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY);
    let file = options.open(path)?;
    let limit = ken_native_model_api::MAX_PAYLOAD;
    if !file.metadata()?.is_file() || file.metadata()?.len() > limit as u64 {
        return Err("bounded regular factory request required".into());
    }
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err("factory request too large".into());
    }
    Ok(bytes)
}
