//! Input-only native caller for the complete numerical owner-ranking boundary.
#[path = "numeric_owner/alignment.rs"]
mod alignment;
#[path = "numeric_owner/features.rs"]
mod features;
#[path = "numeric_owner/forest.rs"]
mod forest;
#[path = "numeric_owner/owners.rs"]
mod owners;
#[path = "numeric_owner/production.rs"]
mod production;
#[path = "numeric_owner/stems.rs"]
mod stems;
use ken_retrieval::{Result, RetrievalError};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::{BTreeMap, HashSet},
    io::{self, Read, Write},
    path::PathBuf,
    time::Instant,
};
const FORMAT: &str = "ken-numeric-owner-probe/1";
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
pub fn raw(value: &impl Serialize) -> Result<Box<RawValue>> {
    Ok(serde_json::value::to_raw_value(value)?)
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
pub fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
pub fn number(value: &Value) -> Result<f64> {
    value
        .as_f64()
        .or_else(|| {
            if value.as_object().is_some_and(|o| o.len() == 1) {
                match value["$float"].as_str()? {
                    "nan" => Some(f64::NAN),
                    "inf" => Some(f64::INFINITY),
                    "-inf" => Some(f64::NEG_INFINITY),
                    _ => None,
                }
            } else {
                None
            }
        })
        .ok_or_else(|| invalid("number or explicit IEEE category required"))
}
pub fn tagged(value: f64) -> Value {
    if value.is_finite() {
        json!(value)
    } else {
        json!({"$float":if value.is_nan(){"nan"}else if value.is_sign_positive(){"inf"}else{"-inf"}})
    }
}
fn allowed(family: &str, kind: &str) -> bool {
    match family {
        "forest" | "forest-edges" => matches!(kind, "model" | "dict" | "predict" | "explain"),
        "stems" => matches!(
            kind,
            "stem" | "stem_concurrent" | "stem_reuse" | "stem_capacity" | "stem_providers"
        ),
        "alignment" | "alignment-edges" => {
            matches!(kind, "similarities" | "coverage" | "summarize" | "maxima")
        }
        "features" | "features-edges" | "features-math-edges" => matches!(
            kind,
            "coverage" | "base" | "evidence" | "evidence_admission" | "feature_context"
        ),
        "owner-ranking" => matches!(
            kind,
            "rank"
                | "rank_trace"
                | "prepare"
                | "validate"
                | "trace_ids"
                | "trace_record"
                | "trace_restore"
                | "trace_empty"
        ),
        "production" => matches!(
            kind,
            "production_identity" | "production_predict" | "production_compose"
        ),
        "production-paths" => kind == "production_paths",
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
        return Err("invalid bounded numeric request".into());
    }
    for path in [&request.resources.ranking, &request.resources.static_table]
        .into_iter()
        .flatten()
    {
        if path.as_os_str().is_empty()
            || path
                .components()
                .any(|p| !matches!(p, std::path::Component::Normal(_)))
        {
            return Err("resource path must stay within owned runtime".into());
        }
    }
    let production = production::Runtime::new(&request.resources);
    let cases = request
        .cases
        .iter()
        .map(|c| {
            let mut out = match c.family.as_str() {
                "forest" | "forest-edges" => forest::run(c.input.get(), &c.kind),
                "stems" => stems::run(c.input.get(), &c.kind),
                "alignment" | "alignment-edges" => alignment::run(c.input.get(), &c.kind),
                "features" | "features-edges" | "features-math-edges" => {
                    features::run(c.input.get(), &c.kind)
                }
                "owner-ranking" => owners::run(c.input.get(), &c.kind),
                _ => production.run(c.input.get(), &c.kind),
            };
            out.insert("id".into(), raw(&c.id).expect("case identity"));
            out.insert("kind".into(), raw(&c.kind).expect("case kind"));
            out.insert("family".into(), raw(&c.family).expect("case family"));
            out
        })
        .collect::<Vec<_>>();
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage initializes rusage on success; the return code is checked.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: successful getrusage initialized the complete structure above.
    let usage = unsafe { usage.assume_init() };
    let rss = usage.ru_maxrss as u64 * if cfg!(target_os = "macos") { 1 } else { 1024 };
    let output = json_output(
        &cases,
        json!({"elapsed_s":started.elapsed().as_secs_f64(),"max_rss_bytes":rss,"scope":"native input parsing, bounded numerical/feature/ranking operations and registered resource loading, before output serialization"}),
    )?;
    if output.len() > 16 * 1024 * 1024 {
        return Err("output exceeds16MiB".into());
    }
    io::stdout().write_all(&output)?;
    Ok(())
}
fn json_output(cases: &[Observation], metrics: Value) -> Result<Vec<u8>> {
    #[derive(Serialize)]
    struct Output<'a> {
        format: &'static str,
        platform: &'static str,
        cases: &'a [Observation],
        metrics: Value,
    }
    Ok(serde_json::to_vec(&Output {
        format: FORMAT,
        platform: if cfg!(target_os = "macos") {
            "macos"
        } else {
            "linux"
        },
        cases,
        metrics,
    })?)
}
