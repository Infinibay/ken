//! Serialized original relevance policy and resident-weight CPU retry.
use crate::{
    JudgeTokens, ModelError, ModelFileSource, NativeTransformerRuntime, TransformerModel,
    TransformerPreparation, TransformerRole, TransformerSession, TransformerSettings,
};
use ken_native_model_api::{
    TransformerArchitecture, TransformerDevice, TransformerDeviceRequest, TransformerOutput,
};
use std::sync::{Arc, Mutex, MutexGuard};
fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(message.to_string())
}
struct State {
    session: Option<TransformerSession>,
    tokens: Option<JudgeTokens>,
    sequence_length: usize,
}
/// Owns one causal model and its whole-request relevance/retry policy.
pub struct RelevanceJudge {
    model: TransformerModel,
    source: crate::model_sources::TransformerSource,
    runtime: NativeTransformerRuntime,
    settings: TransformerSettings,
    device: TransformerDeviceRequest,
    state: Mutex<State>,
}
impl RelevanceJudge {
    pub fn new(
        model: TransformerModel,
        source: ModelFileSource,
        runtime: NativeTransformerRuntime,
        settings: TransformerSettings,
        device: TransformerDeviceRequest,
    ) -> Result<Self, ModelError> {
        Self::from_source(
            model,
            crate::model_sources::TransformerSource::Borrowed(source),
            runtime,
            settings,
            device,
        )
    }

