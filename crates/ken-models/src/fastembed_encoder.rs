//! Serialize a complete text request around lazy owned lexical/native resources.
use crate::{
    EmbeddingSession, FastEmbedBatchTrace, FastEmbedDevice, FastEmbedDeviceRequest, FastEmbedInput,
    FastEmbedModel, FastEmbedPreparation, FastEmbedTokenizer, FastEmbedTokens, ModelError,
    ModelFileSource, NativeOnnxRuntime,
};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FastEmbedRun {
    pub vectors: Vec<Vec<f32>>,
    pub batches: Vec<FastEmbedBatchTrace>,
    pub preparation: FastEmbedPreparation,
}
struct Loaded {
    session: EmbeddingSession,
    tokenizer: FastEmbedTokenizer,
}
pub struct FastEmbedEncoder {
    model: FastEmbedModel,
    source: ModelFileSource,
    runtime: NativeOnnxRuntime,
    request: FastEmbedDeviceRequest,
    loaded: Mutex<Option<Loaded>>,
}
impl FastEmbedEncoder {
    pub fn new(
        model: FastEmbedModel,
        source: ModelFileSource,
        runtime: NativeOnnxRuntime,
        request: FastEmbedDeviceRequest,
    ) -> Result<Self, ModelError> {
        Ok(Self {
            model,
            source,
            runtime,
            request,
            loaded: Mutex::new(None),
        })
    }
    fn lock(&self) -> Result<MutexGuard<'_, Option<Loaded>>, ModelError> {
        self.loaded
            .lock()
            .map_err(|_| ModelError::Inference("FastEmbed state lock poisoned".into()))
    }
    fn load<'a>(&self, slot: &'a mut Option<Loaded>) -> Result<&'a mut Loaded, ModelError> {
        if slot.is_none() {
            let files = Arc::new(self.model.assets().verify_files(&self.source)?);
            let tokenizer = self.model.tokenizer_from_files(&files)?;
            let session =
                EmbeddingSession::prepare(&self.model, files, self.runtime.clone(), &self.request)?;
            *slot = Some(Loaded { session, tokenizer });
        }
        slot.as_mut()
            .ok_or_else(|| ModelError::Inference("FastEmbed preparation absent".into()))
    }
    fn report(&self, slot: &Option<Loaded>) -> FastEmbedPreparation {
        slot.as_ref()
            .map(|loaded| loaded.session.preparation().clone())
            .unwrap_or_else(|| FastEmbedPreparation::unprepared(&self.model))
    }
    pub fn prepare(&self) -> Result<(), ModelError> {
        self.load(&mut *self.lock()?)?;
        Ok(())
    }
    pub fn is_prepared(&self) -> Result<bool, ModelError> {
        Ok(self.lock()?.is_some())
    }
    pub fn dim(&self) -> usize {
        self.model.dim()
    }
    pub fn device(&self) -> Result<FastEmbedDevice, ModelError> {
        Ok(self.preparation()?.device)
    }
    pub fn preparation(&self) -> Result<FastEmbedPreparation, ModelError> {
        Ok(self.report(&*self.lock()?))
    }
    pub fn tokenize(
        &self,
        texts: &[&str],
        kind: FastEmbedInput,
    ) -> Result<Vec<FastEmbedTokens>, ModelError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let slot = self.lock()?;
        match slot.as_ref() {
            Some(loaded) => loaded.tokenizer.tokenize(texts, kind),
            None => self.model.tokenizer(&self.source)?.tokenize(texts, kind),
        }
    }
    pub fn embed_details(
        &self,
        texts: &[&str],
        kind: FastEmbedInput,
    ) -> Result<FastEmbedRun, ModelError> {
        let mut slot = self.lock()?;
        if texts.is_empty() {
            return Ok(FastEmbedRun {
                vectors: Vec::new(),
                batches: Vec::new(),
                preparation: self.report(&slot),
            });
        }
        let loaded = self.load(&mut slot)?;
        let mut vectors = Vec::with_capacity(texts.len());
        let mut batches = Vec::new();
        for tokens in loaded.tokenizer.tokenize(texts, kind)? {
            let batch = loaded.session.run(&tokens)?;
            vectors.extend(batch.vectors);
            batches.push(batch.trace);
        }
        Ok(FastEmbedRun {
            vectors,
            batches,
            preparation: loaded.session.preparation().clone(),
        })
    }
    pub fn embed_queries(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        self.embed_details(texts, FastEmbedInput::Query)
            .map(|result| result.vectors)
    }
    pub fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        self.embed_details(texts, FastEmbedInput::Passage)
            .map(|result| result.vectors)
    }
}
