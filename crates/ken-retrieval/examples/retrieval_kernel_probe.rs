//! Bounded input-only process for the actual native retrieval kernels.
use ken_retrieval::{
    EntityKey, Passage, PassageFields, Result, RetrievalError, Span,
    dense::DenseView,
    embedding_store::VectorView,
    lexical::{Posting, bm25f_score, score_postings},
    proposals::fuse_proposals,
    query::{Candidate, SearchRequest, Signals, merge_spans},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::{BTreeMap, HashSet},
    io::{self, Read, Write},
    time::Instant,
};
const FORMAT: &str = "ken-retrieval-kernel-probe/1";
#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Kind {
    Request,
    Spans,
    Bm25f,
    Postings,
    Dense,
    Fusion,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    format: String,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    kind: Kind,
    input: Box<RawValue>,
}
#[derive(Serialize)]
struct Observation {
    id: String,
    kind: Kind,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Box<RawValue>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scalar {
    frequencies: BTreeMap<String, f64>,
    lengths: BTreeMap<String, f64>,
    averages: BTreeMap<String, f64>,
    document_frequency: i64,
    documents: i64,
    #[serde(default = "k1")]
    k1: f64,
    weights: Option<BTreeMap<String, f64>>,
}
fn k1() -> f64 {
    1.2
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Postings {
    rows: Vec<(i64, String, String, f64, f64)>,
    documents: i64,
    averages: BTreeMap<String, f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Dense {
    passages: Vec<(i64, Passage)>,
    ids: Vec<i64>,
    matrix: Vec<Vec<f32>>,
    query: Vec<Value>,
    view: String,
    limit: isize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Fusion {
    channels: Vec<(String, Vec<Candidate>)>,
    limit: usize,
    rrf_k: usize,
}
fn raw(value: &impl Serialize) -> Result<Box<RawValue>> {
    Ok(RawValue::from_string(serde_json::to_string(value)?)?)
}
fn number(n: f64) -> Value {
    if n.is_finite() {
        json!(n)
    } else {
        json!({"float":if n.is_nan(){"nan"}else if n.is_sign_positive(){"inf"}else{"-inf"}})
    }
}
fn signals(values: &Signals) -> BTreeMap<&str, Value> {
    values
        .iter()
        .map(|(k, &v)| (k.as_str(), number(v)))
        .collect()
}
#[derive(Serialize)]
struct WirePassage<'a> {
    entity: &'a EntityKey,
    span: Span,
    fields: &'a PassageFields,
    source_hash: &'a str,
    entity_span: Span,
    language: &'a str,
    role: &'a str,
    split_reason: Option<&'a str>,
    signals: BTreeMap<&'a str, Value>,
    implementation_start_line: Option<usize>,
}
#[derive(Serialize)]
struct WireCandidate<'a> {
    entity: &'a EntityKey,
    passages: Vec<WirePassage<'a>>,
    signals: BTreeMap<&'a str, Value>,
    owned_regions: &'a [Span],
}
fn candidates(values: &[Candidate]) -> Result<Box<RawValue>> {
    raw(&values
        .iter()
        .map(|c| WireCandidate {
            entity: &c.entity,
            passages: c
                .passages
                .iter()
                .map(|p| WirePassage {
                    entity: &p.entity,
                    span: p.span,
                    fields: &p.fields,
                    source_hash: &p.source_hash,
                    entity_span: p.entity_span,
                    language: &p.language,
                    role: &p.role,
                    split_reason: p.split_reason.as_deref(),
                    signals: signals(&p.signals),
                    implementation_start_line: p.implementation_start_line,
                })
                .collect(),
            signals: signals(&c.signals),
            owned_regions: &c.owned_regions,
        })
        .collect::<Vec<_>>())
}
fn execute(case: &Case) -> Result<Box<RawValue>> {
    match case.kind {
        Kind::Request => raw(&serde_json::from_str::<SearchRequest>(case.input.get())?),
        Kind::Spans => {
            let input: Vec<[usize; 2]> = serde_json::from_str(case.input.get())?;
            let spans = input
                .into_iter()
                .map(|p| Span::new(p[0], p[1]))
                .collect::<Result<Vec<_>>>()?;
            raw(&merge_spans(&spans))
        }
        Kind::Bm25f => {
            let i: Scalar = serde_json::from_str(case.input.get())?;
            raw(&number(bm25f_score(
                &i.frequencies,
                &i.lengths,
                &i.averages,
                i.document_frequency,
                i.documents,
                i.k1,
                i.weights.as_ref(),
            )?))
        }
        Kind::Postings => {
            let i: Postings = serde_json::from_str(case.input.get())?;
            let rows: Vec<_> = i.rows.into_iter().map(Posting::from).collect();
            let scores = score_postings(&rows, i.documents, &i.averages)?;
            raw(&scores
                .iter()
                .map(|(&id, v)| (id, signals(v)))
                .collect::<BTreeMap<_, _>>())
        }
        Kind::Dense => {
            let i: Dense = serde_json::from_str(case.input.get())?;
            let query = i
                .query
                .iter()
                .map(|v| match v.as_str() {
                    Some("nan") => Ok(f32::NAN),
                    Some("inf") => Ok(f32::INFINITY),
                    _ => v.as_f64().map(|v| v as f32).ok_or_else(|| {
                        RetrievalError::Invalid("numeric query value required".into())
                    }),
                })
                .collect::<Result<Vec<_>>>()?;
            let view = DenseView::new(
                i.passages,
                VectorView {
                    ids: i.ids,
                    matrix: i.matrix,
                    model_revision: "provided-input-matrix".into(),
                },
            )?;
            candidates(&view.search(&query, &i.view, i.limit)?)
        }
        Kind::Fusion => {
            let i: Fusion = serde_json::from_str(case.input.get())?;
            let before = i.channels.clone();
            let merged = fuse_proposals(&i.channels, i.limit, i.rrf_k)?;
            if before != i.channels {
                return Err(RetrievalError::Invalid("proposal inputs changed".into()));
            }
            candidates(&merged)
        }
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
    let request: Request = serde_json::from_slice(&input)?;
    let mut ids = HashSet::new();
    if request.format != FORMAT
        || request.cases.is_empty()
        || request.cases.len() > 512
        || request
            .cases
            .iter()
            .any(|c| c.id.is_empty() || c.id.len() > 256 || !ids.insert(c.id.as_str()))
    {
        return Err("invalid bounded kernel request".into());
    }
    let cases: Vec<_> = request
        .cases
        .iter()
        .map(|case| {
            let (result, error) = match execute(case) {
                Ok(v) => (Some(v), None),
                Err(error) => {
                    let kind = if matches!(error, RetrievalError::Version(_)) {
                        "index_version"
                    } else {
                        "invalid"
                    };
                    (None, Some(json!({"kind":kind,"message":error.to_string()})))
                }
            };
            Observation {
                id: case.id.clone(),
                kind: case.kind,
                result,
                error,
            }
        })
        .collect();
    let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
    // getrusage initializes the supplied native structure on success.
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error().into());
    }
    let usage = unsafe { usage.assume_init() };
    let max_rss_bytes = usage.ru_maxrss as u64 * if cfg!(target_os = "macos") { 1 } else { 1024 };
    #[derive(Serialize)]
    struct Output<'a> {
        format: &'a str,
        platform: &'a str,
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
        metrics: json!({"elapsed_s":started.elapsed().as_secs_f64(),"max_rss_bytes":max_rss_bytes,"scope":"native request parsing and all kernels, before output serialization"}),
    };
    let bytes = serde_json::to_vec(&output)?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("output exceeds16MiB".into());
    }
    io::stdout().write_all(&bytes)?;
    Ok(())
}
