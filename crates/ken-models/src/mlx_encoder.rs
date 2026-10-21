//! Original MLX encoder lifecycle, without CPU fallback.
use crate::{
    ModelError, ModelFileSource, NativeTransformerRuntime, TransformerModel,
    TransformerPreparation, TransformerRole, TransformerSession, TransformerSettings,
    TransformerTokens,
};
use ken_native_model_api::{TransformerArchitecture, TransformerDevice, TransformerOutput};
use std::sync::{Arc, Mutex, MutexGuard};
fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(message.to_string())
}
#[derive(Default)]
struct State {
    tokens: Option<TransformerTokens>,
    session: Option<TransformerSession>,
}
/// One serialized lazy model. Native MLX failures propagate without changing device.
pub struct MLXEncoder {
    model: TransformerModel,
    source: ModelFileSource,
    runtime: NativeTransformerRuntime,
    settings: TransformerSettings,
    state: Mutex<State>,
}
impl MLXEncoder {
    pub fn new(
        model: TransformerModel,
        source: ModelFileSource,
        runtime: NativeTransformerRuntime,
        settings: TransformerSettings,
    ) -> Result<Self, ModelError> {
        settings.validate()?;
        if model.architecture() != TransformerArchitecture::Qwen3
            || model.role() != TransformerRole::Encoder
            || runtime.backend() != "mlx"
        {
            return Err(invalid(
                "MLXEncoder requires a Qwen3 encoder registration and MLX runtime",
            ));
        }
        Ok(Self {
            model,
            source,
            runtime,
            settings,
            state: Mutex::new(State::default()),
        })
    }
    fn state(&self) -> Result<MutexGuard<'_, State>, ModelError> {
        self.state
            .lock()
            .map_err(|_| invalid("MLX encoder state lock poisoned"))
    }
    fn tokens<'a>(&self, state: &'a mut State) -> Result<&'a TransformerTokens, ModelError> {
        if state.tokens.is_none() {
            state.tokens = Some(TransformerTokens::for_mlx(
                &self.model,
                &self.source,
                &self.settings,
            )?);
        }
        state
            .tokens
            .as_ref()
            .ok_or_else(|| invalid("MLX tokenizer absent"))
    }
    fn load(&self, state: &mut State) -> Result<(), ModelError> {
        if state.session.is_some() {
            return Ok(());
        }
        self.tokens(state)?;
        let files = Arc::new(self.model.assets().verify_files(&self.source)?);
        let session = TransformerSession::prepare(
            &self.model,
            files,
            self.runtime.clone(),
            TransformerDevice::Mps,
            self.settings.effective_dtype(),
        )?;
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
        let session = state
            .session
            .as_mut()
            .ok_or_else(|| invalid("MLX session absent"))?;
        Self::run_prepared(session, &prepared, |session, batch| {
            session.run(batch, &TransformerOutput::MLXLast)
        })
    }
    fn run_prepared(
        session: &mut TransformerSession,
        prepared: &crate::PreparedTransformerText,
        mut run: impl FnMut(
            &mut TransformerSession,
            &ken_native_model_api::TransformerBatch,
        ) -> Result<crate::TransformerBatchResult, ModelError>,
    ) -> Result<Vec<Vec<f32>>, ModelError> {
        let mut rows = Vec::new();
        for batch in prepared.batches() {
            let result = run(session, batch)?;
            rows.extend(
                result
                    .values
                    .chunks_exact(result.columns)
                    .map(|r| r.to_vec()),
            );
        }
        prepared.restore(rows)
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
            .ok_or_else(|| invalid("MLX query returned no row"))
    }
}
#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::MLXEncoder;
    use crate::TransformerSettings;
    use crate::transformer_test_support::mlx_runtime as runtime;
    use ken_native_model_api::{TransformerDevice, TransformerDtype};
    #[test]
    fn actual_mlx_is_lazy_count_only_then_owns_sources_and_moves_between_calling_threads() {
        let (_temp, model, source, _unused) = crate::transformer_test_support::fixture();
        let snapshot = source.snapshot().to_owned();
        let weights = std::fs::read(snapshot.join("model.safetensors")).unwrap();
        std::fs::remove_file(snapshot.join("model.safetensors")).unwrap();
        let encoder = std::sync::Arc::new(
            MLXEncoder::new(
                model,
                source,
                runtime(),
                TransformerSettings {
                    sequence_length: Some(8),
                    batch_size: Some(2),
                    ..Default::default()
                },
            )
            .unwrap(),
        );
        assert!(encoder.preparation().unwrap().is_none());
        assert!(encoder.embed_passages(&[]).unwrap().is_empty());
        assert_eq!(encoder.token_count("find red").unwrap(), 2);
        assert!(encoder.preparation().unwrap().is_none());
        assert!(encoder.dim().is_err());
        assert!(encoder.preparation().unwrap().is_none());
        std::fs::write(snapshot.join("model.safetensors"), weights).unwrap();
        assert_eq!(encoder.dim().unwrap(), 4);
        let trace = encoder.preparation().unwrap().unwrap();
        assert_eq!(trace.device, TransformerDevice::Mps);
        assert_eq!(trace.dtype, TransformerDtype::Float32);
        assert_eq!(trace.runtime.backend, "mlx");
        let rows = encoder
            .embed_passages(&["find red", "red", "find red"])
            .unwrap();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0], rows[2]);
        std::fs::remove_dir_all(snapshot).unwrap();
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
        let threads: Vec<_> = (0..3)
            .map(|_| {
                let encoder = encoder.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    assert_eq!(encoder.token_count("red").unwrap(), 1);
                    encoder.embed_query("red").unwrap()
                })
            })
            .collect();
        for thread in threads {
            assert_eq!(thread.join().unwrap(), rows[1]);
        }
        for row in rows {
            assert!(row.iter().all(|v| v.is_finite()));
            assert!((row.iter().map(|v| v * v).sum::<f32>().sqrt() - 1.0).abs() < 1e-5);
        }
    }
    #[test]
    fn actual_zero_hidden_states_return_error_without_cpu_fallback() {
        let (_temp, model, source, _unused) = crate::transformer_test_support::fixture();
        let mut weights = std::fs::read(source.snapshot().join("model.safetensors")).unwrap();
        let length = u64::from_le_bytes(weights[..8].try_into().unwrap()) as usize;
        weights[8 + length..].fill(0);
        let (_temp, zero_model, zero_source, _unused) =
            crate::transformer_test_support::fixture_with_weights(&[], Some(&weights));
        let encoder = MLXEncoder::new(
            zero_model,
            zero_source,
            runtime(),
            TransformerSettings {
                sequence_length: Some(8),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(encoder.dim().unwrap(), model.dimension());
        assert!(encoder.embed_query("red").is_err());
        assert_eq!(
            encoder.preparation().unwrap().unwrap().device,
            TransformerDevice::Mps
        );
        assert!(encoder.embed_query("red").is_err());
    }
    #[test]
    fn actual_mlx_late_failure_returns_no_partial_list_and_keeps_gpu_state() {
        let (_temp, model, source, _unused) = crate::transformer_test_support::fixture();
        let encoder = MLXEncoder::new(
            model,
            source,
            runtime(),
            TransformerSettings {
                sequence_length: Some(8),
                batch_size: Some(1),
                ..Default::default()
            },
        )
        .unwrap();
        let mut state = encoder.state().unwrap();
        encoder.load(&mut state).unwrap();
        let prepared = encoder
            .tokens(&mut state)
            .unwrap()
            .passages(&["find red", "red"])
            .unwrap();
        let mut calls = 0;
        let result = MLXEncoder::run_prepared(
            state.session.as_mut().unwrap(),
            &prepared,
            |session, batch| {
                calls += 1;
                let result =
                    session.run(batch, &ken_native_model_api::TransformerOutput::MLXLast)?;
                if calls == 2 {
                    Err(super::invalid(
                        "test I/O decorator interrupts second actual native result",
                    ))
                } else {
                    Ok(result)
                }
            },
        );
        assert!(result.is_err());
        assert_eq!(calls, 2);
        assert_eq!(
            state.session.as_ref().unwrap().trace().device,
            TransformerDevice::Mps
        );
        drop(state);
        assert_eq!(
            encoder.embed_passages(&["find red", "red"]).unwrap().len(),
            2
        );
    }
}
