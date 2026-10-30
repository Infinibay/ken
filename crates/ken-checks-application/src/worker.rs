//! Child protocol: the checked observation bracket is executed exactly once.
use crate::{
    Error, Result, contract,
    native::{NativeEngine, NativeInputs},
    process,
    resources::{Resources, WorkerControl, WorkerResources},
};
use ken_contracts::checks::{
    self, BatchObservation, Observation, QueryEngine, QueryRequest, SourceInputs,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    sync::Arc,
    time::{Duration, Instant},
};
const FORMAT: &str = "ken-native-check-worker/1";
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Task {
    Observe {
        request: QueryRequest,
    },
    Batch {
        request: QueryRequest,
        queries: BTreeMap<String, String>,
        seeds: Option<Vec<String>>,
        incoming: bool,
    },
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    expected_identity: String,
    remaining_ms: f64,
    resources: WorkerResources,
    task: Task,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Reply {
    format: String,
    identity: String,
    result: Box<RawValue>,
}
/// Bound serialization work and allocation while retaining the ordinary serde wire.
pub(crate) struct CheckedWriter<'a, C: FnMut() -> Result<()>> {
    check: &'a mut C,
    bytes: Vec<u8>,
    maximum: usize,
}
impl<'a, C: FnMut() -> Result<()>> CheckedWriter<'a, C> {
    pub(crate) fn new(check: &'a mut C, maximum: usize) -> Self {
        Self {
            check,
            bytes: Vec::new(),
            maximum,
        }
    }
    pub(crate) fn finish(self) -> Vec<u8> {
        self.bytes
    }
}
impl<C: FnMut() -> Result<()>> Write for CheckedWriter<'_, C> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        for chunk in bytes.chunks(8192) {
            (self.check)().map_err(std::io::Error::other)?;
            if chunk.len() > self.maximum.saturating_sub(self.bytes.len()) {
                return Err(std::io::Error::other(
                    "query worker request exceeds configured byte limit",
                ));
            }
            self.bytes.extend_from_slice(chunk);
        }
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        (self.check)().map_err(std::io::Error::other)
    }
}
pub(crate) struct SupervisedEngine {
    pub resources: Arc<Resources>,
    pub control: WorkerControl,
}
impl SupervisedEngine {
    fn invoke(&self, task: Task, timeout: Option<f64>) -> Result<(Box<RawValue>, Instant)> {
        let start = Instant::now();
        let timeout = timeout.unwrap_or(10000.);
        if !timeout.is_finite() || !(0.0..=120000.).contains(&timeout) {
            return Err(Error::Invalid("invalid execution budget".into()));
        }
        let duration = Duration::try_from_secs_f64(timeout / 1000.)
            .map_err(|_| Error::Invalid("invalid execution budget".into()))?;
        let own = start
            .checked_add(duration)
            .ok_or_else(|| Error::Invalid("invalid execution budget".into()))?;
        let deadline = self.control.deadline.map_or(own, |d| d.min(own));
        if self.control.cancellation.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if Instant::now() >= deadline {
            return Err(Error::Timeout);
        }
        let mut check = || {
            if self.control.cancellation.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if Instant::now() >= deadline {
                return Err(Error::Timeout);
            }
            Ok(())
        };
        let identity = self.resources.identity_checked(&mut check)?;
        let request = Request {
            format: FORMAT.into(),
            expected_identity: identity.clone(),
            remaining_ms: deadline
                .saturating_duration_since(Instant::now())
                .as_secs_f64()
                * 1000.,
            resources: self.resources.packet(),
            task,
        };
        let mut encoded =
            CheckedWriter::new(&mut check, self.resources.worker_limits.max_request_bytes);
        let serialization = serde_json::to_writer(&mut encoded, &request);
        let input = encoded.finish();
        check()?;
        serialization?;
        let output = process::invoke(
            &self.resources.worker,
            &self.resources.worker_limits,
            &input,
            deadline,
            &self.control,
        )?;
        let reply: Reply = serde_json::from_slice(&output)
            .map_err(|e| Error::Worker(format!("invalid query worker response: {e}")))?;
        if Instant::now() >= deadline {
            return Err(Error::Timeout);
        }
        if reply.format != FORMAT || reply.identity != identity {
            return Err(Error::Worker(
                "query worker implementation identity changed".into(),
            ));
        }
        if self.control.cancellation.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok((reply.result, deadline))
    }
}
impl QueryEngine for SupervisedEngine {
    fn checkpoint(&self) -> checks::Result<()> {
        self.control.checkpoint().map_err(contract)
    }
    fn identity_checked(
        &self,
        check: &mut dyn FnMut() -> checks::Result<()>,
    ) -> checks::Result<String> {
        self.resources
            .identity_checked(&mut || {
                self.control.checkpoint()?;
                check().map_err(|error| Error::Invalid(error.to_string()))
            })
            .map_err(contract)
    }
    fn identity(&self) -> String {
        self.resources
            .identity()
            .unwrap_or_else(|e| format!("unavailable native engine: {e}"))
    }
    fn run(&mut self, request: &QueryRequest) -> checks::Result<Value> {
        self.run_observation(request)?.to_json()
    }
    fn run_observation(&mut self, request: &QueryRequest) -> checks::Result<Observation> {
        {
            let mut inputs =
                NativeInputs::with_control(self.resources.catalog.clone(), self.control.clone());
            self.observe(request, &mut inputs)
        }
    }
    fn observe(
        &mut self,
        request: &QueryRequest,
        _inputs: &mut dyn SourceInputs,
    ) -> checks::Result<Observation> {
        let (result, deadline) = self
            .invoke(
                Task::Observe {
                    request: request.clone(),
                },
                request.timeout_ms,
            )
            .map_err(contract)?;
        let observation = Observation::parse(result.get())?;
        if self.control.cancellation.is_cancelled() {
            return Err(contract("cancelled"));
        }
        if Instant::now() >= deadline {
            return Err(contract("timeout"));
        }
        Ok(observation)
    }
    fn observe_batch(
        &mut self,
        request: &QueryRequest,
        queries: &BTreeMap<String, String>,
        seeds: Option<&[String]>,
        incoming: bool,
        _inputs: &mut dyn SourceInputs,
    ) -> checks::Result<BatchObservation> {
        let (result, deadline) = self
            .invoke(
                Task::Batch {
                    request: request.clone(),
                    queries: queries.clone(),
                    seeds: seeds.map(<[String]>::to_vec),
                    incoming,
                },
                request.timeout_ms,
            )
            .map_err(contract)?;
        let batch: BatchObservation = serde_json::from_str(result.get())?;
        if self.control.cancellation.is_cancelled() {
            return Err(contract("cancelled"));
        }
        if Instant::now() >= deadline {
            return Err(contract("timeout"));
        }
        Ok(batch)
    }
}
/// The binary calls this before any project/query work. No model factory, daemon
/// connection, registry mutation or analyzed-module import participates.
pub fn worker_main(mut input: impl Read, mut output: impl Write) -> Result<()> {
    let started = Instant::now();
    let mut bytes = Vec::new();
    input.by_ref().take(16_000_001).read_to_end(&mut bytes)?;
    if bytes.len() > 16_000_000 {
        return Err(Error::Worker("query worker request exceeds16MB".into()));
    }
    let request: Request = serde_json::from_slice(&bytes)?;
    if request.format != FORMAT
        || !request.remaining_ms.is_finite()
        || !(0.0..=120000.).contains(&request.remaining_ms)
    {
        return Err(Error::Invalid("invalid native worker request".into()));
    }
    let deadline = started
        .checked_add(Duration::from_secs_f64(request.remaining_ms / 1000.))
        .ok_or(Error::Timeout)?;
    let control = WorkerControl {
        deadline: Some(deadline),
        ..Default::default()
    };
    control.checkpoint()?;
    let catalog = Arc::new(ken_syntax::GrammarCatalog::prepared(
        &request.resources.grammar_manifest,
    )?);
    let identity = request
        .resources
        .identity_checked(&mut || control.checkpoint())?;
    if identity != request.expected_identity {
        return Err(Error::Worker(
            "query worker implementation identity changed".into(),
        ));
    }
    if Instant::now() >= deadline {
        return Err(Error::Timeout);
    }
    let mut inputs = NativeInputs::with_control(catalog.clone(), control.clone());
    let mut engine = NativeEngine {
        resources: request.resources,
        catalog,
        control,
    };
    let result = match request.task {
        Task::Observe { mut request } => {
            request.timeout_ms = Some(
                deadline
                    .saturating_duration_since(Instant::now())
                    .as_secs_f64()
                    * 1000.,
            );
            serde_json::value::to_raw_value(&checks::execute_observation(
                &request,
                &mut engine,
                &mut inputs,
            ))?
        }
        Task::Batch {
            mut request,
            queries,
            seeds,
            incoming,
        } => {
            request.timeout_ms = Some(
                deadline
                    .saturating_duration_since(Instant::now())
                    .as_secs_f64()
                    * 1000.,
            );
            serde_json::value::to_raw_value(&checks::execute_batch_observation(
                &request,
                &queries,
                seeds.as_deref(),
                incoming,
                &mut engine,
                &mut inputs,
            ))?
        }
    };
    if Instant::now() >= deadline {
        return Err(Error::Timeout);
    }
    serde_json::to_writer(
        &mut output,
        &Reply {
            format: FORMAT.into(),
            identity,
            result,
        },
    )?;
    output.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn private_task_roundtrip_keeps_f64_budget_with_arbitrary_precision() {
        // Internally tagged enums buffer through Serde Content; serde_json's
        // arbitrary-precision number marker then reaches f64 as a map.
        // External tagging lets the typed request deserialize its budget directly.
        for task in [
            Task::Observe { request: request() },
            Task::Batch {
                request: request(),
                queries: BTreeMap::from([("q".into(), "select 1".into())]),
                seeds: Some(vec!["source.py".into()]),
                incoming: true,
            },
        ] {
            let encoded = serde_json::to_string(&task).unwrap();
            let decoded: Task = serde_json::from_str(&encoded).unwrap();
            let request = match decoded {
                Task::Observe { request } | Task::Batch { request, .. } => request,
            };
            assert_eq!(request.timeout_ms, Some(10000.25));
            assert_eq!(request.max_states, Some(200000));
            assert_eq!(request.root, std::path::PathBuf::from("/native/project"));
        }
    }
    #[test]
    fn parent_identity_and_encoding_poll_during_work() {
        use std::path::PathBuf;
        let manifest =
            PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar"));
        let resources = Resources::prepared(
            &manifest,
            crate::WorkerProgram::new("/native/missing-worker".into()),
        )
        .unwrap();
        let start = Instant::now();
        let expected = resources.identity().unwrap();
        let full = start.elapsed();
        let start = Instant::now();
        let mut polls = 0;
        let error = resources
            .identity_checked(&mut || {
                polls += 1;
                if polls == 5 {
                    Err(Error::Cancelled)
                } else {
                    Ok(())
                }
            })
            .unwrap_err();
        let interrupted = start.elapsed();
        assert!(matches!(error, Error::Cancelled));
        assert_eq!(polls, 5);
        assert_eq!(
            resources.identity_checked(&mut || Ok(())).unwrap(),
            expected
        );
        let mut polls = 0;
        let mut check = || {
            polls += 1;
            if polls == 3 {
                Err(Error::Cancelled)
            } else {
                Ok(())
            }
        };
        let mut writer = CheckedWriter::new(&mut check, 100000);
        assert!(writer.write_all(&vec![b'x'; 65536]).is_err());
        assert_eq!(writer.finish().len(), 16384);
        assert_eq!(polls, 3);
        eprintln!(
            "native parent phase proof: full_identity={full:?}, cancelled_identity={interrupted:?}; identity stopped on callback5, encode stopped on chunk3"
        );
    }
    fn request() -> QueryRequest {
        QueryRequest {
            root: "/native/project".into(),
            source: r#"language "kql/2";module q;query q{select "\ud800";}"#.into(),
            query_name: None,
            libraries: BTreeMap::new(),
            path: "src".into(),
            source_paths: None,
            timeout_ms: Some(10000.25),
            max_states: Some(200000),
            max_rows: Some(100),
            source_profile: "full".into(),
        }
    }
}
