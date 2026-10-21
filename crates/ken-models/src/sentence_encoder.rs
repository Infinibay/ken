//! Lazy Sentence Transformers state and whole-request inference.
use crate::{
    ModelError, ModelFileSource, NativeTransformerRuntime, TransformerModel, TransformerRole,
    TransformerSession, TransformerSettings, TransformerTokens, TransformerTrace,
    VerifiedModelFiles,
};
use ken_native_model_api::{TransformerDevice, TransformerDeviceRequest, TransformerOutput};
use std::sync::{Arc, Mutex, MutexGuard};

pub type TransformerPreparation = TransformerTrace;

/// Serializes a whole request and publishes only fully prepared native sessions.
pub struct SentenceEncoder {
    model: TransformerModel,
    source: ModelFileSource,
    runtime: NativeTransformerRuntime,
    settings: TransformerSettings,
    device_request: TransformerDeviceRequest,
    state: Mutex<EncoderState>,
}
#[derive(Default)]
struct EncoderState {
    tokens: Option<TransformerTokens>,
    files: Option<Arc<VerifiedModelFiles>>,
    session: Option<TransformerSession>,
}
fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(message.to_string())
}
impl SentenceEncoder {
    pub fn new(
        model: TransformerModel,
        source: ModelFileSource,
        runtime: NativeTransformerRuntime,
        settings: TransformerSettings,
        device_request: TransformerDeviceRequest,
    ) -> Result<Self, ModelError> {
        settings.validate()?;
        if model.role() != TransformerRole::Encoder {
            return Err(invalid("SentenceEncoder requires an encoder registration"));
        }
        Ok(Self {
            model,
            source,
            runtime,
            settings,
            device_request,
            state: Mutex::new(EncoderState::default()),
        })
    }
    fn state(&self) -> Result<MutexGuard<'_, EncoderState>, ModelError> {
        self.state
            .lock()
            .map_err(|_| invalid("sentence encoder state lock poisoned"))
    }
    fn tokens<'a>(&self, state: &'a mut EncoderState) -> Result<&'a TransformerTokens, ModelError> {
        if state.tokens.is_none() {
            state.tokens = Some(TransformerTokens::load(
                &self.model,
                &self.source,
                &self.settings,
            )?);
        }
        state
            .tokens
            .as_ref()
            .ok_or_else(|| invalid("sentence tokenizer absent"))
    }
    fn prepare(
        &self,
        state: &EncoderState,
        device: TransformerDeviceRequest,
    ) -> Result<(Arc<VerifiedModelFiles>, TransformerSession), ModelError> {
        let files = match &state.files {
            Some(files) => files.clone(),
            None => Arc::new(self.model.assets().verify_files(&self.source)?),
        };
        let session = TransformerSession::prepare_requested(
            &self.model,
            files.clone(),
            self.runtime.clone(),
            device,
            self.settings.effective_dtype(),
        )?;
        Ok((files, session))
    }
    fn load(&self, state: &mut EncoderState) -> Result<(), ModelError> {
        if state.session.is_some() {
            return Ok(());
        }
        self.tokens(state)?;
        let (files, session) = self.prepare(state, self.device_request).or_else(|error| {
            if self.device_request == TransformerDeviceRequest::Cpu {
                Err(error)
            } else {
                self.prepare(state, TransformerDeviceRequest::Cpu)
            }
        })?;
        state.files = Some(files);
        state.session = Some(session);
        Ok(())
    }
    pub fn preparation(&self) -> Result<Option<TransformerPreparation>, ModelError> {
        Ok(self.state()?.session.as_ref().map(|s| s.trace().clone()))
    }
    pub fn dim(&self) -> Result<usize, ModelError> {
        let mut state = self.state()?;
        self.load(&mut state)?;
        Ok(self.model.dimension())
    }
    pub fn token_count(&self, text: &str) -> Result<usize, ModelError> {
        let mut state = self.state()?;
        self.tokens(&mut state)?.raw_count(text)
    }
    fn encode(&self, texts: &[&str], query: bool) -> Result<Vec<Vec<f32>>, ModelError> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let mut state = self.state()?;
        self.load(&mut state)?;
        let tokens = self.tokens(&mut state)?;
        let prepared = if query {
            tokens.queries(texts)
        } else {
            tokens.passages(texts)
        }?;
        self.encode_prepared(
            &mut state,
            &prepared,
            |session, batch| session.run(batch, &TransformerOutput::SentenceEncoded),
            |state| self.prepare(state, TransformerDeviceRequest::Cpu),
        )
    }
    // Operations are ordinary fallible native calls, allowing a test decorator
    // to interrupt real inference/rebuilding without product failure switches.
    fn encode_prepared(
        &self,
        state: &mut EncoderState,
        prepared: &crate::PreparedTransformerText,
        mut run: impl FnMut(
            &mut TransformerSession,
            &ken_native_model_api::TransformerBatch,
        ) -> Result<crate::TransformerBatchResult, ModelError>,
        rebuild: impl FnOnce(
            &EncoderState,
        )
            -> Result<(Arc<VerifiedModelFiles>, TransformerSession), ModelError>,
    ) -> Result<Vec<Vec<f32>>, ModelError> {
        fn request(
            session: &mut TransformerSession,
            prepared: &crate::PreparedTransformerText,
            run: &mut impl FnMut(
                &mut TransformerSession,
                &ken_native_model_api::TransformerBatch,
            ) -> Result<crate::TransformerBatchResult, ModelError>,
        ) -> Result<Vec<Vec<f32>>, ModelError> {
            let mut rows = Vec::new();
            for batch in prepared.batches() {
                let result = run(session, batch)?;
                if result.columns == 0
                    || result.columns.checked_mul(result.rows) != Some(result.values.len())
                    || result.rows != batch.input_ids.len()
                {
                    return Err(invalid("invalid sentence batch shape"));
                }
                for row in result.values.chunks_exact(result.columns) {
                    let norm = row
                        .iter()
                        .map(|&v| f64::from(v).powi(2))
                        .sum::<f64>()
                        .sqrt();
                    if row.iter().any(|v| !v.is_finite()) || (norm - 1.0).abs() >= 0.05 {
                        return Err(invalid("sentence output is not finite unit vectors"));
                    }
                    rows.push(row.to_vec());
                }
            }
            prepared.restore(rows)
        }
        let session = state
            .session
            .as_mut()
            .ok_or_else(|| invalid("sentence session absent"))?;
        let result = request(session, prepared, &mut run);
        let rows = if result.is_ok() || session.trace().device == TransformerDevice::Cpu {
            result?
        } else {
            // Publish only after successful CPU construction. A failed CPU run
            // still leaves that successfully prepared replacement permanent.
            let (files, session) = rebuild(state)?;
            state.files = Some(files);
            state.session = Some(session);
            request(
                state
                    .session
                    .as_mut()
                    .ok_or_else(|| invalid("CPU sentence session absent"))?,
                prepared,
                &mut run,
            )?
        };
        Ok(rows
            .into_iter()
            .map(|mut row| {
                let norm = row.iter().map(|v| v * v).sum::<f32>().sqrt().max(1e-12);
                for value in &mut row {
                    *value /= norm;
                }
                row
            })
            .collect())
    }
    pub fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        self.encode(texts, false)
    }
    pub fn embed_queries(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        self.encode(texts, true)
    }
    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError> {
        self.embed_queries(&[text])?
            .pop()
            .ok_or_else(|| invalid("missing query embedding"))
    }
}
#[cfg(test)]
mod tests {
    use super::SentenceEncoder;
    use crate::TransformerSettings;
    use crate::transformer_test_support::fixture;
    use ken_native_model_api::TransformerDeviceRequest;
    #[test]
    fn actual_tiny_cpu_is_lazy_counts_without_weights_then_loads_repeats_and_owns_sources() {
        let (_temp, model, source, runtime) = fixture();
        let snapshot = source.snapshot().to_owned();
        let weights = std::fs::read(snapshot.join("model.safetensors")).unwrap();
        std::fs::remove_file(snapshot.join("model.safetensors")).unwrap();
        let encoder = SentenceEncoder::new(
            model,
            source,
            runtime,
            TransformerSettings {
                batch_size: Some(2),
                ..Default::default()
            },
            TransformerDeviceRequest::Cpu,
        )
        .unwrap();
        assert!(encoder.preparation().unwrap().is_none());
        assert!(encoder.embed_passages(&[]).unwrap().is_empty());
        assert!(encoder.embed_queries(&[]).unwrap().is_empty());
        assert_eq!(encoder.token_count("find red").unwrap(), 2);
        assert!(encoder.preparation().unwrap().is_none());
        assert!(encoder.dim().is_err());
        assert!(encoder.preparation().unwrap().is_none());
        std::fs::write(snapshot.join("model.safetensors"), weights).unwrap();
        assert_eq!(encoder.dim().unwrap(), 4);
        let prepared = encoder.preparation().unwrap().unwrap();
        assert_eq!(
            prepared.device,
            ken_native_model_api::TransformerDevice::Cpu
        );
        assert_eq!(
            prepared.dtype,
            ken_native_model_api::TransformerDtype::Float32
        );
        let rows = encoder
            .embed_passages(&["find red", "red", "find red"])
            .unwrap();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0], rows[2]);
        for row in &rows {
            assert_eq!(row.len(), 4);
            assert!(row.iter().all(|x| x.is_finite()));
            assert!((row.iter().map(|x| x * x).sum::<f32>().sqrt() - 1.0).abs() < 1e-5);
        }
        std::fs::remove_dir_all(&snapshot).unwrap();
        assert_eq!(encoder.token_count("red").unwrap(), 1);
        assert_eq!(encoder.embed_query("red").unwrap(), rows[1]);
    }
    #[test]
    fn actual_concurrent_first_use_shares_one_session_and_source_copy() {
        let (_temp, model, source, runtime) = fixture();
        let encoder = std::sync::Arc::new(
            SentenceEncoder::new(
                model,
                source,
                runtime,
                TransformerSettings::default(),
                TransformerDeviceRequest::Cpu,
            )
            .unwrap(),
        );
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(4));
        let threads: Vec<_> = (0..4)
            .map(|_| {
                let e = encoder.clone();
                let b = barrier.clone();
                std::thread::spawn(move || {
                    b.wait();
                    e.embed_query("find red").unwrap()
                })
            })
            .collect();
        let rows: Vec<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
        assert!(rows.iter().all(|r| r == &rows[0]));
        assert!(encoder.preparation().unwrap().is_some());
    }
    #[test]
    fn unavailable_explicit_cuda_falls_back_to_actual_cpu() {
        let (_temp, model, source, runtime) = fixture();
        let e = SentenceEncoder::new(
            model,
            source,
            runtime,
            TransformerSettings::default(),
            TransformerDeviceRequest::Cuda(usize::MAX),
        )
        .unwrap();
        assert_eq!(e.dim().unwrap(), 4);
        assert_eq!(
            e.preparation().unwrap().unwrap().device,
            ken_native_model_api::TransformerDevice::Cpu
        );
    }
    #[test]
    fn actual_cpu_late_batch_failure_returns_error_then_recovers() {
        let (_temp, model, source, runtime) = fixture();
        let e = SentenceEncoder::new(
            model,
            source,
            runtime,
            TransformerSettings {
                batch_size: Some(1),
                ..Default::default()
            },
            TransformerDeviceRequest::Cpu,
        )
        .unwrap();
        let mut state = e.state().unwrap();
        e.load(&mut state).unwrap();
        let prepared = e
            .tokens(&mut state)
            .unwrap()
            .passages(&["find red", "red"])
            .unwrap();
        let mut calls = 0;
        let outcome = e.encode_prepared(
            &mut state,
            &prepared,
            |session, batch| {
                calls += 1;
                let result = session.run(
                    batch,
                    &ken_native_model_api::TransformerOutput::SentenceEncoded,
                )?;
                if calls == 2 {
                    Err(super::invalid(
                        "test I/O decorator interrupted second actual batch",
                    ))
                } else {
                    Ok(result)
                }
            },
            |_| panic!("CPU errors must not rebuild"),
        );
        assert!(outcome.is_err());
        assert_eq!(calls, 2);
        drop(state);
        assert_eq!(e.embed_passages(&["find red", "red"]).unwrap().len(), 2);
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn actual_mps_failure_rebuilds_cpu_atomically_and_retries_whole_request() {
        use ken_native_model_api::{TransformerDevice, TransformerOutput};
        for failure in ["exception", "nonfinite", "nonunit"] {
            let (_temp, model, source, runtime) = fixture();
            let e = SentenceEncoder::new(
                model,
                source,
                runtime,
                TransformerSettings {
                    batch_size: Some(1),
                    ..Default::default()
                },
                TransformerDeviceRequest::Mps,
            )
            .unwrap();
            let mut state = e.state().unwrap();
            e.load(&mut state).unwrap();
            assert_eq!(
                state.session.as_ref().unwrap().trace().device,
                TransformerDevice::Mps
            );
            let prepared = e
                .tokens(&mut state)
                .unwrap()
                .passages(&["find red", "red"])
                .unwrap();
            let mut calls = Vec::new();
            let rows = e
                .encode_prepared(
                    &mut state,
                    &prepared,
                    |session, batch| {
                        let device = session.trace().device;
                        calls.push(device);
                        let mut result = session.run(batch, &TransformerOutput::SentenceEncoded)?;
                        if device == TransformerDevice::Mps && calls.len() == 2 {
                            match failure {
                                "exception" => {
                                    return Err(super::invalid(
                                        "I/O decorator interrupted actual GPU result",
                                    ));
                                }
                                "nonfinite" => result.values[0] = f32::NAN,
                                "nonunit" => result.values.fill(0.0),
                                _ => unreachable!(),
                            }
                        }
                        Ok(result)
                    },
                    |state| e.prepare(state, TransformerDeviceRequest::Cpu),
                )
                .unwrap();
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
            drop(state);
            assert_eq!(rows, e.embed_passages(&["find red", "red"]).unwrap());
        }
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn failed_actual_cpu_rebuild_keeps_previous_mps_and_successful_rebuild_commits_before_retry() {
        use ken_native_model_api::{TransformerDevice, TransformerOutput};
        let (_temp, model, source, runtime) = fixture();
        let e = SentenceEncoder::new(
            model,
            source,
            runtime,
            TransformerSettings::default(),
            TransformerDeviceRequest::Mps,
        )
        .unwrap();
        let mut state = e.state().unwrap();
        e.load(&mut state).unwrap();
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Mps
        );
        let prepared = e.tokens(&mut state).unwrap().passages(&["red"]).unwrap();
        let files = state.files.as_ref().unwrap().clone();
        let weights = files.artifact_path("model.safetensors").unwrap();
        let original = std::fs::read(&weights).unwrap();
        std::fs::remove_file(&weights).unwrap();
        std::fs::write(
            &weights,
            b"damaged owned source at actual CPU construction boundary",
        )
        .unwrap();
        assert!(
            e.encode_prepared(
                &mut state,
                &prepared,
                |_, _| Err(super::invalid("interrupted actual GPU call")),
                |state| e.prepare(state, TransformerDeviceRequest::Cpu)
            )
            .is_err()
        );
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Mps
        );
        std::fs::remove_file(&weights).unwrap();
        std::fs::write(&weights, original).unwrap();
        assert!(
            e.encode_prepared(
                &mut state,
                &prepared,
                |session, batch| {
                    let _ = session.run(batch, &TransformerOutput::SentenceEncoded)?;
                    Err(super::invalid(
                        "interrupt after real inference on each device",
                    ))
                },
                |state| e.prepare(state, TransformerDeviceRequest::Cpu)
            )
            .is_err()
        );
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Cpu
        );
        drop(state);
        assert!(e.embed_query("red").is_ok());
    }
}
