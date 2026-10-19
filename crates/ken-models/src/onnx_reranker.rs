//! Lazy serialized CPU scoring over an already selected pool of at most ten.
use crate::{
    ModelError, NativeOnnxRuntime, PairTokens, PreparedReranker, RerankerModel,
    reranker_tokens::PairedTokenizer,
};
use ort::{session::Session, value::Tensor};
use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    sync::{Arc, Mutex, MutexGuard},
    time::Instant,
};

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct RerankOptions {
    pub batch_size: usize,
    #[serde(rename = "intra_op_threads")]
    pub intra_threads: usize,
    pub max_tokens: usize,
}
impl Default for RerankOptions {
    fn default() -> Self {
        Self {
            batch_size: 1,
            intra_threads: 4,
            max_tokens: 1024,
        }
    }
}
impl RerankOptions {
    pub fn new(
        batch_size: usize,
        intra_threads: usize,
        max_tokens: usize,
    ) -> Result<Self, ModelError> {
        let options = Self {
            batch_size,
            intra_threads,
            max_tokens,
        };
        options.validate()?;
        Ok(options)
    }
    fn validate(&self) -> Result<(), ModelError> {
        if self.batch_size == 0 {
            return Err(invalid("positive integer batch size required"));
        }
        if self.intra_threads == 0 || self.intra_threads > i32::MAX as usize {
            return Err(invalid(
                "positive representable integer CPU thread budget required",
            ));
        }
        if self.max_tokens == 0 {
            return Err(invalid("positive integer token budget required"));
        }
        Ok(())
    }
}

#[derive(Debug, Default, Serialize)]
pub struct RerankDetails {
    pub token_ms: f64,
    pub inference_ms: f64,
    pub truncated_documents: usize,
    pub pair_tokens: Vec<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pad_id: Option<u32>,
}
#[derive(Debug, Default, Serialize)]
pub struct ScoredPool {
    pub scores: Vec<f32>,
    pub details: RerankDetails,
}

struct LoadedReranker {
    // Own authenticated graph and tokenizer bytes for the whole session lifetime.
    _prepared: Arc<PreparedReranker>,
    tokenizer: PairedTokenizer,
    session: Session,
    output: String,
}

pub struct OnnxReranker {
    model: RerankerModel,
    prepared: Option<Arc<PreparedReranker>>,
    source: Option<PathBuf>,
    cache: PathBuf,
    runtime: NativeOnnxRuntime,
    options: RerankOptions,
    loaded: Mutex<Option<LoadedReranker>>,
}
fn invalid(error: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(error.to_string())
}

impl OnnxReranker {
    pub fn new(
        model: RerankerModel,
        prepared: Option<Arc<PreparedReranker>>,
        source: Option<PathBuf>,
        cache: PathBuf,
        runtime: NativeOnnxRuntime,
        options: RerankOptions,
    ) -> Result<Self, ModelError> {
        options.validate()?;
        if prepared
            .as_ref()
            .is_some_and(|prepared| !model.accredits(prepared))
        {
            return Err(ModelError::Registration(
                "prepared graph does not accredit reranker model artifacts".into(),
            ));
        }
        Ok(Self {
            model,
            prepared,
            source,
            cache,
            runtime,
            options,
            loaded: Mutex::new(None),
        })
    }

