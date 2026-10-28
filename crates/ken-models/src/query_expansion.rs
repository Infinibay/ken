//! One lazy, authenticated native CPU translator; every call owns its diagnostics.
use crate::{
    ModelError, NativeTranslationRuntime, PreparedTranslation, QueryExpansionPlan,
    TranslationModel, plan_query, translation_model::TRANSLATION_FILES,
};
use ct2rs::{
    ComputeType, Config, Device,
    sys::{TranslationOptions, Translator},
};
use sentencepiece::SentencePieceProcessor;
use serde::Serialize;
use std::sync::Arc;
use std::{fs, path::PathBuf, sync::Mutex};

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct TranslationTokens {
    pub ids: Vec<u32>,
    pub pieces_with_eos: Vec<String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranslationTrace {
    pub prepared: String,
    pub tokens: TranslationTokens,
    pub hypotheses: Vec<Vec<String>>,
    pub decoded: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct ExpandedQuery {
    pub text: String,
    pub trace: Option<TranslationTrace>,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranslationInput {
    pub prepared: String,
    pub tokens: TranslationTokens,
}

#[derive(Debug)]
pub struct ExpansionAttempt {
    pub result: Result<ExpandedQuery, ModelError>,
    pub input: Option<TranslationInput>,
}

#[derive(Clone, Debug, Serialize)]
pub struct TranslationRuntimeIdentity {
    #[serde(skip_serializing_if = "str::is_empty")]
    pub ct2rs_crate: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub native_binding: Option<&'static str>,
    pub ctranslate2_source: &'static str,
    pub sentencepiece_crate: &'static str,
    pub sentencepiece_source: &'static str,
    pub float_backend: &'static str,
    pub int8_backend: &'static str,
    pub configured_device: &'static str,
    pub configured_compute_type: &'static str,
    pub intra_threads: usize,
    pub inter_threads: usize,
    pub observed_replicas: usize,
    pub beam_size: usize,
    pub max_input_length: usize,
    pub max_decoding_length: usize,
}

struct NativeSession {
    // C++ model/workers are destroyed before the retained private data directory.
    translator: SessionTranslator,
    source: SentencePieceProcessor,
    target: SentencePieceProcessor,
    identity: TranslationRuntimeIdentity,
    _materialized: tempfile::TempDir,
}

enum SessionTranslator {
    Static(Translator, TranslationOptions<String, String>),
    Registered(crate::translation_runtime::NativeTranslator),
}
impl SessionTranslator {
    fn replicas(&self) -> Result<usize, ModelError> {
        match self {
            Self::Static(translator, _) => translator
                .num_replicas()
                .map_err(|v| ModelError::Runtime(v.to_string())),
            Self::Registered(translator) => Ok(translator.replicas()),
        }
    }
    fn translate(&self, tokens: &[String]) -> Result<Vec<Vec<String>>, ModelError> {
        match self {
            Self::Registered(translator) => {
                translator.translate(tokens).map_err(|error| match error {
                    ModelError::Runtime(message) => ModelError::Inference(message),
                    other => other,
                })
            }
            Self::Static(translator, options) => {
                let rows = translator
                    .translate_batch(&[tokens.to_vec()], options, None)
                    .map_err(|v| ModelError::Inference(v.to_string()))?;
                if rows.len() != 1 {
                    return Err(ModelError::Inference(
                        "native translator returned an invalid row count".into(),
                    ));
                }
                Ok(rows.into_iter().next().expect("one result").hypotheses)
            }
        }
    }
}

impl NativeSession {
    fn load(
        prepared: PreparedTranslation,
        native: Option<&NativeTranslationRuntime>,
    ) -> Result<Self, ModelError> {
        if native.is_none()
            && !cfg!(all(
                target_arch = "aarch64",
                any(target_os = "macos", target_os = "linux")
            ))
        {
            return Err(ModelError::Runtime(
                "translation profile requires an explicit registered CPU runtime on this platform"
                    .into(),
            ));
        }
        let materialized = tempfile::Builder::new()
            .prefix("ken-native-translation-")
            .tempdir()
            .map_err(|source| ModelError::Io {
                artifact: "private translation directory".into(),
                source,
            })?;
        for name in TRANSLATION_FILES {
            fs::write(materialized.path().join(name), prepared.artifact(name)?).map_err(
                |source| ModelError::Io {
                    artifact: name.into(),
                    source,
                },
            )?;
        }
        let policy = &crate::translation_abi::POLICY;
        let config = Config {
            device: Device::CPU,
            compute_type: ComputeType::INT8,
            num_threads_per_replica: policy.intra_threads as usize,
            device_indices: vec![0],
            ..Default::default()
        };
        let options = TranslationOptions {
            beam_size: policy.beam_size as usize,
            max_input_length: policy.max_input_length as usize,
            max_decoding_length: policy.max_decoding_length as usize,
            ..Default::default()
        };
        let translator = if let Some(native) = native {
            SessionTranslator::Registered(native.session(materialized.path())?)
        } else {
            SessionTranslator::Static(
                Translator::new(materialized.path(), &config)
                    .map_err(|error| ModelError::Runtime(error.to_string()))?,
                options,
            )
        };
        let source =
            SentencePieceProcessor::from_serialized_proto(prepared.artifact("source.spm")?)
                .map_err(|error| ModelError::Tokenizer(error.to_string()))?;
        let target =
            SentencePieceProcessor::from_serialized_proto(prepared.artifact("target.spm")?)
                .map_err(|error| ModelError::Tokenizer(error.to_string()))?;
        let replicas = translator.replicas()?;
        if replicas != 1 {
            return Err(ModelError::Runtime(
                "translation requires one native replica".into(),
            ));
        }
        let (float_backend, int8_backend) = match &translator {
            SessionTranslator::Registered(value) => value.backends()?,
            SessionTranslator::Static(..) => (
                if cfg!(target_os = "macos") {
                    "Accelerate"
                } else {
                    "OpenBLAS0.3.26"
                },
                "Ruy",
            ),
        };
        let identity = TranslationRuntimeIdentity {
            ct2rs_crate: if native.is_some() { "" } else { "0.10.1" },
            native_binding: native.map(|_| "ken-translation/1"),
            ctranslate2_source: "4.8.2",
            sentencepiece_crate: "0.13.2",
            sentencepiece_source: "0.2.1",
            float_backend,
            int8_backend,
            configured_device: match config.device {
                Device::CPU => "cpu",
                _ => "unsupported",
            },
            configured_compute_type: match config.compute_type {
                ComputeType::INT8 => "int8",
                _ => "unsupported",
            },
            intra_threads: config.num_threads_per_replica,
            inter_threads: config.device_indices.len(),
            observed_replicas: replicas,
            beam_size: policy.beam_size as usize,
            max_input_length: policy.max_input_length as usize,
            max_decoding_length: policy.max_decoding_length as usize,
        };
        Ok(Self {
            translator,
            source,
            target,
            identity,
            _materialized: materialized,
        })
    }

    fn tokenize(&self, prepared: &str) -> Result<TranslationTokens, ModelError> {
        let pieces = self
            .source
            .encode(prepared)
            .map_err(|error| ModelError::Tokenizer(error.to_string()))?;
        let ids = pieces.iter().map(|piece| piece.id).collect();
        let mut pieces_with_eos: Vec<_> = pieces.into_iter().map(|piece| piece.piece).collect();
        pieces_with_eos.push("</s>".into());
        Ok(TranslationTokens {
            ids,
            pieces_with_eos,
        })
    }

    fn translate(
        &self,
        prepared: &str,
        input: &mut Option<TranslationInput>,
    ) -> Result<TranslationTrace, ModelError> {
        let tokens = self.tokenize(prepared)?;
        *input = Some(TranslationInput {
            prepared: prepared.into(),
            tokens: tokens.clone(),
        });
        let hypotheses = self.translator.translate(&tokens.pieces_with_eos)?;
        if hypotheses.len() != 1 {
            return Err(ModelError::Inference(
                "native translator returned an invalid hypothesis count".into(),
            ));
        }
        let decoded = self
            .target
            .decode_pieces(&hypotheses[0])
            .map_err(|error| ModelError::Tokenizer(error.to_string()))?;
        Ok(TranslationTrace {
            prepared: prepared.into(),
            tokens,
            hypotheses,
            decoded,
        })
    }
}

pub struct LocalQueryExpansion {
    model: TranslationModel,
    source: crate::model_sources::PreparationSource,
    cache: PathBuf,
    runtime: Mutex<Option<NativeSession>>,
    native: Option<NativeTranslationRuntime>,
}

impl LocalQueryExpansion {
    pub fn new(
        model: TranslationModel,
        source: Option<PathBuf>,
        cache: PathBuf,
    ) -> Result<Self, ModelError> {
        let absolute = |path: PathBuf| {
            std::path::absolute(&path).map_err(|source| ModelError::Io {
                artifact: path.display().to_string(),
                source,
            })
        };
        Ok(Self {
            model,
            source: crate::model_sources::PreparationSource::Borrowed(
                source.map(absolute).transpose()?,
            ),
            cache: absolute(cache)?,
            runtime: Mutex::new(None),
            native: None,
        })
    }

    pub fn with_native_runtime(mut self, runtime: NativeTranslationRuntime) -> Self {
        self.runtime = Mutex::new(None);
        self.native = Some(runtime);
        self
    }

    pub(crate) fn with_source_provider(
        model: TranslationModel,
        source: Arc<dyn crate::model_sources::SnapshotProvider>,
        cache: PathBuf,
    ) -> Result<Self, ModelError> {
        let mut owner = Self::new(model, None, cache)?;
        owner.source = crate::model_sources::PreparationSource::Deferred(source);
        Ok(owner)
    }

    fn with_runtime<T>(
        &self,
        action: impl FnOnce(&NativeSession) -> Result<T, ModelError>,
    ) -> Result<T, ModelError> {
        let mut guard = self
            .runtime
            .lock()
            .map_err(|_| ModelError::Runtime("translation runtime mutex poisoned".into()))?;
        if guard.is_none() {
            let source = self
                .source
                .for_preparation(self.model.source_assets(), &self.cache)?;
            let prepared = self.model.prepare(source.as_deref(), &self.cache)?;
            *guard = Some(NativeSession::load(prepared, self.native.as_ref())?);
        }
        action(
            guard
                .as_ref()
                .expect("runtime initialized while holding its lock"),
        )
    }

    pub fn expand(&self, query: &str) -> Result<String, ModelError> {
        Ok(self.expand_detailed(query)?.text)
    }

    pub fn expand_detailed(&self, query: &str) -> Result<ExpandedQuery, ModelError> {
        self.expand_attempt(query).result
    }

    pub fn expand_attempt(&self, query: &str) -> ExpansionAttempt {
        let mut input = None;
        let result = (|| match plan_query(query)? {
            QueryExpansionPlan::Passthrough(text) => Ok(ExpandedQuery { text, trace: None }),
            QueryExpansionPlan::Translate(query) => self.with_runtime(|runtime| {
                let trace = runtime.translate(query.text(), &mut input)?;
                let text = query.restore(&trace.decoded)?;
                Ok(ExpandedQuery {
                    text,
                    trace: Some(trace),
                })
            }),
        })();
        ExpansionAttempt { result, input }
    }

    pub fn tokenize_prepared(&self, prepared: &str) -> Result<TranslationTokens, ModelError> {
        self.with_runtime(|runtime| runtime.tokenize(prepared))
    }
    pub fn load(&self) -> Result<(), ModelError> {
        self.with_runtime(|_| Ok(()))
    }
    pub fn is_loaded(&self) -> bool {
        self.runtime
            .lock()
            .map(|guard| guard.is_some())
            .unwrap_or(false)
    }
    pub fn runtime_identity(&self) -> Result<Option<TranslationRuntimeIdentity>, ModelError> {
        let guard = self
            .runtime
            .lock()
            .map_err(|_| ModelError::Runtime("translation runtime mutex poisoned".into()))?;
        Ok(guard.as_ref().map(|runtime| runtime.identity.clone()))
    }
}

#[cfg(test)]
#[path = "../tests/support/translation_oracle.rs"]
pub(crate) mod oracle;

#[cfg(test)]
mod tests {
    use crate::{ModelError, TranslationModel};
    use std::path::PathBuf;

    #[test]
    fn actual_native_core_matches_all_pre_product_original_raw_histories() {
        let original = super::oracle::raw_histories(std::env::consts::OS, std::env::consts::ARCH);
        let source = PathBuf::from(
            std::env::var_os("KEN_TRANSLATION_SOURCE")
                .expect("prepare KEN_TRANSLATION_SOURCE for actual native CT2 core parity"),
        );
        let model = TranslationModel::from_json(include_str!(
            "../../../src/ken/embedder/data/es-en-ct2-int8.json"
        ))
        .unwrap();
        let root = tempfile::tempdir().unwrap();
        let prepared = model
            .prepare(
                Some(&source),
                &root.path().join("c96e2c5399ebfae4fc43d9669556b9afa74bb69d"),
            )
            .unwrap();
        let native = super::oracle::native_declaration().map(|(registration, module, core)| {
            crate::NativeTranslationRuntime::from_json(&registration, &module, &core).unwrap()
        });
        let session = super::NativeSession::load(prepared, native.as_ref()).unwrap();
        assert_eq!(session.identity.observed_replicas, 1);
        for row in original {
            let query = row["input"].as_str().unwrap();
            let tokens = session.tokenize(query).unwrap();
            assert_eq!(serde_json::to_value(tokens.ids).unwrap(), row["source_ids"]);
            assert_eq!(
                serde_json::to_value(tokens.pieces_with_eos).unwrap(),
                row["source_pieces_with_eos"]
            );
            match session.translate(query, &mut None) {
                Ok(trace) => {
                    assert!(row.get("error").is_none());
                    assert_eq!(
                        serde_json::to_value(trace.hypotheses).unwrap(),
                        row["hypotheses"]
                    );
                    assert_eq!(trace.decoded, row["decoded"].as_str().unwrap());
                }
                Err(ModelError::Inference(error)) => {
                    assert_eq!(error, row["error"].as_str().unwrap())
                }
                Err(error) => panic!("unexpected native core failure: {error}"),
            }
        }
    }
}
