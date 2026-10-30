//! Top-one identity and visible source evidence are separate observations.
use super::{dataset::bounds, hash, invalid, valid_path, validate_case};
use crate::Result;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
};
fn truth(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => v.as_f64() != Some(0.),
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
fn metric(hits: usize, total: usize) -> Value {
    json!({"hits":hits,"total":total,"rate":if total==0{0.}else{hits as f64/total as f64}})
}
pub fn request_for_case(case: &Value) -> Value {
    json!({"query":case["query"],"purpose":"auto","target":"symbol","limit":10,"max_chars":12000})
}
fn identity(result: &Value, alternative: &Value) -> bool {
    if result["path"] != alternative["path"] {
        return false;
    }
    let Some(expected) = alternative.get("entity").filter(|e| !e.is_null()) else {
        return true;
    };
    let actual = &result["entity"];
    actual.is_object()
        && ["kind", "qualname", "owner"]
            .iter()
            .all(|key| actual[*key] == expected[*key])
        && ordinal_equal(
            &actual["definition_ordinal"],
            &expected["definition_ordinal"],
        )
}
fn ordinal_equal(actual: &Value, expected: &Value) -> bool {
    if actual == expected {
        return true;
    }
    let canonical = expected
        .as_i64()
        .map(|n| n.to_string())
        .unwrap_or_else(|| expected.to_string());
    match actual {
        Value::Bool(value) => canonical == if *value { "1" } else { "0" },
        Value::Number(number) => {
            if let Some(integer) = number.as_i64() {
                return canonical == integer.to_string();
            }
            if !number.to_string().contains(['.', 'e', 'E']) {
                return false;
            }
            number
                .as_f64()
                .filter(|n| n.is_finite() && n.fract() == 0.)
                .is_some_and(|n| canonical == format!("{n:.0}"))
        }
        _ => false,
    }
}
fn read(root: &Path, path: &str, escape: &str) -> Result<Vec<u8>> {
    let base = root.canonicalize()?;
    let source = root.join(path).canonicalize()?;
    if !source.starts_with(base) {
        return Err(invalid(escape));
    }
    Ok(std::fs::read(source)?)
}
fn visible(result: &Value, root: &Path) -> Result<BTreeSet<usize>> {
    let path = result["path"]
        .as_str()
        .filter(|p| valid_path(p))
        .ok_or_else(|| invalid("invalid response path"))?;
    let source = read(root, path, "response escapes project root")?;
    if result["source_hash"] != hash(&source) {
        return Err(invalid("stale or missing response source hash"));
    }
    let source = std::str::from_utf8(&source).map_err(|e| invalid(e.to_string()))?;
    let lines = ken_text::unicode::splitlines(source);
    let evidence = result["evidence"]
        .as_array()
        .ok_or_else(|| invalid("missing evidence"))?;
    let mut visible = BTreeSet::new();
    let mut shown = 0usize;
    for fragment in evidence {
        let (start, end) = bounds(fragment)?;
        if end > lines.len() || truth(&fragment["stale"]) {
            return Err(invalid("evidence outside current source"));
        }
        if fragment["content"] != lines[start - 1..end].join("\n") {
            return Err(invalid("evidence content does not match its source span"));
        }
        shown = shown.saturating_add(end - start + 1);
        if shown > 40 {
            return Err(invalid("visible evidence exceeds line budget"));
        }
        visible.extend(start..=end);
    }
    Ok(visible)
}
fn score(case: &Value, response: Option<&Value>, root: &Path) -> (bool, bool, &'static str) {
    let Some(response) = response else {
        return (false, false, "missing_response");
    };
    if truth(&response["error"]) || response["ok"] == Value::Bool(false) {
        return (false, false, "error");
    }
    let mut payload = response.clone();
    payload
        .as_object_mut()
        .expect("validated response object")
        .remove("id");
    let size = serde_json::to_string(&payload)
        .map(|s| s.chars().count())
        .unwrap_or(usize::MAX);
    if size > 12000 {
        return (false, false, "output_budget");
    }
    let Some(results) = response["results"].as_array().filter(|r| !r.is_empty()) else {
        return (false, false, "empty");
    };
    if results.len() > 10 || !results[0].is_object() {
        return (false, false, "invalid_results");
    }
    let first = &results[0];
    let alternatives = case["alternatives"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|alt| identity(first, alt))
        .collect::<Vec<_>>();
    if alternatives.is_empty() {
        return (false, false, "wrong_identity");
    }
    let Ok(visible) = visible(first, root) else {
        return (true, false, "invalid_evidence");
    };
    for alternative in alternatives {
        if alternative["source_hash"] == first["source_hash"]
            && alternative["anchors"]
                .as_array()
                .unwrap()
                .iter()
                .all(|anchor| {
                    bounds(anchor)
                        .is_ok_and(|(start, end)| (start..=end).all(|line| visible.contains(&line)))
                })
        {
            return (true, true, "hit");
        }
    }
    (true, false, "missing_anchor")
}
pub fn evaluate(
    cases: &[Value],
    responses: &[Value],
    roots: &BTreeMap<String, PathBuf>,
) -> Result<Value> {
    let mut ids = BTreeSet::new();
    for case in cases {
        validate_case(case)?;
        if !ids.insert(case["id"].as_str().unwrap()) {
            return Err(invalid("duplicate case id"));
        }
    }
    let mut by_id = BTreeMap::new();
    for response in responses {
        if !response.is_object() {
            return Err(invalid("response must be an object"));
        }
        let id = response["id"]
            .as_str()
            .ok_or_else(|| invalid("response id must be a string"))?;
        if by_id.contains_key(id) {
            return Err(invalid(format!("duplicate response id: {id}")));
        }
        if !ids.contains(id) {
            return Err(invalid(format!("unknown response id: {id}")));
        }
        by_id.insert(id, response);
    }
    let mut rows = Vec::new();
    let mut negatives = Vec::new();
    let mut strata = BTreeMap::<String, Vec<Value>>::new();
    let mut repo_order = Vec::new();
    for case in cases {
        let id = case["id"].as_str().unwrap();
        let repo = case["repo_id"].as_str().unwrap();
        let root = roots
            .get(repo)
            .ok_or_else(|| invalid(format!("missing repository root: {repo}")))?;
        for alternative in case["alternatives"].as_array().unwrap() {
            let source = read(
                root,
                alternative["path"].as_str().unwrap(),
                "gold path escapes project",
            )?;
            if alternative["source_hash"] != hash(&source) {
                return Err(invalid(format!("reference snapshot mismatch: {id}")));
            }
            let source = std::str::from_utf8(&source).map_err(|e| invalid(e.to_string()))?;
            let lines = ken_text::unicode::splitlines(source).len();
            if alternative["anchors"]
                .as_array()
                .unwrap()
                .iter()
                .any(|anchor| bounds(anchor).map_or(true, |(_, end)| end > lines))
            {
                return Err(invalid(format!("reference span outside source: {id}")));
            }
        }
        let response = by_id.get(id).copied();
        if case["answerable"] == false {
            negatives.push(
                json!({"id":id,"returned_results":response.is_some_and(|r|truth(&r["results"]))}),
            );
            continue;
        }
        let (identity, hit, reason) = score(case, response, root);
        let row = json!({"id":id,"identity_hit":identity,"strict_hit":hit,"reason":reason});
        rows.push(row.clone());
        for group in [
            "all".into(),
            format!("repo:{repo}"),
            format!("language:{}", case["language"].as_str().unwrap()),
            format!("purpose:{}", case["purpose"].as_str().unwrap()),
        ] {
            if group.starts_with("repo:") && !strata.contains_key(&group) {
                repo_order.push(group.clone());
            }
            strata.entry(group).or_default().push(row.clone());
        }
    }
    let metrics = strata
        .into_iter()
        .map(|(key, rows)| {
            (
                key,
                metric(
                    rows.iter().filter(|r| r["strict_hit"] == true).count(),
                    rows.len(),
                ),
            )
        })
        .collect::<BTreeMap<_, _>>();
    let repos = repo_order
        .iter()
        .map(|key| metrics[key]["rate"].as_f64().unwrap())
        .collect::<Vec<_>>();
    let macro_repo = if repos.is_empty() {
        0.
    } else {
        ken_retrieval::vector_math::python_sum_f64(&repos) / repos.len() as f64
    };
    let missing = cases
        .iter()
        .filter_map(|case| {
            let id = case["id"].as_str().unwrap();
            (!by_id.contains_key(id)).then_some(id)
        })
        .collect::<Vec<_>>();
    Ok(
        json!({"schema_version":2,"strict_top1":metrics.get("all").cloned().unwrap_or_else(||metric(0,0)),"identity_top1":metric(rows.iter().filter(|r|r["identity_hit"]==true).count(),rows.len()),"macro_repo_top1":macro_repo,"strata":metrics,"rows":rows,"negatives":negatives,"missing_response_ids":missing}),
    )
}
pub fn check_gate(report: &Value, policy: Option<&Value>) -> Result<Vec<String>> {
    let threshold = match policy.filter(|v| truth(v)) {
        Some(policy) if !policy.is_object() => {
            return Err(invalid("gate policy must be an object"));
        }
        Some(policy) => match policy.get("min_top1") {
            None => 0.9,
            Some(Value::Number(n)) => n
                .as_f64()
                .filter(|n| n.is_finite() && (0.9..=1.).contains(n))
                .ok_or_else(|| invalid("top1 floor must be finite, >=0.90 and <=1"))?,
            _ => return Err(invalid("top1 floor must be finite, >=0.90 and <=1")),
        },
        None => 0.9,
    };
    let mut failures = Vec::new();
    for key in [
        "all",
        "language:en",
        "language:es",
        "purpose:implementation",
    ] {
        let current = report["strata"]
            .get(key)
            .cloned()
            .unwrap_or_else(|| metric(0, 0));
        let total = current["total"].as_u64().unwrap_or(0);
        if total == 0 || current["rate"].as_f64().unwrap_or(0.) < threshold {
            failures.push(format!(
                "strict_top1 {key}: {}/{} < {threshold}",
                current["hits"], current["total"]
            ));
        }
    }
    if report["macro_repo_top1"].as_f64().unwrap_or(0.) < threshold {
        failures.push(format!(
            "strict_top1 macro_repo: {} < {threshold}",
            report["macro_repo_top1"]
        ));
    }
    Ok(failures)
}
