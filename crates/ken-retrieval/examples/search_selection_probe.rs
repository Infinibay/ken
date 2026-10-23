//! Complete input-only selection caller, independent of the checkout and Python runtime.
#[path = "search_selection/context.rs"]
mod context;
#[path = "search_selection/rank.rs"]
mod rank;
#[path = "search_selection/sql.rs"]
mod sql;
#[path = "search_selection/text.rs"]
mod text;
use ken_retrieval::{Result, RetrievalError};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json, value::RawValue};
use std::{
    cell::RefCell,
    collections::HashSet,
    io::{self, Read, Write},
    rc::Rc,
    time::Instant,
};
const FORMAT: &str = "ken-search-selection-probe/1";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    legacy_runtime: Value,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    kind: String,
    input: Box<RawValue>,
}
#[derive(Serialize)]
struct Observation {
    id: String,
    kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Box<RawValue>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    query_calls: Option<Vec<Box<RawValue>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    judge_calls: Option<Vec<Box<RawValue>>>,
}
#[derive(Clone, Default)]
struct Calls(Rc<RefCell<Vec<Box<RawValue>>>>);
impl Calls {
    fn push(&self, value: &impl Serialize) -> Result<()> {
        self.0.borrow_mut().push(raw(value)?);
        Ok(())
    }
    fn values(&self) -> Vec<Box<RawValue>> {
        self.0.borrow().clone()
    }
}
fn raw(value: &impl Serialize) -> Result<Box<RawValue>> {
    Ok(RawValue::from_string(serde_json::to_string(value)?)?)
}

fn execute(case: &Case, legacy: &Value, calls: &Calls) -> Result<Box<RawValue>> {
    match case.kind.as_str() {
        "intent" | "locator" | "module" | "identifier" | "description" => {
            text::run(case.input.get(), &case.kind)
        }
        "context" | "source_views" | "view_texts" => {
            context::run(case.input.get(), &case.kind, calls)
        }
        "selection" | "context_selection" => sql::run(case.input.get(), &case.kind, legacy, calls),
        "document" | "rank" => rank::run(case.input.get(), &case.kind, calls),
        _ => unreachable!("validated operation"),
    }
}
fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let mut input = Vec::new();
    io::stdin()
        .take(8 * 1024 * 1024 + 1)
        .read_to_end(&mut input)?;
    if input.len() > 8 * 1024 * 1024 {
        return Err("input exceeds8MiB".into());
    }
    let normalized = ken_retrieval::json_transport::python_strings(std::str::from_utf8(&input)?)?;
    let request: Request = serde_json::from_str(&normalized)?;
    let mut ids = HashSet::new();
    let kinds = [
        "intent",
        "locator",
        "module",
        "identifier",
        "description",
        "context",
        "source_views",
        "view_texts",
        "selection",
        "context_selection",
        "document",
        "rank",
    ];
    if request.format != FORMAT
        || request.cases.is_empty()
        || request.cases.len() > 1024
        || request.cases.iter().any(|c| {
            c.id.is_empty()
                || c.id.len() > 256
                || !ids.insert(&c.id)
                || !kinds.contains(&c.kind.as_str())
        })
    {
        return Err("invalid bounded selection request".into());
    }
    let cases = request
        .cases
        .iter()
        .map(|case| {
            let calls = Calls::default();
            let outcome = execute(case, &request.legacy_runtime, &calls);
            let failed = outcome.is_err();
            let (result, error) = match outcome {
                Ok(v) => (Some(v), None),
                Err(e) => {
                    let kind = if matches!(e, RetrievalError::Version(_)) {
                        "index_version"
                    } else {
                        "invalid"
                    };
                    (None, Some(json!({"kind":kind,"message":e.to_string()})))
                }
            };
            Observation {
                id: case.id.clone(),
                kind: case.kind.clone(),
                result,
                error,
                query_calls: if failed
                    && matches!(
                        case.kind.as_str(),
                        "selection" | "context_selection" | "context" | "source_views"
                    ) {
                    Some(calls.values())
                } else {
                    None
                },
                judge_calls: if failed && case.kind == "rank" {
                    Some(calls.values())
                } else {
                    None
                },
            }
        })
        .collect::<Vec<_>>();
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // SAFETY: getrusage initializes this structure on success, checked before use.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    let max_rss_bytes = usage.ru_maxrss as u64 * if cfg!(target_os = "macos") { 1 } else { 1024 };
    #[derive(Serialize)]
    struct Output {
        format: &'static str,
        platform: &'static str,
        cases: Vec<Observation>,
        metrics: Value,
    }
    let output = Output {
        format: FORMAT,
        platform: if cfg!(target_os = "macos") {
            "macos"
        } else {
            "linux"
        },
        cases,
        metrics: json!({"elapsed_s":started.elapsed().as_secs_f64(),"max_rss_bytes":max_rss_bytes,"scope":"native request parsing, SQL scenario preparation and complete selection/ranking, before output serialization"}),
    };
    let bytes = serde_json::to_vec(&output)?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("output exceeds16MiB".into());
    }
    io::stdout().write_all(&bytes)?;
    Ok(())
}
