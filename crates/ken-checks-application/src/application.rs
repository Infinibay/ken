//! Operation-local composition around the existing contracts Service.
use crate::{
    Resources, Result, WorkerControl,
    clock::NativeClock,
    native::{RegisteredModules, inputs},
    worker::SupervisedEngine,
};
use ken_contracts::checks::{
    self, BatchObservation, Observation, QueryRequest, RawReport, Service, Store,
};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};
#[derive(Clone)]
pub struct ChecksApplication {
    pub(crate) root: Arc<PathBuf>,
    pub(crate) resources: Arc<Resources>,
}
impl ChecksApplication {
    pub fn new(root: &Path, resources: Resources) -> Result<Self> {
        let root = root.canonicalize()?;
        if !root.is_dir() {
            return Err(crate::Error::Invalid(
                "check project root is not a directory".into(),
            ));
        }
        Store::new(&root)?;
        Ok(Self {
            root: Arc::new(root),
            resources: Arc::new(resources.seal()?),
        })
    }
    fn service<T>(
        &self,
        control: WorkerControl,
        operation: impl FnOnce(&mut Service<'_>) -> checks::Result<T>,
    ) -> Result<T> {
        control.checkpoint()?;
        let mut engine = SupervisedEngine {
            resources: self.resources.clone(),
            control: control.clone(),
        };
        let mut inputs = inputs(&self.resources, control.clone());
        let mut resolver = RegisteredModules {
            packaged: self.resources.packaged_libraries.clone(),
            control: control.clone(),
        };
        let clock = NativeClock::new()?;
        control.checkpoint()?;
        let mut service =
            Service::new(&self.root, &mut engine, &mut inputs, &mut resolver, &clock)?;
        Ok(operation(&mut service)?)
    }
    pub fn manage(&self, input: &Value) -> Result<Value> {
        self.manage_with_control(input, &WorkerControl::default())
    }
    pub fn manage_with_control(&self, input: &Value, control: &WorkerControl) -> Result<Value> {
        self.service(request_control(control, input, 30000.)?, |s| {
            s.manage(input)
        })
    }
    pub fn check(&self, input: &Value) -> Result<RawReport> {
        self.check_with_control(input, &WorkerControl::default())
    }
    pub fn check_with_control(&self, input: &Value, control: &WorkerControl) -> Result<RawReport> {
        self.service(request_control(control, input, 10000.)?, |s| {
            s.check_report(input)
        })
    }
    pub fn search(&self, input: &Value) -> Result<RawReport> {
        self.search_with_control(input, &WorkerControl::default())
    }
    pub fn search_with_control(&self, input: &Value, control: &WorkerControl) -> Result<RawReport> {
        self.service(request_control(control, input, 10000.)?, |s| {
            s.search_report(input)
        })
    }
    pub fn related(&self, path: &str, limit: usize) -> Result<RawReport> {
        self.related_with_control(path, limit, &WorkerControl::default())
    }
    pub fn related_with_control(
        &self,
        path: &str,
        limit: usize,
        control: &WorkerControl,
    ) -> Result<RawReport> {
        self.service(control.within(Duration::from_secs(1))?, |service| {
            service.related_report(path, limit)
        })
    }
    pub fn freshness(&self, run_id: &str, budget: Duration) -> Result<Value> {
        self.freshness_with_control(run_id, budget, &WorkerControl::default())
    }
    pub fn freshness_with_control(
        &self,
        run_id: &str,
        budget: Duration,
        control: &WorkerControl,
    ) -> Result<Value> {
        let control = control.within(budget)?;
        self.service(control.clone(), |service| {
            let receipt = service.store().read_receipt_checked(run_id, &mut || {
                control.checkpoint().map_err(crate::contract)
            })?;
            service.freshness_receipt(&receipt, budget)
        })
    }
    pub fn justification(&self, run_id: &str, data: Option<&Value>) -> Result<Value> {
        self.justification_with_control(run_id, data, &WorkerControl::default())
    }
    pub fn justification_with_control(
        &self,
        run_id: &str,
        data: Option<&Value>,
        control: &WorkerControl,
    ) -> Result<Value> {
        self.service(control.within(Duration::from_secs(2))?, |service| {
            service.justification(run_id, data)
        })
    }
    pub fn resume(&self) -> Result<String> {
        self.resume_with_control(&WorkerControl::default())
    }
    pub fn resume_with_control(&self, control: &WorkerControl) -> Result<String> {
        self.service(control.within(Duration::from_millis(500))?, |service| {
            service.resume()
        })
    }
    pub fn observe(&self, request: &QueryRequest, control: &WorkerControl) -> Result<Observation> {
        let mut engine = SupervisedEngine {
            resources: self.resources.clone(),
            control: control.clone(),
        };
        let mut inputs = inputs(&self.resources, control.clone());
        Ok(checks::execute_observation(
            request,
            &mut engine,
            &mut inputs,
        ))
    }
    pub fn observe_batch(
        &self,
        request: &QueryRequest,
        queries: &BTreeMap<String, String>,
        seeds: Option<&[String]>,
        incoming: bool,
        control: &WorkerControl,
    ) -> Result<BatchObservation> {
        let mut engine = SupervisedEngine {
            resources: self.resources.clone(),
            control: control.clone(),
        };
        let mut inputs = inputs(&self.resources, control.clone());
        Ok(checks::execute_batch_observation(
            request,
            queries,
            seeds,
            incoming,
            &mut engine,
            &mut inputs,
        ))
    }
    pub(crate) fn has_automatic_rules(&self) -> Result<bool> {
        Ok(Store::new(&self.root)?
            .rules()?
            .iter()
            .any(|r| r["enabled"] == true && r["automatic"] == true))
    }
}

fn request_control(
    control: &WorkerControl,
    input: &Value,
    default_ms: f64,
) -> Result<WorkerControl> {
    control.checkpoint()?;
    // Domain admission retains its existing validation/error messages. Only valid
    // durations establish the inherited absolute deadline before any service work.
    match input
        .get("timeout_ms")
        .map_or(Some(default_ms), Value::as_f64)
        .filter(|ms| ms.is_finite() && *ms > 0.)
        .and_then(|ms| Duration::try_from_secs_f64(ms / 1000.).ok())
    {
        Some(duration) => control.within(duration),
        None => Ok(control.clone()),
    }
}
