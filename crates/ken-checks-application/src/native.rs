//! Concrete query/modules/source ports; no duplicated query or import semantics.
use crate::{Resources, WorkerControl, contract, resources::WorkerResources};
use ken_contracts::checks::{
    self, ModuleResolver, Observation, QueryEngine, QueryRequest, SourceInputs,
};
use ken_structural::application::{
    inspection::{self, NativeSources},
    modules,
    sessions::{QueryApplication, QueryOptions, SessionError, SessionOptions, SourceProfile},
};
use std::{
    collections::BTreeMap,
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};
pub(crate) struct NativeInputs {
    sources: NativeSources,
    control: WorkerControl,
}
impl NativeInputs {
    pub fn with_control(catalog: Arc<ken_syntax::GrammarCatalog>, control: WorkerControl) -> Self {
        Self {
            sources: NativeSources::new(catalog),
            control,
        }
    }
}
impl SourceInputs for NativeInputs {
    fn checkpoint(&self) -> checks::Result<()> {
        self.control.checkpoint().map_err(contract)
    }
    fn changed_paths(&mut self, root: &Path) -> checks::Result<Vec<String>> {
        checks::changed_paths_checked(root, &mut || self.control.checkpoint().map_err(contract))
    }
    fn capture(
        &mut self,
        root: &Path,
        scope: &str,
        budget: Duration,
    ) -> checks::Result<serde_json::Value> {
        checks::capture_sources_checked(root, scope, budget, &mut || {
            self.control.checkpoint().map_err(contract)
        })
    }
    fn dependencies(
        &mut self,
        root: &Path,
        snapshot: &serde_json::Value,
        budget: Duration,
    ) -> checks::Result<serde_json::Value> {
        self.checkpoint()?;
        let control = self.control.within(budget).map_err(contract)?;
        let mut sources = ControlledSources {
            inner: &mut self.sources,
            control,
        };
        let result =
            inspection::dependencies(root, snapshot, &mut sources, budget).map_err(contract);
        self.checkpoint()?;
        result
    }
    fn select(
        &mut self,
        root: &Path,
        snapshot: &serde_json::Value,
        seeds: &[String],
        incoming: bool,
        budget: Duration,
    ) -> checks::Result<serde_json::Value> {
        self.checkpoint()?;
        let control = self.control.within(budget).map_err(contract)?;
        let mut sources = ControlledSources {
            inner: &mut self.sources,
            control,
        };
        let result =
            inspection::select_sources(root, snapshot, seeds, incoming, &mut sources, budget)
                .map_err(contract);
        self.checkpoint()?;
        result
    }
}
pub(crate) struct RegisteredModules {
    pub packaged: BTreeMap<String, String>,
    pub control: WorkerControl,
}
impl ModuleResolver for RegisteredModules {
    fn resolve(
        &mut self,
        root: &Path,
        source: &str,
        explicit: &BTreeMap<String, String>,
    ) -> checks::Result<BTreeMap<String, String>> {
        self.control.checkpoint().map_err(contract)?;
        let mut resolver = modules::ModuleResolver::new(root, self.packaged.clone());
        let result = resolver
            .resolve(Some(source), None, None, Some(explicit))
            .map(|r| r.libraries().clone())
            .map_err(contract);
        let closed = resolver.close().map_err(contract);
        self.control.checkpoint().map_err(contract)?;
        match result {
            Ok(value) => {
                closed?;
                Ok(value)
            }
            Err(error) => Err(error),
        }
    }
}
pub(crate) struct NativeEngine {
    pub resources: WorkerResources,
    pub catalog: Arc<ken_syntax::GrammarCatalog>,
    pub control: WorkerControl,
}
impl QueryEngine for NativeEngine {
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
                check().map_err(|error| crate::Error::Invalid(error.to_string()))
            })
            .map_err(contract)
    }
    fn identity(&self) -> String {
        self.resources
            .identity()
            .unwrap_or_else(|e| format!("unavailable native engine: {e}"))
    }
    fn run(&mut self, request: &QueryRequest) -> checks::Result<serde_json::Value> {
        self.run_observation(request)?.to_json()
    }
    fn run_observation(&mut self, request: &QueryRequest) -> checks::Result<Observation> {
        let start = Instant::now();
        let own = request
            .timeout_ms
            .map(|ms| {
                Duration::try_from_secs_f64(ms / 1000.)
                    .ok()
                    .and_then(|d| start.checked_add(d))
                    .ok_or_else(|| contract("invalid execution budget"))
            })
            .transpose()?;
        let deadline = match (own, self.control.deadline) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        };
        let control = self.control.clone();
        let mut check = || {
            if control.cancellation.is_cancelled() {
                return Err(SessionError::Invalid("cancelled".into()));
            }
            if deadline.is_some_and(|d| Instant::now() >= d) {
                return Err(SessionError::Invalid("timeout".into()));
            }
            Ok(())
        };
        let profile = match request.source_profile.as_str() {
            "full" => SourceProfile::Full,
            "local_hazards" => SourceProfile::LocalHazards,
            _ => return Err(contract("unsupported preparation profile")),
        };
        let app = QueryApplication::new(
            &request.root,
            self.catalog.clone(),
            self.resources.packaged_libraries.clone(),
        )
        .map_err(contract)?;
        let mut session = app
            .open_checked(
                SessionOptions {
                    path: request.path.clone().into(),
                    cache_mb: self.resources.cache_mb,
                    max_file_bytes: self.resources.max_file_bytes,
                    source_paths: request.source_paths.clone(),
                    source_profile: profile,
                },
                &mut check,
            )
            .map_err(contract)?;
        let result = session
            .search_json(
                Some(&request.source),
                QueryOptions {
                    query_name: request.query_name.clone(),
                    libraries: Some(request.libraries.clone()),
                    timeout_ms: request.timeout_ms,
                    deadline,
                    max_states: request.max_states,
                    max_rows: request.max_rows,
                    include_entities: true,
                    cancellation: control.cancellation,
                    ..Default::default()
                },
            )
            .map_err(contract);
        let closed = session.close().map_err(contract);
        match result {
            Ok(text) => {
                closed?;
                Observation::parse(&text)
            }
            Err(error) => Err(error),
        }
    }
}
pub(crate) fn inputs(resources: &Resources, control: WorkerControl) -> NativeInputs {
    NativeInputs::with_control(resources.catalog.clone(), control)
}

struct ControlledSources<'a> {
    inner: &'a mut NativeSources,
    control: WorkerControl,
}
impl inspection::InspectionSources for ControlledSources<'_> {
    fn checkpoint(&self) -> inspection::Result<()> {
        self.control
            .checkpoint()
            .map_err(|error| inspection::InspectionError::Invalid(error.to_string()))
    }
    fn capture(
        &mut self,
        root: &Path,
        scope: &str,
        budget: Duration,
    ) -> inspection::Result<serde_json::Value> {
        checks::capture_sources_checked(root, scope, budget, &mut || {
            self.control.checkpoint().map_err(contract)
        })
        .map_err(|error| inspection::InspectionError::Invalid(error.to_string()))
    }
    fn facts(
        &mut self,
        root: &Path,
        path: &str,
        budget: Duration,
    ) -> inspection::Result<inspection::SourceFacts> {
        self.checkpoint()?;
        let result = inspection::InspectionSources::facts(self.inner, root, path, budget);
        self.checkpoint()?;
        result
    }
}
