//! Whole-conclusion projection and explicit per-session delivery state.
use crate::{Result, invalid, records, wire};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};
pub fn clip(text: &str, limit: usize) -> String {
    let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if text.chars().count() <= limit {
        text
    } else {
        format!(
            "{}…",
            text.chars()
                .take(limit.saturating_sub(1))
                .collect::<String>()
        )
    }
}
fn text<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
pub fn summary(hit: &Value) -> Value {
    let d = &hit["justification"];
    let sources = d["evidence"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|e| !text(e, "path").starts_with(".ken/"))
        .map(|e| json!({"path":e["path"],"note":e.get("note").cloned().unwrap_or(json!(""))}))
        .collect::<Vec<_>>();
    json!({"topic":hit["topic"],"conclusion":hit.get("content").cloned().unwrap_or(json!("")),"conclusion_complete":true,"kind":d.get("kind").cloned().unwrap_or(json!("note")),"validity":hit.get("validity").cloned().unwrap_or(json!({"state":"untracked"})),"rationale":clip(text(d,"rationale"),240),"assumptions":d.get("assumptions").cloned().unwrap_or(json!([])),"sources":sources,"recheck":clip(text(d,"recheck"),160),"expand":{"topic":hit["topic"],"detail":"full"}})
}
pub fn answer(hit: &Value) -> Value {
    let mut result = summary(hit);
    result.as_object_mut().unwrap().remove("rationale");
    let validity = hit
        .get("validity")
        .cloned()
        .unwrap_or(json!({"state":"untracked"}));
    let state = validity["state"].as_str().unwrap_or("unknown");
    result["validity"] = json!({"state":state});
    if state == "unchanged" {
        result.as_object_mut().unwrap().remove("recheck");
        result["reuse"] = json!("consider_if_question_and_assumptions_match");
    } else {
        result["reuse"] = json!("review_inputs_before_reusing");
        if validity["issues"].as_array().is_some_and(|a| !a.is_empty()) {
            result["validity"]["issues"] = validity["issues"].clone();
        }
    }
    if let Some(checks) = validity["checks"].as_array().filter(|a| !a.is_empty()) {
        result["validity"]["checks"] = json!(
            checks
                .iter()
                .map(|c| json!({"status":c["status"],"validity":c["validity"],"rules":c["rules"]}))
                .collect::<Vec<_>>()
        );
    }
    result
}
pub fn compact(hits: &[Value], max_chars: usize, detail: &str) -> Result<Value> {
    if !(300..=20000).contains(&max_chars) {
        return Err(invalid("max_chars must be 300..20000"));
    }
    let mut out = json!({"memories":[],"omitted":hits.len(),"detail":detail});
    if detail == "answer" {
        out["validity_scope"] = json!(
            "Declared inputs only; the conclusion and assumptions are not independently proved."
        );
    }
    for hit in hits {
        let mut candidate = out.clone();
        candidate["memories"]
            .as_array_mut()
            .unwrap()
            .push(if detail == "answer" {
                answer(hit)
            } else {
                summary(hit)
            });
        candidate["omitted"] = json!(out["omitted"].as_u64().unwrap() - 1);
        if wire::json(&candidate).chars().count() <= max_chars {
            out = candidate;
            continue;
        }
        let mut candidate = out.clone();
        candidate["memories"].as_array_mut().unwrap().push(json!({"topic":hit["topic"],"conclusion_omitted":true,"validity":{"state":hit["validity"].get("state").cloned().unwrap_or(json!("untracked"))},"expand":{"topic":hit["topic"],"detail":"full"}}));
        candidate["omitted"] = json!(out["omitted"].as_u64().unwrap() - 1);
        if wire::json(&candidate).chars().count() <= max_chars {
            out = candidate;
        }
    }
    Ok(out)
}
pub fn brief_line(hit: &Value, max_chars: usize) -> String {
    let d = &hit["justification"];
    let state = hit["validity"]["state"].as_str().unwrap_or("untracked");
    let mut label = match state {
        "unchanged" => "dependencias sin cambios",
        "stale" => "REVISAR: cambió una dependencia",
        "unknown" => "REVISAR: vigencia desconocida",
        "untracked" => "sin vigencia comprobada",
        _ => "REVISAR",
    }
    .to_owned();
    if d["kind"] == "hypothesis" {
        label.push_str("; hipótesis");
    }
    if d["assumptions"].as_array().is_some_and(|a| !a.is_empty()) {
        label.push_str("; supuestos pendientes");
    }
    let mut line = format!(
        "[{label}] {} — {}",
        clip(text(hit, "topic"), 120),
        clip(text(hit, "content"), 200)
    );
    if state == "stale" || state == "unknown" {
        let issues = hit["validity"]["issues"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>()
            .join("; ");
        let recheck = text(d, "recheck");
        line.push_str(&format!(
            ". Revisar: {}",
            clip(if recheck.is_empty() { &issues } else { recheck }, 130)
        ));
    } else if !text(d, "rationale").is_empty() {
        line.push_str(&format!(". Motivo: {}", clip(text(d, "rationale"), 130)));
    }
    clip(&line, max_chars)
}
pub fn render_brief(
    hits: &[Value],
    max_chars: usize,
    seen: &mut BTreeMap<String, String>,
) -> String {
    let header =
        "<ken-knowledge>\nVigencia de dependencias declaradas; conservar alcance y supuestos.\n";
    let footer =
        "\nRecuperar conclusión: ken_recall(topic=\"…\", detail=\"answer\").\n</ken-knowledge>";
    let mut lines = Vec::new();
    for hit in hits {
        if hit.get("justification").is_none() {
            continue;
        }
        let signature = wire::digest(hit);
        let topic = text(hit, "topic");
        if seen.get(topic) == Some(&signature) {
            continue;
        }
        let line = format!("- {}", brief_line(hit, 450));
        let mut next = lines.clone();
        next.push(line.clone());
        if format!("{header}{}{footer}", next.join("\n"))
            .chars()
            .count()
            > max_chars
        {
            continue;
        }
        lines.push(line);
        seen.insert(topic.to_owned(), signature);
    }
    if lines.is_empty() {
        String::new()
    } else {
        format!("{header}{}{footer}", lines.join("\n"))
    }
}
pub fn recall_view(
    db: &rusqlite::Connection,
    result: &Value,
    root: Option<&Path>,
    detail: &str,
    max_chars: usize,
    checks: &[records::CheckObservation],
) -> Result<Value> {
    if let Some(hits) = result.as_array() {
        let enriched = records::enrich(db, hits, root, checks)?;
        return if detail == "full" {
            Ok(json!(enriched))
        } else {
            compact(&enriched, max_chars, detail)
        };
    }
    if !result.is_object() {
        return Ok(result.clone());
    }
    let mut result = result.clone();
    let mut hits = Vec::new();
    if let Some(topic) = result["topic"].as_str().filter(|s| !s.is_empty()) {
        let focused = records::for_topics(db, &[topic.to_owned()], root, checks)?;
        if let Some(first) = focused.first() {
            result["finding"] = first.clone();
            hits.extend(focused);
        }
    }
    for key in ["findings", "neighbors", "related"] {
        if let Some(items) = result[key].as_array() {
            let enriched = records::enrich(db, items, root, checks)?;
            hits.extend(enriched.clone());
            result[key] = json!(enriched);
        }
    }
    if detail == "full" {
        Ok(result)
    } else {
        compact(&hits, max_chars, detail)
    }
}
