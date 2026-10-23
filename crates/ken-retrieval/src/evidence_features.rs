//! Canonical owners own their complete source feature projection and schema.
use crate::{
    EntityKey, Result, RetrievalError,
    coverage::{STAT_NAMES, TermDocument, coverage},
    description::OwnerDescription,
    feature_matrix::{FeatureMatrix, pool_stats},
    intent::interpret,
    matrix::Matrix,
    model::evidence_matches,
    query::{Candidate, SearchRequest},
    stemming::WordStemmer,
    text_patterns as p,
    vocabulary::{code_terms_python, code_tokens, code_tokens_python},
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use std::collections::{BTreeMap, BTreeSet};
pub const FEATURE_VERSION: usize = 1;
pub const BASE_FEATURES: [&str; 15] = [
    "rrf",
    "cosine_identity",
    "cosine_behavior",
    "bm25f",
    "bm25_body",
    "bm25_documentation",
    "bm25_identity",
    "bm25_signature",
    "bm25_path",
    "role_match",
    "class",
    "module",
    "log_lines",
    "name_overlap",
    "body_overlap",
];
const RAW: [&str; 6] = [
    "identity",
    "signature",
    "documentation",
    "body",
    "path",
    "all",
];
const SOURCE: [&str; 10] = [
    "identity",
    "signature",
    "documentation",
    "implementation",
    "executable",
    "comments",
    "calls",
    "returns",
    "path",
    "all",
];
const KINDS: [&str; 13] = [
    "function",
    "method",
    "class",
    "struct",
    "interface",
    "enum",
    "trait",
    "type",
    "module",
    "constant",
    "property",
    "variable",
    "constructor",
];
const OPERATIONS: [&str; 15] = [
    "return", "raise", "throw", "panic", "if", "else", "try", "catch", "except", "for", "while",
    "match", "switch", "await", "yield",
];
const SHAPE: [&str; 7] = [
    "log_executable_lines",
    "log_comment_lines",
    "log_owned_lines",
    "log_regions",
    "documentation_fraction",
    "query_negation",
    "query_test",
];
pub fn feature_names() -> Vec<PythonText> {
    let mut names: Vec<String> = BASE_FEATURES.iter().map(|s| s.to_string()).collect();
    names.extend(
        [
            "is_exception",
            "is_constructor",
            "query_log_tokens",
            "query_identifier",
            "query_kind_class",
        ]
        .map(str::to_string),
    );
    for field in RAW {
        for stat in STAT_NAMES {
            names.push(format!("{field}_{stat}"));
        }
    }
    for name in &BASE_FEATURES[..9] {
        for stat in ["relative", "rank"] {
            names.push(format!("{name}_{stat}"));
        }
    }
    for field in SOURCE {
        for stat in ["exact", "stem"]
            .into_iter()
            .chain(STAT_NAMES[1..].iter().copied())
        {
            names.push(format!("expanded_{field}_{stat}"));
        }
    }
    names.extend(KINDS.map(|k| format!("expanded_kind_{k}")));
    names.extend(SHAPE.map(|k| format!("expanded_{k}")));
    names.extend(OPERATIONS.map(|k| format!("expanded_op_{k}")));
    names.into_iter().map(PythonText::from).collect()
}
fn tokens(text: &PythonText) -> BTreeSet<String> {
    code_tokens_python(text).into_iter().collect()
}
fn overlap(query: &BTreeSet<String>, terms: &BTreeSet<String>) -> f64 {
    query.intersection(terms).count() as f64 / query.len().max(1) as f64
}
pub fn base_features(
    request: &SearchRequest,
    candidate: &Candidate,
) -> Result<BTreeMap<String, f64>> {
    let Some(first) = candidate.passages.first() else {
        return Err(stale());
    };
    if !evidence_matches(&candidate.entity, &first.source_hash, &candidate.passages) {
        return Err(stale());
    }
    let mut row: BTreeMap<String, f64> = BASE_FEATURES[..9]
        .iter()
        .map(|name| ((*name).into(), *candidate.signals.get(*name).unwrap_or(&0.)))
        .collect();
    for name in &BASE_FEATURES[3..9] {
        row.insert((*name).into(), row[*name].max(0.).ln_1p());
    }
    let intent = interpret(request);
    let role = match intent.purpose.as_str() {
        "tests" => "test",
        "usage" => "example",
        "documentation" => "documentation",
        _ => "definition",
    };
    let query = tokens(request.query());
    let lines = candidate
        .passages
        .iter()
        .map(|p| p.entity_span.end_line - p.entity_span.start_line + 1)
        .max()
        .unwrap();
    row.extend([
        ("role_match".into(), f64::from(first.role == role)),
        ("class".into(), f64::from(candidate.entity.kind == "class")),
        (
            "module".into(),
            f64::from(candidate.entity.qualname.is_none()),
        ),
        ("log_lines".into(), (lines as f64).ln_1p()),
        (
            "name_overlap".into(),
            overlap(
                &query,
                &code_tokens(candidate.entity.qualname.as_deref().unwrap_or(""))
                    .into_iter()
                    .collect(),
            ),
        ),
        (
            "body_overlap".into(),
            candidate
                .passages
                .iter()
                .map(|p| overlap(&query, &tokens(&p.fields.body)))
                .fold(0., f64::max),
        ),
    ]);
    Ok(row)
}
fn stale() -> RetrievalError {
    RetrievalError::Version("ranking description source is stale".into())
}
fn field<'a>(owner: &'a OwnerDescription, name: &str) -> Result<&'a PythonText> {
    owner
        .fields
        .get(name)
        .ok_or_else(|| RetrievalError::Invalid(format!("ranking owner field missing: {name}")))
}
pub fn evidence_features(
    request: &SearchRequest,
    candidates: &[Candidate],
    descriptions: &BTreeMap<EntityKey, OwnerDescription>,
    encoder: &dyn WordEncoder,
    stemmer: &dyn WordStemmer,
    expanded: Option<&PythonText>,
) -> Result<FeatureMatrix> {
    let names = feature_names();
    if candidates.is_empty() {
        return Ok(FeatureMatrix {
            values: Matrix::new(0, names.len(), vec![])?,
            names,
        });
    }
    let owners: Vec<_> = candidates
        .iter()
        .map(|c| descriptions.get(&c.entity).ok_or_else(stale))
        .collect::<Result<_>>()?;
    if candidates.iter().zip(&owners).any(|(c, d)| {
        d.entity != c.entity
            || !evidence_matches(&c.entity, &d.source_hash, &c.passages)
            || !evidence_matches(&c.entity, &d.source_hash, &d.passages)
    }) {
        return Err(stale());
    }
    let mut raw_docs = Vec::new();
    let mut source_docs = Vec::new();
    for owner in &owners {
        let mut raw = TermDocument::new();
        for f in &RAW[..5] {
            raw.insert((*f).into(), code_terms_python(field(owner, f)?, Some(4096)));
        }
        let mut seen = BTreeSet::new();
        let mut all = Vec::new();
        for f in &RAW[..5] {
            for word in &raw[*f] {
                if seen.insert(word.clone()) {
                    all.push(word.clone());
                }
            }
        }
        raw.insert("all".into(), all);
        let mut joined = Vec::new();
        for (index, f) in [
            "identity",
            "signature",
            "documentation",
            "path",
            "implementation",
            "comments",
            "executable",
            "calls",
            "returns",
        ]
        .into_iter()
        .enumerate()
        {
            if index > 0 {
                joined.push(10);
            }
            joined.extend_from_slice(field(owner, f)?.codepoints());
        }
        let all = PythonText::from_codepoints(joined).expect("owner source points");
        let mut source = TermDocument::new();
        for f in SOURCE {
            let words = if ["identity", "signature", "documentation", "path"].contains(&f) {
                raw[f].clone()
            } else if f == "all" {
                code_terms_python(&all, Some(4096))
            } else {
                code_terms_python(field(owner, f)?, Some(4096))
            };
            source.insert(f.into(), words);
        }
        raw_docs.push(raw);
        source_docs.push(source);
    }
    let raw_coverage = coverage(request.query(), &raw_docs, &RAW, encoder, None)?;
    let expanded = expanded.unwrap_or(request.query());
    let source_coverage = coverage(expanded, &source_docs, &SOURCE, encoder, Some(stemmer))?;
    let intent = interpret(request);
    let expanded_intent = interpret(&request.with_query(expanded.clone())?);
    let query_count = tokens(request.query()).len();
    let mut rows = Vec::new();
    for (((candidate, owner), raw_stats), source_stats) in candidates
        .iter()
        .zip(owners)
        .zip(raw_coverage)
        .zip(source_coverage)
    {
        let mut row = base_features(request, candidate)?;
        let name = candidate
            .entity
            .qualname
            .as_deref()
            .unwrap_or("")
            .to_lowercase();
        let name = name.rsplit('.').next().unwrap();
        row.extend([
            (
                "is_exception".into(),
                f64::from(name.contains("exception") || name.contains("error")),
            ),
            (
                "is_constructor".into(),
                f64::from(["__init__", "new", "constructor"].contains(&name)),
            ),
            ("query_log_tokens".into(), (query_count as f64).ln_1p()),
            ("query_identifier".into(), f64::from(intent.identity)),
            (
                "query_kind_class".into(),
                f64::from(intent.kind.as_deref() == Some("class")),
            ),
        ]);
        row.extend(raw_stats);
        row.extend(
            source_stats
                .into_iter()
                .map(|(k, v)| (format!("expanded_{k}"), v)),
        );
        row.extend(KINDS.map(|k| {
            (
                format!("expanded_kind_{k}"),
                f64::from(candidate.entity.kind == k),
            )
        }));
        row.extend([
            (
                "expanded_log_executable_lines".into(),
                (owner.executable_lines as f64).ln_1p(),
            ),
            (
                "expanded_log_comment_lines".into(),
                (owner.comment_lines as f64).ln_1p(),
            ),
            (
                "expanded_log_owned_lines".into(),
                (owner.owned_lines as f64).ln_1p(),
            ),
            (
                "expanded_log_regions".into(),
                (owner.regions as f64).ln_1p(),
            ),
            (
                "expanded_documentation_fraction".into(),
                1. - owner.implementation_lines as f64 / owner.owned_lines.max(1) as f64,
            ),
            (
                "expanded_query_negation".into(),
                f64::from(p::has(
                    r"\b(?:not|without|never|no|sin)\b",
                    false,
                    &p::fold(expanded),
                )),
            ),
            (
                "expanded_query_test".into(),
                f64::from(expanded_intent.purpose == "tests"),
            ),
        ]);
        let mut operations: BTreeMap<String, usize> = BTreeMap::new();
        for m in p::captures(r"\b\w+\b", false, field(owner, "executable")?) {
            let key = m.whole.to_utf8().expect("matched scalar source token");
            *operations.entry(key).or_default() += 1;
        }
        row.extend(OPERATIONS.map(|op| {
            (
                format!("expanded_op_{op}"),
                (*operations.get(op).unwrap_or(&0) as f64).ln_1p(),
            )
        }));
        rows.push(row);
    }
    for name in &BASE_FEATURES[..9] {
        let values: Vec<_> = rows.iter().map(|r| r[*name]).collect();
        let stats = pool_stats(&values);
        for (i, row) in rows.iter_mut().enumerate() {
            row.insert(format!("{name}_relative"), stats.relative[i]);
            row.insert(format!("{name}_rank"), stats.reciprocal_rank[i]);
        }
    }
    let mut values = Vec::new();
    for row in &rows {
        for name in &names {
            let key = name.to_utf8().expect("named numeric source feature");
            values.push(*row.get(&key).ok_or_else(|| {
                RetrievalError::Invalid(format!("ranking feature missing: {key}"))
            })?);
        }
    }
    if values.iter().any(|v| !v.is_finite()) {
        return Err(RetrievalError::Invalid(
            "ranking features must be finite".into(),
        ));
    }
    Ok(FeatureMatrix {
        values: Matrix::new(rows.len(), names.len(), values)?,
        names,
    })
}