    fn lock(&self) -> Result<MutexGuard<'_, Option<LoadedReranker>>, ModelError> {
        self.loaded
            .lock()
            .map_err(|_| invalid("reranker session lock poisoned"))
    }
    pub fn is_prepared(&self) -> Result<bool, ModelError> {
        Ok(self.lock()?.is_some())
    }

    fn load<'a>(
        &self,
        slot: &'a mut Option<LoadedReranker>,
    ) -> Result<&'a mut LoadedReranker, ModelError> {
        if slot.is_none() {
            let prepared = match &self.prepared {
                Some(prepared) => prepared.clone(),
                None => Arc::new(self.model.prepare(self.source.as_deref(), &self.cache)?),
            };
            let tokenizer = PairedTokenizer::new(&prepared, self.options.max_tokens)?;
            let environment = self.runtime.environment()?;
            let session = Session::builder(&environment)
                .map_err(invalid)?
                .with_intra_threads(self.options.intra_threads)
                .map_err(invalid)?
                .with_inter_threads(1)
                .map_err(invalid)?
                .with_execution_providers([ort::ep::CPU::default()
                    .with_arena_allocator(true)
                    .build()
                    .error_on_failure()])
                .map_err(invalid)?
                .commit_from_memory(prepared.graph()?)
                .map_err(invalid)?;
            let output = session
                .outputs()
                .first()
                .ok_or_else(|| invalid("reranker output missing"))?
                .name()
                .to_owned();
            *slot = Some(LoadedReranker {
                _prepared: prepared,
                tokenizer,
                session,
                output,
            });
        }
        slot.as_mut()
            .ok_or_else(|| invalid("reranker session absent"))
    }
    pub fn prepare(&self) -> Result<(), ModelError> {
        self.load(&mut *self.lock()?)?;
        Ok(())
    }
    pub fn pair_fits(&self, query: &str, text: &str) -> Result<bool, ModelError> {
        self.load(&mut *self.lock()?)?
            .tokenizer
            .pair_fits(query, text)
    }
    pub fn tokenize_pairs(
        &self,
        query: &str,
        texts: &[&str],
    ) -> Result<Vec<PairTokens>, ModelError> {
        self.load(&mut *self.lock()?)?
            .tokenizer
            .encode(query, texts)
    }
    pub fn score(&self, query: &str, texts: &[&str]) -> Result<ScoredPool, ModelError> {
        if texts.len() > 10 {
            return Err(invalid("reranking is limited to the native top10"));
        }
        let mut result = ScoredPool::default();
        if texts.is_empty() {
            return Ok(result);
        }
        let mut slot = self.lock()?;
        let loaded = self.load(&mut slot)?;
        loaded.tokenizer.check_query(query)?;
        for batch in texts.chunks(self.options.batch_size) {
            let before = Instant::now();
            let tokens = loaded.tokenizer.encode(query, batch)?;
            let width = tokens.first().map_or(0, |row| row.ids.len());
            if tokens.len() != batch.len()
                || tokens
                    .iter()
                    .any(|row| row.ids.len() != width || row.attention_mask.len() != width)
            {
                return Err(invalid("inconsistent paired token dimensions"));
            }
            result.details.truncated_documents +=
                tokens.iter().filter(|row| row.overflowing).count();
            result.details.pair_tokens.extend(tokens.iter().map(|row| {
                row.attention_mask
                    .iter()
                    .map(|n| *n as usize)
                    .sum::<usize>()
            }));
            let ids: Vec<_> = tokens
                .iter()
                .flat_map(|row| row.ids.iter().copied())
                .collect();
            let mask: Vec<_> = tokens
                .iter()
                .flat_map(|row| row.attention_mask.iter().copied())
                .collect();
            // Session creation authenticates and initializes the native API before
            // tensor allocation, including the first lazy score in a cold process.
            let ids = Tensor::from_array(([batch.len(), width], ids)).map_err(invalid)?;
            let mask = Tensor::from_array(([batch.len(), width], mask)).map_err(invalid)?;
            result.details.token_ms += before.elapsed().as_secs_f64() * 1000.;
            let before = Instant::now();
            let output = loaded
                .session
                .run(ort::inputs!["input_ids"=>ids,"attention_mask"=>mask])
                .map_err(invalid)?;
            result.details.inference_ms += before.elapsed().as_secs_f64() * 1000.;
            let value = output
                .get(&loaded.output)
                .ok_or_else(|| invalid("reranker output missing"))?;
            let (_, scores) = value.try_extract_tensor::<f32>().map_err(invalid)?;
            if scores.len() != batch.len() || scores.iter().any(|score| !score.is_finite()) {
                return Err(invalid(
                    "reranker must return one finite score per document",
                ));
            }
            result.scores.extend_from_slice(scores);
        }
        result.details.pad_id = Some(loaded.tokenizer.pad_id);
        Ok(result)
    }
}
