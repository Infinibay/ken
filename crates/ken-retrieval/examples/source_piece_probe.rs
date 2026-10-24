//! Input-only native source scenarios; no compiled references or expected outputs.
#[path = "source_piece/assembly.rs"]
mod assembly;
#[path = "source_piece/cards.rs"]
mod cards;
#[path = "source_piece/catalog.rs"]
mod catalog;
#[path = "source_piece/evidence.rs"]
mod evidence;
#[path = "numeric_owner/features.rs"]
pub mod features;
#[path = "source_piece/presentation.rs"]
mod presentation;
#[path = "numeric_owner/production.rs"]
pub mod production;
#[path = "source_piece/ranking.rs"]
mod ranking;
#[path = "source_piece/scenario.rs"]
mod scenario;
use ken_retrieval::{Result, RetrievalError};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::{BTreeMap, HashSet},
    io::{self, Read, Write},
    path::{Component, PathBuf},
    time::Instant,
};
const FORMAT: &str = "ken-source-piece-probe/1";
const SCOPE: &str = "native input parsing, disposable source scenarios, piece projection/ranking/presentation and registered resource loading, before output serialization";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    resources: Resources,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Resources {
    pub ranking: Option<PathBuf>,
    #[serde(rename = "static")]
    pub static_table: Option<PathBuf>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    family: String,
    kind: String,
    input: Box<RawValue>,
}
pub type Observation = BTreeMap<String, Box<RawValue>>;
pub struct Failure {
    kind: &'static str,
    message: String,
}
pub type ScenarioResult<T> = std::result::Result<T, Failure>;
impl From<RetrievalError> for Failure {
    fn from(e: RetrievalError) -> Self {
        Self {
            kind: match &e {
                RetrievalError::Numeric(e) => e.kind(),
                RetrievalError::MissingField(_) => "KeyError",
                _ => "ValueError",
            },
            message: e.to_string(),
        }
    }
}
impl From<ken_retrieval::source_snapshot::SourceError> for Failure {
    fn from(e: ken_retrieval::source_snapshot::SourceError) -> Self {
        Self {
            kind: e.kind(),
            message: e.to_string(),
        }
    }
}
impl From<serde_json::Error> for Failure {
    fn from(e: serde_json::Error) -> Self {
        Self {
            kind: "ValueError",
            message: e.to_string(),
        }
    }
}
pub fn finish_observation(
    result: ScenarioResult<Box<RawValue>>,
    extra: Observation,
) -> Observation {
    let mut out = extra;
    match result {
        Ok(value) => {
            out.insert("result".into(), value);
        }
        Err(e) => {
            out.insert(
                "error".into(),
                raw(&json!({"type":e.kind,"message":e.message})).expect("scalar failure"),
            );
        }
    }
    out
}
pub fn fields(text: &str, allowed: &[&str], extra: &[&str]) -> Result<()> {
    let values: BTreeMap<String, Box<RawValue>> = serde_json::from_str(text)?;
    if values
        .keys()
        .any(|k| !allowed.contains(&k.as_str()) && !extra.contains(&k.as_str()))
    {
        return Err(invalid("unknown source scenario field"));
    }
    Ok(())
}
pub fn raw(value: &impl Serialize) -> Result<Box<RawValue>> {
    Ok(serde_json::value::to_raw_value(value)?)
}
pub fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
pub fn tagged(value: f64) -> Value {
    if value.is_finite() {
        json!(value)
    } else {
        json!({"$float":if value.is_nan(){"nan"}else if value.is_sign_positive(){"inf"}else{"-inf"}})
    }
}
pub fn finish(result: Result<Box<RawValue>>, extra: Observation) -> Observation {
    let mut out = extra;
    match result {
        Ok(value) => {
            out.insert("result".into(), value);
        }
        Err(e) => {
            let kind = match &e {
                RetrievalError::Numeric(e) => e.kind(),
                RetrievalError::MissingField(_) => "KeyError",
                _ => "ValueError",
            };
            out.insert(
                "error".into(),
                raw(&json!({"type":kind,"message":e.to_string()})).expect("scalar failure"),
            );
        }
    }
    out
}
pub fn finish_source(
    result: ken_retrieval::source_snapshot::SourceResult<Box<RawValue>>,
    extra: Observation,
) -> Observation {
    let mut out = extra;
    match result {
        Ok(value) => {
            out.insert("result".into(), value);
        }
        Err(e) => {
            out.insert(
                "error".into(),
                raw(&json!({"type":e.kind(),"message":e.to_string()})).expect("source failure"),
            );
        }
    }
    out
}
fn allowed(family: &str, kind: &str) -> bool {
    match family {
        "catalog" => matches!(kind, "catalog" | "catalog_admission"),
        "assembly" => matches!(
            kind,
            "assemble" | "piece_constructor" | "assembly_admission"
        ),
        "ranking" | "ranking-edges" | "ranking-empty-declaration" => {
            matches!(kind, "piece_features" | "piece_rank")
        }
        "cards" => kind == "cards",
        "evidence" | "evidence-edges" => kind == "source-evidence",
        "presentation" => kind == "presentation",
        _ => false,
    }
}
fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let mut bytes = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err("input exceeds8MiB".into());
    }
    let text = ken_retrieval::json_transport::python_strings(std::str::from_utf8(&bytes)?)?;
    let request: Request = serde_json::from_str(&text)?;
    let mut ids = HashSet::new();
    if request.format != FORMAT
        || request.cases.is_empty()
        || request.cases.len() > 1024
        || request.cases.iter().any(|c| {
            c.id.is_empty()
                || c.id.len() > 256
                || !ids.insert(&c.id)
                || !allowed(&c.family, &c.kind)
        })
    {
        return Err("invalid bounded source-piece request".into());
    }
    for path in [&request.resources.ranking, &request.resources.static_table]
        .into_iter()
        .flatten()
    {
        if path.as_os_str().is_empty()
            || path
                .components()
                .any(|p| !matches!(p, Component::Normal(_)))
        {
            return Err("resource path must stay within owned runtime".into());
        }
    }
    let runtime = production::Runtime::new(&request.resources);
    let cases = request
        .cases
        .iter()
        .map(|case| {
            let mut out = match case.family.as_str() {
                "catalog" => catalog::run(case.input.get()),
                "assembly" => assembly::run(case.input.get()),
                "cards" => cards::run(case.input.get()),
                "evidence" | "evidence-edges" => evidence::run(case.input.get()),
                "presentation" => presentation::run(case.input.get()),
                _ => ranking::run(case.input.get(), &case.kind, &runtime),
            };
            out.insert("id".into(), raw(&case.id).expect("case id"));
            out.insert("family".into(), raw(&case.family).expect("case family"));
            out.insert("kind".into(), raw(&case.kind).expect("case kind"));
            out
        })
        .collect::<Vec<_>>();
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: successful getrusage initializes the complete supplied structure.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    let rss = usage.ru_maxrss as u64 * if cfg!(target_os = "macos") { 1 } else { 1024 };
    #[derive(Serialize)]
    struct Output<'a> {
        format: &'static str,
        platform: &'static str,
        machine: &'static str,
        cases: &'a [Observation],
        metrics: Value,
    }
    let platform = if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    };
    let machine = if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else if cfg!(target_os = "macos") {
        "arm64"
    } else {
        "aarch64"
    };
    let output = serde_json::to_vec(&Output {
        format: FORMAT,
        platform,
        machine,
        cases: &cases,
        metrics: json!({"elapsed_s":started.elapsed().as_secs_f64(),"max_rss_bytes":rss,"scope":SCOPE}),
    })?;
    if output.len() > 16 * 1024 * 1024 {
        return Err("output exceeds16MiB".into());
    }
    io::stdout().write_all(&output)?;
    Ok(())
}
