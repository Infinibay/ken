//! Coalescing and publication state are separate from host timers/workers. A host
//! claims under its lock, executes the batch outside it, then completes under it.
use super::{Result, model::digest};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path, PathBuf},
    time::Duration,
};
pub fn message(receipt: &Value) -> String {
    super::RawReport::new(receipt)
        .and_then(|r| message_report(&r))
        .unwrap_or_default()
}
pub fn message_report(receipt: &super::RawReport) -> Result<String> {
    let fields: super::observation::Fields = serde_json::from_str(receipt.json())?;
    let mut lines = Vec::new();
    if let Some(checks) = fields.get("checks") {
        for check in super::observation::decode::<Vec<super::observation::Fields>>(checks)? {
            let read = |key: &str| {
                check
                    .get(key)
                    .and_then(|v| super::observation::decode::<String>(v).ok())
                    .unwrap_or_else(|| "?".into())
            };
            lines.push(format!("{}: {}", read("rule"), read("status")));
        }
    }
    if let Some(skipped) = fields.get("skipped_rules") {
        for rule in super::observation::decode::<Vec<Value>>(skipped)? {
            lines.push(format!(
                "{}: {}",
                rule["rule"].as_str().unwrap_or("?"),
                rule["reason"].as_str().unwrap_or("unknown")
            ));
        }
    }
    if let Some(comparison) = fields.get("comparison") {
        let comparison: Value = super::observation::decode(comparison)?;
        for change in comparison["changes"].as_array().into_iter().flatten() {
            let state = change["change"].as_str().unwrap_or("");
            if ["regression", "resolved", "inconclusive"].contains(&state) {
                lines.push(format!(
                    "{}: {state}",
                    change["rule"].as_str().unwrap_or("?")
                ));
            }
        }
    }
    if lines.is_empty() {
        return Ok(String::new());
    }
    let run_id = fields
        .get("run_id")
        .map(|v| super::observation::decode::<String>(v))
        .transpose()?
        .unwrap_or_default();
    Ok(format!(
        "<ken-checks>\n{}\nScope: selected source contracts. Inspect: ken_check(run_id=\"{}\", full=true).\n</ken-checks>",
        lines.join("; ").chars().take(900).collect::<String>(),
        run_id
    ))
}

#[derive(Debug, Clone)]
pub struct Job {
    pub session: String,
    pub paths: Vec<String>,
    pub compare: String,
    pub timeout_ms: u64,
}
impl Job {
    pub fn request(&self) -> Value {
        serde_json::json!({"scope":"changes","automatic":true,"touched":if self.paths.is_empty(){Value::Null}else{serde_json::json!(self.paths)},"compare":self.compare,"timeout_ms":self.timeout_ms})
    }
}
#[derive(Debug, Clone)]
pub struct Batch {
    token: u64,
    pub jobs: Vec<Job>,
}
pub struct Scheduler {
    delay: Duration,
    timeout_ms: u64,
    pending: BTreeMap<String, BTreeSet<String>>,
    notices: BTreeMap<String, String>,
    signatures: BTreeMap<String, String>,
    baselines: BTreeMap<String, String>,
    due: Option<Duration>,
    running: Option<u64>,
    generation: u64,
    closed: bool,
}
impl Scheduler {
    pub fn new(delay: Duration, timeout_ms: u64) -> Self {
        Self {
            delay,
            timeout_ms,
            pending: BTreeMap::new(),
            notices: BTreeMap::new(),
            signatures: BTreeMap::new(),
            baselines: BTreeMap::new(),
            due: None,
            running: None,
            generation: 0,
            closed: false,
        }
    }
    pub fn enqueue(
        &mut self,
        session: &str,
        paths: &[String],
        has_automatic_rules: bool,
        now: Duration,
    ) {
        if self.closed || !has_automatic_rules {
            return;
        }
        self.pending
            .entry(session.to_owned())
            .or_default()
            .extend(paths.iter().cloned());
        if self.running.is_none() {
            self.due = Some(now.saturating_add(self.delay));
        }
    }
    pub fn take_ready(&mut self, now: Duration) -> Option<Batch> {
        if self.closed || self.running.is_some() || self.due.is_none_or(|due| now < due) {
            return None;
        }
        self.generation = self.generation.wrapping_add(1);
        let token = self.generation;
        self.running = Some(token);
        self.due = None;
        let jobs = std::mem::take(&mut self.pending)
            .into_iter()
            .map(|(session, paths)| Job {
                compare: self.baselines.get(&session).cloned().unwrap_or_default(),
                session,
                paths: paths.into_iter().collect(),
                timeout_ms: self.timeout_ms,
            })
            .collect();
        Some(Batch { token, jobs })
    }
    pub fn complete(&mut self, batch: &Batch, results: &[Result<Value>], now: Duration) {
        let reports = results
            .iter()
            .map(|r| match r {
                Ok(v) => super::RawReport::new(v),
                Err(e) => Err(super::invalid(e.to_string())),
            })
            .collect::<Vec<_>>();
        self.complete_reports(batch, &reports, now);
    }
    pub fn complete_reports(
        &mut self,
        batch: &Batch,
        results: &[Result<super::RawReport>],
        now: Duration,
    ) {
        if self.closed || self.running != Some(batch.token) {
            return;
        }
        for (job, result) in batch.jobs.iter().zip(results) {
            let Ok(receipt) = result else { continue };
            let prepared = (|| -> Result<Option<(String, String, String)>> {
                let mut fields: super::observation::Fields = serde_json::from_str(receipt.json())?;
                let compact = if fields.contains_key("version") {
                    super::receipt_report(&super::Receipt::parse(receipt.json())?, false)?
                } else {
                    receipt.clone()
                };
                fields = serde_json::from_str(compact.json())?;
                let truth = |key: &str| {
                    fields
                        .get(key)
                        .is_some_and(|v| super::observation::truth(v))
                };
                if !truth("checks") && !truth("skipped_rules") {
                    return Ok(None);
                }
                let signature_payload = super::observation::raw(&[
                    fields
                        .get("checks")
                        .cloned()
                        .unwrap_or(super::observation::raw(&Value::Null)?),
                    fields
                        .get("skipped_rules")
                        .cloned()
                        .unwrap_or(super::observation::raw(&Value::Null)?),
                ])?;
                let signature =
                    if let Ok(value) = serde_json::from_str::<Value>(signature_payload.get()) {
                        digest(&value)
                    } else {
                        use sha2::{Digest, Sha256};
                        format!("{:x}", Sha256::digest(signature_payload.get().as_bytes()))
                    };
                let run_id = fields
                    .get("run_id")
                    .map(|v| super::observation::decode::<String>(v))
                    .transpose()?
                    .unwrap_or_default();
                Ok(Some((signature, message_report(&compact)?, run_id)))
            })();
            let Ok(Some((signature, notice, run_id))) = prepared else {
                continue;
            };
            if self.signatures.get(&job.session) != Some(&signature) {
                self.notices.insert(job.session.clone(), notice);
                self.signatures.insert(job.session.clone(), signature);
            }
            if !run_id.is_empty() {
                self.baselines.insert(job.session.clone(), run_id);
            }
        }
        self.running = None;
        if !self.pending.is_empty() {
            self.due = Some(now.saturating_add(self.delay));
        }
    }

