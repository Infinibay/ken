//! Rendering never changes the engine's result or its certainty.
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
const NOTE: &str = "Structural evidence consistent with an idiom; not proof of intent.";
pub(super) fn directories(matches: &Value, files: &[Value], label: &str) -> Value {
    let mut directories = BTreeMap::<String, BTreeSet<String>>::new();
    let mut counts = BTreeMap::<String, BTreeMap<String, BTreeSet<String>>>::new();
    let parent = |file: &str| {
        Path::new(file)
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .map_or(".".into(), |p| p.to_string_lossy().into_owned())
    };
    for file in files.iter().filter_map(Value::as_str) {
        directories
            .entry(parent(file))
            .or_default()
            .insert(file.into());
    }
    for item in matches.as_array().into_iter().flatten() {
        if let (Some(path), Some(id)) = (item["path"].as_str(), item["id"].as_str()) {
            counts
                .entry(parent(path))
                .or_default()
                .entry(id.into())
                .or_default()
                .insert(path.into());
        }
    }
    json!(directories.into_iter().map(|(directory,paths)|{let mut items=counts.remove(&directory).unwrap_or_default().into_iter().collect::<Vec<_>>();items.sort_by(|(aid,a),(bid,b)|b.len().cmp(&a.len()).then_with(||aid.cmp(bid)));let patterns=items.into_iter().map(|(id,matching)|json!({"id":id,"matching_files":matching.len(),"share":round(matching.len()as f64/paths.len()as f64),"files":matching})).collect::<Vec<_>>();json!({"directory":directory,"analyzed_files":paths.len(),label:patterns})}).collect::<Vec<_>>())
}
fn round(value: f64) -> f64 {
    format!("{value:.3}").parse().unwrap_or(value)
}
fn place(item: &Value, out: &mut Value) {
    out["path"] = item.get("path").cloned().unwrap_or(json!(""));
    out["line"] = item.get("line").cloned().unwrap_or(json!(0));
    if item["symbol"].as_str().is_some_and(|s| !s.is_empty()) {
        out["symbol"] = item["symbol"].clone();
    }
}
fn named(items: &Value, names: &BTreeMap<String, String>, depth: usize) -> Option<String> {
    if depth > 4 {
        return None;
    }
    for item in items.as_array().into_iter().flatten() {
        if let Some(query) = item["query"].as_str() {
            if let Some(name) = names.get(query.split_once(':').map_or(query, |(_, tail)| tail)) {
                return Some(name.clone());
            }
            if let Some((_, variant)) = query.split_once('#') {
                return Some(variant.into());
            }
        }
        for field in ["alternatives", "evidence", "optional"] {
            if let Some(name) = named(&item[field], names, depth + 1) {
                return Some(name);
            }
        }
    }
    None
}
fn variant(item: &Value) -> String {
    if let Some(value) = item["variant"]
        .as_str()
        .filter(|v| !v.is_empty() && *v != "default")
    {
        return value.into();
    }
    let mut names = BTreeMap::new();
    for variant in item["rule"]["variants"].as_array().into_iter().flatten() {
        if let (Some(source), Some(id)) = (variant["query"].as_str(), variant["id"].as_str()) {
            for line in source.lines() {
                if let Some(rest) = line.trim_start().strip_prefix("module ")
                    && let Some(module) = rest.split(';').next()
                {
                    names.insert(format!("{}.detect", module.trim()), id.into());
                    break;
                }
            }
        }
    }
    named(&item["evidence"], &names, 0).unwrap_or_else(|| {
        item["variant"]
            .as_str()
            .filter(|v| !v.is_empty())
            .unwrap_or("default")
            .into()
    })
}
pub fn present(result: &Value, kind: &str, full: bool) -> Value {
    if full {
        return result.clone();
    }
    let field = if kind == "structure" {
        "matches"
    } else {
        "findings"
    };
    let Some(items) = result[field].as_array() else {
        return result.clone();
    };
    let mut out = json!({"ok":result.get("ok").cloned().unwrap_or(json!(true))});
    out[field]=json!(items.iter().map(|item|{let confidence=item["evidence_score"].as_f64().map(round).unwrap_or(1.);let mut row=match kind{"bugs"=>json!({"rule":item.get("id").cloned().unwrap_or(json!("")),"severity":item.get("severity").cloned().unwrap_or(json!("")),"message":item.get("message").cloned().unwrap_or(json!(""))}),"structure"=>json!({"bindings":item.get("bindings").cloned().unwrap_or(json!({})),"confidence":confidence}),_=>json!({"pattern":item.get("id").or_else(||item.get("pattern")).cloned().unwrap_or(json!("")),"variant":variant(item),"confidence":confidence})};place(item,&mut row);if kind!="structure"&&kind!="bugs"{if item["status"].as_str().is_some_and(|s|!s.is_empty()&&s!="structural_match"){row["status"]=item["status"].clone();}
if let Some(unknown)=item["unknown"].as_array().filter(|v|!v.is_empty()){let mut unknown=unknown.clone();unknown.sort_by(|a,b|a.as_str().cmp(&b.as_str()));row["unknown"]=json!(unknown);}}row}).collect::<Vec<_>>());
    out["count"] = json!(items.len());
    if kind != "structure" && kind != "bugs" {
        let mut counts = BTreeMap::<String, usize>::new();
        for item in items {
            let id = item
                .get("id")
                .or_else(|| item.get("pattern"))
                .and_then(Value::as_str)
                .unwrap_or("");
            *counts.entry(id.into()).or_default() += 1;
        }
        let mut counts = counts.into_iter().collect::<Vec<_>>();
        counts.sort_by(|(aid, a), (bid, b)| b.cmp(a).then_with(|| aid.cmp(bid)));
        out["summary"] = Value::Object(
            counts
                .into_iter()
                .map(|(id, count)| (id, json!(count)))
                .collect(),
        );
    }
    if result.get("outcomes").is_some() {
        out["complete"] = result.get("complete").cloned().unwrap_or(json!(true));
        if result["incomplete"]
            .as_object()
            .is_some_and(|v| !v.is_empty())
        {
            out["incomplete"] = result["incomplete"].clone();
        }
    }
    if result["analysis"].is_object() {
        let analysis = &result["analysis"];
        out["analysis"] = json!({"files":analysis["files"].as_array().map_or(0,Vec::len),"skipped":analysis["skipped"].as_array().map_or(0,Vec::len),"coverage_complete":analysis["coverage_complete"].as_bool().unwrap_or(false),"elapsed_ms":analysis["elapsed_ms"]});
    }
    out["note"] = json!(NOTE);
    out
}
