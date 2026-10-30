//! Compact projections inspect only presentation metadata; witnesses stay raw.
use super::{
    CheckObservation, Observation, RawReport, Receipt, Result,
    observation::{Fields, decode, fields, raw, truth},
    wire,
};
use serde_json::{Value, json, value::RawValue};
use std::collections::{BTreeMap, BTreeSet};
fn insert<T: serde::Serialize + ?Sized>(out: &mut Fields, key: &str, value: &T) -> Result<()> {
    out.insert(key.into(), raw(value)?);
    Ok(())
}
fn children(value: &RawValue) -> Result<Vec<Box<RawValue>>> {
    match value.get().trim_start().as_bytes().first() {
        Some(b'[') => decode(value),
        Some(b'{') => Ok(fields(value)?.into_values().collect()),
        _ => Ok(Vec::new()),
    }
}
pub(super) fn locations(value: &RawValue) -> Result<Vec<Box<RawValue>>> {
    let mut pending = vec![RawValue::from_string(value.get().into())?];
    let (mut out, mut seen) = (Vec::new(), BTreeSet::new());
    while let Some(value) = pending.pop() {
        if value.get().trim_start().starts_with('{') {
            let map = fields(&value)?;
            let location = map
                .get("path")
                .is_some_and(|v| v.get().trim_start().starts_with('"'))
                && map.get("line").is_some_and(|v| {
                    let v = v.get().trim();
                    v == "true"
                        || v == "false"
                        || (!v.contains(['.', 'e', 'E'])
                            && !v.trim_start_matches('-').is_empty()
                            && v.trim_start_matches('-')
                                .bytes()
                                .all(|b| b.is_ascii_digit()))
                });
            if location {
                let selected = map
                    .into_iter()
                    .filter(|(k, _)| ["path", "line", "name", "kind"].contains(&k.as_str()))
                    .collect::<Fields>();
                let encoded = raw(&selected)?;
                if seen.insert(encoded.get().to_owned()) {
                    out.push(encoded);
                }
                continue;
            }
            let values = map.into_values().collect::<Vec<_>>();
            pending.extend(values.into_iter().rev());
        } else {
            pending.extend(children(&value)?.into_iter().rev());
        }
    }
    Ok(out)
}
fn compact_evidence(value: &RawValue) -> Result<Option<Box<RawValue>>> {
    let Ok(items) = decode::<Vec<Box<RawValue>>>(value) else {
        return Ok(None);
    };
    if items.is_empty() {
        return Ok(None);
    }
    let mut records = Vec::new();
    for item in items {
        let Ok(map) = fields(&item) else {
            return Ok(None);
        };
        if !map.contains_key("row") || !map.contains_key("evidence") {
            return Ok(None);
        }
        records.push(map);
    }
    let mut anchors = Vec::new();
    for mut item in records {
        let mut sources = BTreeMap::<Vec<u32>, ken_text::PythonText>::new();
        let mut relations = BTreeMap::<Vec<u32>, ken_text::PythonText>::new();
        let mut optional = 0usize;
        let mut pending = vec![item.remove("evidence").unwrap()];
        while let Some(value) = pending.pop() {
            if value.get().trim_start().starts_with('{') {
                let map = fields(&value)?;
                if let Some(source) = map.get("source")
                    && let Ok(values) = decode::<Vec<Box<RawValue>>>(source)
                {
                    for value in values {
                        if let Ok(value) = decode::<ken_text::PythonText>(&value) {
                            sources.insert(value.codepoints().to_vec(), value);
                        }
                    }
                }
                if let Some(relation) = map.get("relation")
                    && let Ok(value) = decode::<ken_text::PythonText>(relation)
                {
                    relations.insert(value.codepoints().to_vec(), value);
                }
                optional += usize::from(map.contains_key("optional"));
                pending.extend(map.into_values());
            } else {
                pending.extend(children(&value)?);
            }
        }
        let mut anchor = Fields::new();
        anchor.insert("row".into(), item.remove("row").unwrap());
        insert(
            &mut anchor,
            "sources",
            &sources.into_values().collect::<Vec<_>>(),
        )?;
        insert(
            &mut anchor,
            "relations",
            &relations.into_values().collect::<Vec<_>>(),
        )?;
        if optional > 0 {
            insert(&mut anchor, "optional_witnesses", &optional)?;
        }
        anchors.push(anchor);
    }
    Ok(Some(raw(&anchors)?))
}
pub fn query_report(result: &Observation, full: bool) -> Result<RawReport> {
    if full {
        return RawReport::new(result);
    }
    let mut out = Fields::new();
    for key in [
        "language",
        "query",
        "columns",
        "rows",
        "complete",
        "coverage_complete",
        "unknown_candidates",
        "results_truncated",
        "source_scope",
        "diagnostics",
    ] {
        if let Some(value) = result.field(key) {
            out.insert(key.into(), RawValue::from_string(value.get().into())?);
        }
    }
    if let Some(reason) = result.field("reason").filter(|v| truth(v)) {
        out.insert("reason".into(), RawValue::from_string(reason.get().into())?);
    }
    if let Some(evidence) = result.field("optional_evidence").filter(|v| truth(v)) {
        if let Some(anchors) = compact_evidence(evidence)? {
            out.insert("evidence".into(), anchors);
        } else {
            out.insert(
                "optional_evidence".into(),
                RawValue::from_string(evidence.get().into())?,
            );
        }
    }
    if let Some(analysis) = result.field("analysis") {
        let map = fields(analysis).unwrap_or_default();
        if let Some(value) = map.get("registry_modules").filter(|v| truth(v)) {
            out.insert("registry_modules".into(), value.clone());
        }
        let mut timing = Fields::new();
        for key in [
            "total_ms",
            "timeout_ms",
            "compile_ms",
            "build_ms",
            "query_ms",
            "startup_ms",
            "preparation_ms",
            "index_wait_ms",
            "prepared_query_ms",
            "session_attempt_ms",
        ] {
            if let Some(value) = map.get(key).and_then(|v| decode::<f64>(v).ok()) {
                insert(&mut timing, key, &wire::round(value, 1))?;
            }
        }
        if !timing.is_empty() {
            insert(&mut out, "timing", &timing)?;
        }
        if let Some(phase) = map.get("stopped_phase").filter(|v| truth(v)) {
            out.insert("stopped_phase".into(), phase.clone());
            let preparation = map
                .into_iter()
                .filter(|(key, _)| {
                    ["parsed_units", "reused_units", "current_path"].contains(&key.as_str())
                })
                .collect::<Fields>();
            insert(&mut out, "preparation", &preparation)?;
        }
    }
    RawReport::new(&out)
}
pub fn observation_report(observation: &CheckObservation) -> Result<RawReport> {
    let mut out = Fields::new();
    for (key, value) in [
        ("rule", &observation.rule),
        ("description", &observation.description),
        ("path", &observation.path),
        ("expectation", &observation.expectation),
        ("status", &observation.status),
    ] {
        insert(&mut out, key, value)?;
    }
    let result = &observation.result;
    let rows = result
        .field("rows")
        .map(decode::<Vec<Box<RawValue>>>)
        .transpose()?
        .unwrap_or_default();
    insert(&mut out, "matches", &rows.len())?;
    let locations = match result.field("rows") {
        Some(value) => locations(value)?,
        None => Vec::new(),
    }
    .into_iter()
    .take(12)
    .collect::<Vec<_>>();
    insert(&mut out, "locations", &locations)?;
    insert(
        &mut out,
        "complete",
        &result.admission().complete.unwrap_or(false),
    )?;
    insert(
        &mut out,
        "coverage_complete",
        &result.admission().coverage_complete.unwrap_or(false),
    )?;
    if let Some(value) = result.field("unknown_candidates") {
        out.insert(
            "unknown_candidates".into(),
            RawValue::from_string(value.get().into())?,
        );
    } else {
        insert(&mut out, "unknown_candidates", &0)?;
    }
    for key in ["reason", "diagnostics"] {
        if let Some(value) = result.field(key).filter(|v| truth(v)) {
            out.insert(key.into(), RawValue::from_string(value.get().into())?);
        }
    }
    if result.admission().results_truncated == Some(true) {
        insert(&mut out, "results_truncated", &true)?;
    }
    if !rows.is_empty() && locations.is_empty() {
        insert(
            &mut out,
            "witnesses",
            &rows.into_iter().take(3).collect::<Vec<_>>(),
        )?;
    }
    RawReport::new(&out)
}
pub fn receipt_report(receipt: &Receipt, full: bool) -> Result<RawReport> {
    if full {
        return RawReport::new(receipt);
    }
    let mut out = Fields::new();
    for (key, value) in [
        ("run_id", &receipt.run_id),
        ("status", &receipt.status),
        ("scope", &receipt.scope),
        ("selection", &receipt.selection),
        ("created_at", &receipt.created_at),
    ] {
        insert(&mut out, key, value)?;
    }
    insert(
        &mut out,
        "checks",
        &receipt
            .checks
            .iter()
            .map(observation_report)
            .collect::<Result<Vec<_>>>()?,
    )?;
    for (key, value) in [
        ("comparison", receipt.comparison.as_ref()),
        ("selection_evidence", receipt.selection_evidence.as_ref()),
    ] {
        if let Some(value) = value.filter(|v| wire::truth(v)) {
            insert(&mut out, key, value)?;
        }
    }
    if let Some(skipped) = receipt.skipped_rules.as_ref().filter(|v| !v.is_empty()) {
        insert(&mut out, "skipped_rules", skipped)?;
    }
    insert(
        &mut out,
        "claim",
        "Selected source contracts only; not proof of runtime behavior or absence of all bugs.",
    )?;
    RawReport::new(&out)
}
pub fn compare_receipts(before: &Receipt, after: &Receipt) -> Value {
    let previous = before
        .checks
        .iter()
        .map(|c| (c.rule.as_str(), c))
        .collect::<BTreeMap<_, _>>();
    let mut checked = BTreeSet::new();
    let mut changes = Vec::new();
    for item in &after.checks {
        checked.insert(item.rule.as_str());
        let old = previous.get(item.rule.as_str()).copied();
        let comparable = old.is_some_and(|old| {
            old.revision == item.revision && old.path == item.path && old.engine == item.engine
        });
        let status = if !comparable {
            "not_comparable"
        } else {
            let old = old.unwrap();
            if old.status == "unknown" || item.status == "unknown" {
                "inconclusive"
            } else if old.status == item.status {
                "unchanged"
            } else if item.status == "fail" {
                "regression"
            } else {
                "resolved"
            }
        };
        changes.push(json!({"rule":item.rule,"change":status,"before":old.map(|o|o.status.as_str()),"after":item.status,"matches_before":old.map(|o|o.result.row_count().unwrap_or(0)),"matches_after":item.result.row_count().unwrap_or(0)}));
    }
    json!({"baseline":before.run_id,"changes":changes,"not_checked":previous.keys().filter(|k|!checked.contains(**k)).collect::<Vec<_>>()})
}