    fn from_source(
        model: TransformerModel,
        source: crate::model_sources::TransformerSource,
        runtime: NativeTransformerRuntime,
        settings: TransformerSettings,
        device: TransformerDeviceRequest,
    ) -> Result<Self, ModelError> {
        settings.validate()?;
        if model.role() != TransformerRole::Judge
            || model.architecture() != TransformerArchitecture::Qwen3
        {
            return Err(invalid(
                "relevance judge requires a causal Qwen judge registration",
            ));
        }
        let sequence_length = settings.sequence_length.unwrap_or(512);
        Ok(Self {
            model,
            source,
            runtime,
            settings,
            device,
            state: Mutex::new(State {
                session: None,
                tokens: None,
                sequence_length,
            }),
        })
    }
    fn state(&self) -> Result<MutexGuard<'_, State>, ModelError> {
        self.state
            .lock()
            .map_err(|_| invalid("relevance judge state lock poisoned"))
    }

    pub(crate) fn with_source_provider(
        model: TransformerModel,
        provider: Arc<dyn crate::model_sources::SnapshotProvider>,
        private_parent: std::path::PathBuf,
        runtime: NativeTransformerRuntime,
        settings: TransformerSettings,
        device: TransformerDeviceRequest,
    ) -> Result<Self, ModelError> {
        if !private_parent.is_absolute() {
            return Err(crate::profile::invalid(
                "absolute private model parent required",
            ));
        }
        Self::from_source(
            model,
            crate::model_sources::TransformerSource::Deferred {
                provider,
                private_parent,
            },
            runtime,
            settings,
            device,
        )
    }
    fn load(&self, state: &mut State) -> Result<(), ModelError> {
        if state.session.is_some() {
            return Ok(());
        }
        let source = self.source.resolve(self.model.assets())?;
        if state.tokens.is_none() {
            state.tokens = Some(JudgeTokens::load(&self.model, &source)?);
        }
        let files = Arc::new(self.model.assets().verify_files(&source)?);
        let session = TransformerSession::prepare_requested(
            &self.model,
            files,
            self.runtime.clone(),
            self.device,
            self.settings.effective_dtype(),
        )?;
        state.session = Some(session);
        Ok(())
    }
    pub fn preparation(&self) -> Result<Option<TransformerPreparation>, ModelError> {
        Ok(self.state()?.session.as_ref().map(|s| s.trace().clone()))
    }
    /// The original judge exposes a replaceable spec. Updating its input limit
    /// changes call policy without discarding the resident model or retry state.
    pub fn set_sequence_length(&self, length: usize) -> Result<(), ModelError> {
        if length == 0 {
            return Err(invalid("joint sequence length must be positive"));
        }
        self.state()?.sequence_length = length;
        Ok(())
    }
    fn run(
        &self,
        state: &mut State,
        query: &str,
        documents: &[&str],
        purpose: &str,
        run: &mut impl FnMut(
            &mut TransformerSession,
            &ken_native_model_api::TransformerBatch,
            &TransformerOutput,
        ) -> Result<crate::TransformerBatchResult, ModelError>,
    ) -> Result<Vec<f32>, ModelError> {
        let tokens = state
            .tokens
            .as_ref()
            .ok_or_else(|| invalid("joint tokenizer absent"))?;
        let prepared = tokens.prepare(
            query,
            documents,
            purpose,
            state.sequence_length,
            self.settings.batch_size.unwrap_or(16),
        )?;
        let session = state
            .session
            .as_mut()
            .ok_or_else(|| invalid("joint model absent"))?;
        let output = TransformerOutput::YesMinusNo {
            true_id: prepared.projection_ids[0],
            false_id: prepared.projection_ids[1],
        };
        let mut scores = Vec::with_capacity(documents.len());
        for batch in &prepared.batches {
            scores.extend(run(session, batch, &output)?.values);
        }
        if scores.len() != documents.len() {
            return Err(invalid("joint score count differs from document count"));
        }
        if scores.iter().any(|v| !v.is_finite()) {
            return Err(ModelError::RelevanceNonfinite);
        }
        Ok(scores)
    }
    pub fn score(
        &self,
        query: &str,
        documents: &[&str],
        purpose: &str,
    ) -> Result<Vec<f32>, ModelError> {
        let mut state = self.state()?;
        self.load(&mut state)?;
        self.score_using(
            &mut state,
            query,
            documents,
            purpose,
            |session, batch, output| session.run(batch, output),
            |session| session.to_cpu_float32(),
        )
    }
    fn score_using(
        &self,
        state: &mut State,
        query: &str,
        documents: &[&str],
        purpose: &str,
        mut run: impl FnMut(
            &mut TransformerSession,
            &ken_native_model_api::TransformerBatch,
            &TransformerOutput,
        ) -> Result<crate::TransformerBatchResult, ModelError>,
        convert: impl FnOnce(&mut TransformerSession) -> Result<(), ModelError>,
    ) -> Result<Vec<f32>, ModelError> {
        match self.run(state, query, documents, purpose, &mut run) {
            Ok(scores) => Ok(scores),
            Err(error) => {
                let session = state
                    .session
                    .as_mut()
                    .ok_or_else(|| invalid("joint model absent after failure"))?;
                if matches!(error, ModelError::RelevanceEmptyDocuments)
                    || session.trace().device == TransformerDevice::Cpu
                    || session.trace().runtime.backend == "mlx"
                {
                    return Err(error);
                }
                convert(session)?;
                self.run(state, query, documents, purpose, &mut run)
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::RelevanceJudge;
    use crate::TransformerSettings;
    use ken_native_model_api::{TransformerDevice, TransformerDeviceRequest};
    fn fixture(
        weights: Option<&[u8]>,
    ) -> (
        tempfile::TempDir,
        crate::TransformerModel,
        crate::ModelFileSource,
        crate::NativeTransformerRuntime,
    ) {
        use serde_json::{Value, json};
        let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let mut config: Value = serde_json::from_slice(
            &std::fs::read(repo.join("native/ken-torch-backend/tests/fixtures/qwen/config.json"))
                .unwrap(),
        )
        .unwrap();
        config["max_position_embeddings"] = json!(512);
        let mut tokenizer:Value=serde_json::from_slice(&std::fs::read(repo.join("crates/ken-models/tests/fixtures/context/valid/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/tokenizer.json")).unwrap()).unwrap();
        let vocab = tokenizer["model"]["vocab"].as_object_mut().unwrap();
        vocab.remove("find");
        vocab.remove("red");
        vocab.insert("yes".into(), json!(1));
        vocab.insert("no".into(), json!(2));
        crate::transformer_test_support::fixture_with_details(
            &[("config.json", config)],
            weights,
            "judge",
            Some(&tokenizer),
        )
    }
    #[test]
    fn actual_cpu_loads_even_for_empty_then_scores_raw_batches_and_keeps_its_owned_source() {
        let (_temp, model, source, runtime) = fixture(None);
        let snapshot = source.snapshot().to_owned();
        let judge = RelevanceJudge::new(
            model,
            source,
            runtime,
            TransformerSettings {
                sequence_length: Some(128),
                batch_size: Some(1),
                ..Default::default()
            },
            TransformerDeviceRequest::Cpu,
        )
        .unwrap();
        assert!(judge.preparation().unwrap().is_none());
        assert!(judge.score("", &[], "implementation").is_err());
        assert_eq!(
            judge.preparation().unwrap().unwrap().device,
            TransformerDevice::Cpu
        );
        let scores = judge
            .score("query", &["yes", "no", "yes"], "implementation")
            .unwrap();
        assert_eq!(scores.len(), 3);
        assert_eq!(scores[0], scores[2]);
        assert_ne!(scores[0], scores[1]);
        assert!(scores.iter().all(|n| n.is_finite()));
        std::fs::remove_dir_all(snapshot).unwrap();
        assert_eq!(
            scores,
            judge
                .score("query", &["yes", "no", "yes"], "unknown-purpose")
                .unwrap()
        );
        judge.set_sequence_length(1).unwrap();
        assert!(judge.score("query", &[], "implementation").is_err());
        assert_eq!(
            judge.preparation().unwrap().unwrap().device,
            TransformerDevice::Cpu
        );
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn actual_mps_empty_keeps_gpu_but_budget_failure_converts_resident_weights_to_cpu_float32() {
        let (_temp, model, source, runtime) = fixture(None);
        let snapshot = source.snapshot().to_owned();
        let judge = RelevanceJudge::new(
            model,
            source,
            runtime,
            TransformerSettings {
                dtype: Some(ken_native_model_api::TransformerDtype::Float16),
                sequence_length: Some(128),
                ..Default::default()
            },
            TransformerDeviceRequest::Mps,
        )
        .unwrap();
        assert!(matches!(
            judge.score("", &[], "implementation"),
            Err(crate::ModelError::RelevanceEmptyDocuments)
        ));
        let before = judge.preparation().unwrap().unwrap();
        assert_eq!(before.device, TransformerDevice::Mps);
        assert_eq!(
            before.dtype,
            ken_native_model_api::TransformerDtype::Float16
        );
        std::fs::remove_dir_all(snapshot).unwrap();
        judge.set_sequence_length(1).unwrap();
        assert!(matches!(
            judge.score("query", &[], "implementation"),
            Err(crate::ModelError::RelevanceBudget)
        ));
        let after = judge.preparation().unwrap().unwrap();
        assert_eq!(after.device, TransformerDevice::Cpu);
        assert_eq!(after.dtype, ken_native_model_api::TransformerDtype::Float32);
        assert_eq!(after.model_fingerprint, before.model_fingerprint);
        judge.set_sequence_length(128).unwrap();
        assert_eq!(
            judge.score("query", &["yes", "no"], "tests").unwrap().len(),
            2
        );
        assert_eq!(
            judge.preparation().unwrap().unwrap().device,
            TransformerDevice::Cpu
        );
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn actual_mlx_empty_and_budget_errors_keep_the_original_gpu_and_dtype() {
        let (_temp, model, source, _unused) = fixture(None);
        let judge = RelevanceJudge::new(
            model,
            source,
            crate::transformer_test_support::mlx_runtime(),
            TransformerSettings {
                dtype: Some(ken_native_model_api::TransformerDtype::Float16),
                sequence_length: Some(128),
                ..Default::default()
            },
            TransformerDeviceRequest::Mps,
        )
        .unwrap();
        assert!(matches!(
            judge.score("", &[], "implementation"),
            Err(crate::ModelError::RelevanceEmptyDocuments)
        ));
        assert_eq!(
            judge
                .score("query", &["yes", "no"], "implementation")
                .unwrap()
                .len(),
            2
        );
        judge.set_sequence_length(1).unwrap();
        assert!(matches!(
            judge.score("query", &[], "implementation"),
            Err(crate::ModelError::RelevanceBudget)
        ));
        let after = judge.preparation().unwrap().unwrap();
        assert_eq!(after.device, TransformerDevice::Mps);
        assert_eq!(after.dtype, ken_native_model_api::TransformerDtype::Float16);
        assert_eq!(after.runtime.backend, "mlx");
    }
    #[test]
    fn concurrent_first_use_serializes_one_owned_judge() {
        let (_temp, model, source, runtime) = fixture(None);
        let judge = std::sync::Arc::new(
            RelevanceJudge::new(
                model,
                source,
                runtime,
                TransformerSettings {
                    sequence_length: Some(128),
                    ..Default::default()
                },
                TransformerDeviceRequest::Cpu,
            )
            .unwrap(),
        );
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(4));
        let threads: Vec<_> = (0..4)
            .map(|_| {
                let j = judge.clone();
                let b = barrier.clone();
                std::thread::spawn(move || {
                    b.wait();
                    j.score("query", &["yes", "no"], "tests").unwrap()
                })
            })
            .collect();
        let rows: Vec<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
        assert!(rows.iter().all(|r| r == &rows[0]));
    }
    fn interrupted_request(device: TransformerDeviceRequest, mlx: bool) {
        for nonfinite in [false, true] {
            let (_temp, model, source, runtime) = fixture(None);
            #[cfg(target_os = "macos")]
            let runtime = if mlx {
                crate::transformer_test_support::mlx_runtime()
            } else {
                runtime
            };
            #[cfg(not(target_os = "macos"))]
            assert!(!mlx);
            let judge = RelevanceJudge::new(
                model,
                source,
                runtime,
                TransformerSettings {
                    sequence_length: Some(128),
                    batch_size: Some(1),
                    ..Default::default()
                },
                device,
            )
            .unwrap();
            let mut state = judge.state().unwrap();
            judge.load(&mut state).unwrap();
            let mut calls = Vec::new();
            let outcome = judge.score_using(
                &mut state,
                "query",
                &["yes", "no"],
                "tests",
                |session, batch, output| {
                    calls.push(session.trace().device);
                    let mut result = session.run(batch, output)?;
                    if calls.len() == 2 {
                        if nonfinite {
                            result.values[0] = f32::NAN;
                        } else {
                            return Err(super::invalid("interrupted second real native batch"));
                        }
                    }
                    Ok(result)
                },
                |session| {
                    assert!(!mlx && device != TransformerDeviceRequest::Cpu);
                    session.to_cpu_float32()
                },
            );
            if device == TransformerDeviceRequest::Cpu || mlx {
                assert!(outcome.is_err());
                assert_eq!(calls.len(), 2);
            } else {
                assert_eq!(
                    calls,
                    vec![
                        TransformerDevice::Mps,
                        TransformerDevice::Mps,
                        TransformerDevice::Cpu,
                        TransformerDevice::Cpu
                    ]
                );
                assert_eq!(
                    state.session.as_ref().unwrap().trace().device,
                    TransformerDevice::Cpu
                );
                let scores = outcome.unwrap();
                drop(state);
                assert_eq!(
                    scores,
                    judge.score("query", &["yes", "no"], "tests").unwrap()
                );
            }
        }
    }
    #[test]
    fn cpu_late_failure_and_nonfinite_return_no_partial_scores_without_retry() {
        interrupted_request(TransformerDeviceRequest::Cpu, false);
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn mlx_late_failure_and_nonfinite_propagate_without_cpu_conversion() {
        interrupted_request(TransformerDeviceRequest::Mps, true);
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn mps_late_failure_and_nonfinite_convert_once_and_retry_all_batches() {
        interrupted_request(TransformerDeviceRequest::Mps, false);
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn conversion_failure_keeps_gpu_and_cpu_retry_failure_remains_cpu_without_second_retry() {
        let (_temp, model, source, runtime) = fixture(None);
        let judge = RelevanceJudge::new(
            model,
            source,
            runtime,
            TransformerSettings {
                sequence_length: Some(128),
                ..Default::default()
            },
            TransformerDeviceRequest::Mps,
        )
        .unwrap();
        let mut state = judge.state().unwrap();
        judge.load(&mut state).unwrap();
        let error = judge.score_using(
            &mut state,
            "query",
            &["yes"],
            "tests",
            |session, batch, output| {
                session.run(batch, output)?;
                Err(super::invalid("interrupted real GPU result"))
            },
            |_| Err(super::invalid("conversion I/O error")),
        );
        assert!(error.is_err());
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Mps
        );
        let mut calls = Vec::new();
        let result = judge.score_using(
            &mut state,
            "query",
            &["yes"],
            "tests",
            |session, batch, output| {
                calls.push(session.trace().device);
                session.run(batch, output)?;
                Err(super::invalid("interrupted real result"))
            },
            |session| session.to_cpu_float32(),
        );
        assert!(result.is_err());
        assert_eq!(calls, vec![TransformerDevice::Mps, TransformerDevice::Cpu]);
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Cpu
        );
    }
}
