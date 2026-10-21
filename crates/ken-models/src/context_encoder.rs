//! Contextual lexical inputs and one lazy, serialized CPU inference session.
use crate::{ContextModel, ModelError, NativeOnnxRuntime, VerifiedSnapshot};
use ort::{session::Session, value::Tensor};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tokenizers::{Tokenizer, TruncationParams};

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextInput {
    Query,
    Passage,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ContextTokens {
    pub ids: Vec<i64>,
    pub attention_mask: Vec<i64>,
}

pub struct ContextEncoder {
    model: ContextModel,
    runtime: NativeOnnxRuntime,
    data: Mutex<Option<Arc<ContextData>>>,
    source: Option<Arc<dyn crate::model_sources::SnapshotProvider>>,
    session: Mutex<Option<Session>>,
}

struct ContextData {
    snapshot: Arc<VerifiedSnapshot>,
    tokenizer: Tokenizer,
}

fn inference(error: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(error.to_string())
}

impl ContextEncoder {
    pub fn new(
        model: ContextModel,
        snapshot: Arc<VerifiedSnapshot>,
        runtime: NativeOnnxRuntime,
    ) -> Result<Self, ModelError> {
        let data = Self::prepare_data(&model, snapshot)?;
        Ok(Self {
            model,
            runtime,
            data: Mutex::new(Some(Arc::new(data))),
            source: None,
            session: Mutex::new(None),
        })
    }

    pub(crate) fn with_source_provider(
        model: ContextModel,
        source: Arc<dyn crate::model_sources::SnapshotProvider>,
        runtime: NativeOnnxRuntime,
    ) -> Self {
        Self {
            model,
            runtime,
            data: Mutex::new(None),
            source: Some(source),
            session: Mutex::new(None),
        }
    }

    fn prepare_data(
        model: &ContextModel,
        snapshot: Arc<VerifiedSnapshot>,
    ) -> Result<ContextData, ModelError> {
        if !model.assets().accredits(&snapshot) {
            return Err(ModelError::Registration(
                "snapshot does not accredit context model artifacts".into(),
            ));
        }
        let mut tokenizer = Tokenizer::from_bytes(snapshot.artifact("tokenizer.json")?)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        tokenizer.with_padding(None);
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: 512,
                ..Default::default()
            }))
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        Ok(ContextData {
            snapshot,
            tokenizer,
        })
    }

    fn data(&self) -> Result<Arc<ContextData>, ModelError> {
        let mut slot = self
            .data
            .lock()
            .map_err(|_| inference("context data lock poisoned"))?;
        if let Some(data) = slot.as_ref() {
            return Ok(data.clone());
        }
        let source = self
            .source
            .as_ref()
            .ok_or_else(|| inference("context source absent"))?;
        let snapshot = Arc::new(
            self.model
                .assets()
                .verify(&source.snapshot(self.model.assets())?)?,
        );
        let data = Arc::new(Self::prepare_data(&self.model, snapshot)?);
        *slot = Some(data.clone());
        Ok(data)
    }

    pub fn dim(&self) -> usize {
        768
    }

    pub fn is_prepared(&self) -> Result<bool, ModelError> {
        self.session
            .lock()
            .map(|slot| slot.is_some())
            .map_err(|_| inference("context session lock poisoned"))
    }

    fn load_session(&self, slot: &mut Option<Session>) -> Result<(), ModelError> {
        if slot.is_none() {
            let data = self.data()?;
            let environment = self.runtime.environment()?;
            let session = Session::builder(&environment)
                .map_err(inference)?
                .with_intra_threads(2)
                .map_err(inference)?
                .with_inter_threads(1)
                .map_err(inference)?
                .with_execution_providers([ort::ep::CPU::default().build().error_on_failure()])
                .map_err(inference)?
                .commit_from_memory(data.snapshot.artifact("onnx/model.onnx")?)
                .map_err(inference)?;
            *slot = Some(session);
        }
        Ok(())
    }

    pub fn prepare(&self) -> Result<(), ModelError> {
        let mut slot = self
            .session
            .lock()
            .map_err(|_| inference("context session lock poisoned"))?;
        self.load_session(&mut slot)
    }

    pub fn tokenize(&self, text: &str, kind: ContextInput) -> Result<ContextTokens, ModelError> {
        let input = match kind {
            ContextInput::Query => format!("{}{text}", self.model.query_prefix()),
            ContextInput::Passage => text.to_owned(),
        };
        let encoded = self
            .data()?
            .tokenizer
            .encode(input, true)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        Ok(ContextTokens {
            ids: encoded.get_ids().iter().map(|n| i64::from(*n)).collect(),
            attention_mask: encoded
                .get_attention_mask()
                .iter()
                .map(|n| i64::from(*n))
                .collect(),
        })
    }

    fn encode(&self, text: &str, kind: ContextInput) -> Result<Vec<f32>, ModelError> {
        let tokens = self.tokenize(text, kind)?;
        let mut slot = self
            .session
            .lock()
            .map_err(|_| inference("context session lock poisoned"))?;
        // Tensor construction itself calls the native API. Authenticate and
        // initialize it before any tensor, including the first lazy query.
        self.load_session(&mut slot)?;
        let ids = Tensor::from_array(([1, tokens.ids.len()], tokens.ids)).map_err(inference)?;
        let mask = Tensor::from_array(([1, tokens.attention_mask.len()], tokens.attention_mask))
            .map_err(inference)?;
        let session = slot
            .as_mut()
            .ok_or_else(|| inference("context session absent"))?;
        let output = session
            .run(ort::inputs!["input_ids"=>ids,"attention_mask"=>mask])
            .map_err(inference)?;
        let value = output
            .get("sentence_embedding")
            .ok_or_else(|| inference("context sentence_embedding output missing"))?;
        let (shape, values) = value.try_extract_tensor::<f32>().map_err(inference)?;
        if shape.as_ref() != [1_i64, 768] || values.iter().any(|v| !v.is_finite()) {
            return Err(inference(
                "invalid contextual embedding: expected finite F32[1,768]",
            ));
        }
        Ok(values.to_vec())
    }

    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError> {
        self.encode(text, ContextInput::Query)
    }
    pub fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        texts
            .iter()
            .map(|text| self.encode(text, ContextInput::Passage))
            .collect()
    }
}
