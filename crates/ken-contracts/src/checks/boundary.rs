use super::{Result, invalid};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    time::Duration,
};
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QueryRequest {
    pub root: PathBuf,
    pub source: String,
    pub query_name: Option<String>,
    pub libraries: BTreeMap<String, String>,
    pub path: String,
    pub source_paths: Option<Vec<String>>,
    pub timeout_ms: Option<f64>,
    pub max_states: Option<u64>,
    pub max_rows: Option<u64>,
    pub source_profile: String,
}
/// The host owns real native query application and hard process supervision.
/// identity includes query implementation/catalog/policy revisions, never a label
/// inferred from a successful result or an absent worker.
pub trait QueryEngine {
    fn identity(&self) -> String;
    fn checkpoint(&self) -> Result<()> {
        Ok(())
    }
    /// Native implementations poll during the actual resource hash; the legacy
    /// default preserves existing controlled providers and checks its boundary.
    fn identity_checked(&self, check: &mut dyn FnMut() -> Result<()>) -> Result<String> {
        self.checkpoint()?;
        check()?;
        let identity = self.identity();
        self.checkpoint()?;
        check()?;
        Ok(identity)
    }
    fn run(&mut self, request: &QueryRequest) -> Result<Value>;
    fn run_observation(&mut self, request: &QueryRequest) -> Result<super::Observation> {
        super::Observation::from_json(&self.run(request)?)
    }
    fn observe(
        &mut self,
        request: &QueryRequest,
        inputs: &mut dyn SourceInputs,
    ) -> Result<super::Observation> {
        super::execution::evaluate(request, self, inputs)
    }
    fn observe_batch(
        &mut self,
        request: &QueryRequest,
        queries: &BTreeMap<String, String>,
        seeds: Option<&[String]>,
        incoming: bool,
        inputs: &mut dyn SourceInputs,
    ) -> Result<super::BatchObservation> {
        super::execution::evaluate_batch(request, queries, seeds, incoming, self, inputs)
    }
}
pub trait ModuleResolver {
    fn resolve(
        &mut self,
        root: &Path,
        source: &str,
        explicit: &BTreeMap<String, String>,
    ) -> Result<BTreeMap<String, String>>;
}
/// Standalone explicit libraries; registry/catalog discovery remains the host's.
pub struct ExplicitModules;
impl ModuleResolver for ExplicitModules {
    fn resolve(
        &mut self,
        _: &Path,
        _: &str,
        explicit: &BTreeMap<String, String>,
    ) -> Result<BTreeMap<String, String>> {
        Ok(explicit.clone())
    }
}
pub trait SourceInputs {
    fn checkpoint(&self) -> Result<()> {
        Ok(())
    }
    fn capture(&mut self, root: &Path, scope: &str, budget: Duration) -> Result<Value>;
    fn dependencies(&mut self, root: &Path, snapshot: &Value, budget: Duration) -> Result<Value>;
    fn changed_paths(&mut self, root: &Path) -> Result<Vec<String>> {
        super::selection::changed_paths(root)
    }
    fn select(
        &mut self,
        _root: &Path,
        _snapshot: &Value,
        _seeds: &[String],
        _incoming: bool,
        _budget: Duration,
    ) -> Result<Value> {
        Err(invalid("native source selection provider unavailable"))
    }
}
pub trait Clock {
    fn now(&self) -> String;
    fn run_id(&self) -> String;
}