    pub fn drain(&mut self, session: &str) -> String {
        self.notices.remove(session).unwrap_or_default()
    }
    pub fn close(&mut self) {
        self.closed = true;
        self.pending.clear();
        self.due = None;
        self.running = None;
        self.generation = self.generation.wrapping_add(1);
    }
    pub fn next_due(&self) -> Option<Duration> {
        self.due
    }
    pub fn is_running(&self) -> bool {
        self.running.is_some()
    }
    pub fn is_closed(&self) -> bool {
        self.closed
    }
}
fn normalized(root: &Path, value: &str) -> Option<PathBuf> {
    let mut path = if Path::new(value).is_absolute() {
        PathBuf::new()
    } else {
        root.to_path_buf()
    };
    for part in Path::new(value).components() {
        match part {
            Component::ParentDir => {
                path.pop();
            }
            Component::CurDir => {}
            other => path.push(other),
        }
    }
    let mut ancestor = path.as_path();
    let mut tail = Vec::new();
    while !ancestor.exists() {
        tail.push(ancestor.file_name()?.to_owned());
        ancestor = ancestor.parent()?;
    }
    let mut resolved = ancestor.canonicalize().ok()?;
    for part in tail.into_iter().rev() {
        resolved.push(part);
    }
    resolved.strip_prefix(root).ok().map(Path::to_path_buf)
}
pub fn edited_paths(root: &Path, input: &Value, target: Option<&str>) -> Vec<String> {
    let Ok(root) = root.canonicalize() else {
        return Vec::new();
    };
    let mut values = target.into_iter().map(str::to_owned).collect::<Vec<_>>();
    let patch = input
        .as_str()
        .or_else(|| input["patch"].as_str())
        .unwrap_or("");
    for line in patch.lines() {
        for prefix in ["*** Update File: ", "*** Add File: ", "*** Delete File: "] {
            if let Some(path) = line.strip_prefix(prefix) {
                values.push(path.to_owned());
                break;
            }
        }
    }
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for value in values {
        if let Some(path) = normalized(&root, &value) {
            if path
                .components()
                .any(|p| p.as_os_str() == ".ken" || p.as_os_str() == ".git")
            {
                continue;
            }
            let path = path.to_string_lossy().into_owned();
            if seen.insert(path.clone()) {
                out.push(path);
            }
        }
    }
    out
}
