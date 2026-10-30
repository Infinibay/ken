//! Retrieve, inspect, re-embed current docs, assess, then quote. Preview has no
//! path back into candidate scores or ordering.
use crate::{
    CurrentSources, Reasoner, ResponsibilityVectors, Result, WhoReport, WhoRequest, assessment,
    invalid, retrieval, text,
};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use rusqlite::Connection;
use serde_json::json;
use std::path::Path;
pub fn who_with(
    conn: &Connection,
    root: &Path,
    request: &WhoRequest,
    vectors: &mut dyn ResponsibilityVectors,
    sources: &mut dyn CurrentSources,
    reasoners: &[Box<dyn Reasoner>],
) -> Result<WhoReport> {
    let trim = |text: &str| text.trim_matches(ken_text::unicode::whitespace).to_owned();
    if trim(&request.question).is_empty() || request.question.chars().count() > 2000 {
        return Err(invalid("question must be 1..2000 characters"));
    }
    if !(1..=10).contains(&request.limit) {
        return Err(invalid("limit must be 1..10"));
    }
    if request.hypotheses.len() > 3
        || request
            .hypotheses
            .iter()
            .any(|s| trim(s).is_empty() || s.chars().count() > 500)
    {
        return Err(invalid(
            "hypotheses must contain at most 3 non-empty formulations of at most 500 characters",
        ));
    }
    let context = DiscoveryContext::from_process()?;
    let paths = ProjectPaths::at(root, &context)?;
    let scope = paths.resolve_inside(Path::new(&request.path), &context)?;
    let relative = scope
        .strip_prefix(paths.root())
        .map_err(|_| invalid("path must be within the project"))?
        .to_string_lossy();
    let scope_label = if relative.is_empty() { "." } else { &relative };
    let mut formulations = vec![trim(&request.question)];
    for hypothesis in &request.hypotheses {
        let value = trim(hypothesis);
        if !formulations.contains(&value) {
            formulations.push(value);
        }
    }
    let mut queries = Vec::new();
    for q in &formulations {
        queries.push(vectors.embed_query(q)?);
    }
    let (rows, indexed) = retrieval::retrieve(
        conn,
        paths.root(),
        &scope,
        &formulations,
        &queries,
        request.include_tests,
        vectors,
    )?;
    sources.begin_request()?;
    let mut live = Vec::new();
    let mut issues = Vec::new();
    for row in rows {
        match sources.resolve(&row){Ok(symbol)=>live.push(symbol),Err(error)=>issues.push(json!({"path":row.path,"qualname":row.qualname,"reason":error.to_string().chars().take(180).collect::<String>()}))}
    }
    let passages=live.iter().map(|symbol|{
  let docs=text::prefix(&symbol.documentation,12000).to_utf8().ok_or_else(||invalid("documentation contains non-scalar Unicode unsupported by the configured embedder"))?;
  let collapsed=docs.split(ken_text::unicode::whitespace).filter(|s|!s.is_empty()).collect::<Vec<_>>().join(" ");
  Ok(format!("{} — {collapsed}",if symbol.kind=="module"{"module_docstring"}else{"symbol_docstring"}))
 }).collect::<Result<Vec<_>>>()?;
    let matrix = if live.is_empty() {
        vec![]
    } else {
        vectors.embed_passages(&passages)?
    };
    if matrix.len() != live.len() {
        return Err(invalid(
            "current documentation embedding count does not align",
        ));
    }
    let width = matrix
        .first()
        .map_or_else(|| queries.first().map_or(0, Vec::len), Vec::len);
    if matrix.iter().any(|r| r.len() != width) {
        return Err(invalid(
            "current documentation embeddings are not rectangular",
        ));
    }
    let flat = matrix.into_iter().flatten().collect::<Vec<_>>();
    let mut scores = Vec::new();
    for query in &queries {
        let values = vectors.cosine(query, &flat, live.len(), width)?;
        if values.len() != live.len() {
            return Err(invalid("current documentation score count does not align"));
        }
        scores.push(values);
    }
    let mut candidates = Vec::new();
    for (i, symbol) in live.iter().enumerate() {
        candidates.push(assessment::assess_symbol(
            symbol,
            &formulations,
            // NumPy scores remain f32 through the numerical provider. Python's
            // float(similarities[j]) widens them only at the policy boundary.
            &scores.iter().map(|s| f64::from(s[i])).collect::<Vec<_>>(),
            reasoners,
        )?);
    }
    let mut result = assessment::present(
        request,
        candidates,
        scope_label,
        indexed,
        live.len(),
        issues,
        formulations.into_iter().skip(1).collect(),
    );
    for candidate in result
        .candidates
        .iter_mut()
        .chain(&mut result.counterevidence)
    {
        match sources.preview(candidate) {
            Ok(preview) => candidate.preview(preview),
            Err(error) => candidate.preview_unavailable = Some(error.to_string()),
        }
    }
    Ok(result)
}
