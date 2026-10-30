//! One authoritative source/dependency/engine bracket, optionally supervised by
//! the host's observe hook. Worker children use the default native bracket.
use super::{
    BatchObservation, Observation, QueryEngine, QueryRequest, Result, SourceInputs, invalid,
    model::relative,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
    time::{Duration, Instant},
};
pub fn unknown(reason: impl Into<String>) -> Value {
    json!({"rows":[],"complete":false,"coverage_complete":false,"unknown_candidates":0,"reason":reason.into()})
}
pub(super) fn remaining(start: Instant, budget: Duration) -> Result<Duration> {
    let elapsed = start.elapsed();
    if elapsed >= budget {
        Err(invalid("timeout"))
    } else {
        Ok(budget - elapsed)
    }
}
fn budget(request: &QueryRequest) -> Result<Duration> {
    let ms = request.timeout_ms.unwrap_or(10000.);
    if !ms.is_finite()
        || ms <= 0.0
        || ms > 120000.
        || request.max_rows.unwrap_or(100) == 0
        || request.max_rows.unwrap_or(100) > 1000
    {
        return Err(invalid(
            "timeout_ms must be 1..120000; max_rows must be 1..1000",
        ));
    }
    Ok(Duration::from_secs_f64(ms / 1000.))
}
fn manifest(value: &Value) -> Result<BTreeMap<String, String>> {
    let rows = value["manifest"]
        .as_array()
        .ok_or_else(|| invalid("source manifest unavailable"))?;
    rows.iter()
        .map(|row| {
            let path = row[0]
                .as_str()
                .ok_or_else(|| invalid("invalid source manifest"))?;
            let hash = row[1]
                .as_str()
                .ok_or_else(|| invalid("invalid source manifest"))?;
            Ok((path.to_owned(), hash.to_owned()))
        })
        .collect()
}
fn captured(result: &Observation) -> Result<BTreeMap<String, String>> {
    let analysis = result.metadata("analysis")?.unwrap_or(Value::Null);
    analysis
        .get("manifest")
        .map(|m| manifest(&json!({"manifest":m})))
        .transpose()
        .map(Option::unwrap_or_default)
}
pub fn execute_observation(
    request: &QueryRequest,
    engine: &mut dyn QueryEngine,
    inputs: &mut dyn SourceInputs,
) -> Observation {
    match catch_unwind(AssertUnwindSafe(|| engine.observe(request, inputs))) {
        Ok(Ok(result)) => result,
        Ok(Err(e)) => Observation::unknown(e.to_string()),
        Err(_) => Observation::unknown("native query worker panicked"),
    }
}
pub fn execute(
    request: &QueryRequest,
    engine: &mut dyn QueryEngine,
    inputs: &mut dyn SourceInputs,
) -> Result<Value> {
    execute_observation(request, engine, inputs).to_json()
}
pub(super) fn evaluate<E: QueryEngine + ?Sized>(
    request: &QueryRequest,
    engine: &mut E,
    inputs: &mut dyn SourceInputs,
) -> Result<Observation> {
    let start = Instant::now();
    let total = budget(request)?;
    relative(&request.path)?;
    engine.checkpoint()?;
    inputs.checkpoint()?;
    let before = inputs.capture(
        &request.root,
        &request.path,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    let inspected = manifest(&before)?;
    let dependency_before = inputs.dependencies(
        &request.root,
        &before,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    manifest(&dependency_before)?;
    let version = engine.identity_checked(&mut || {
        engine.checkpoint()?;
        remaining(start, total)?;
        Ok(())
    })?;
    let mut actual = request.clone();
    actual.timeout_ms = Some(remaining(start, total)?.as_secs_f64() * 1000.);
    engine.checkpoint()?;
    let mut result = engine.run_observation(&actual)?;
    engine.checkpoint()?;
    remaining(start, total)?;
    let after = inputs.capture(
        &request.root,
        &request.path,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    let dependency_after = inputs.dependencies(
        &request.root,
        &after,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    let captured = captured(&result)?;
    if before != after
        || dependency_before != dependency_after
        || engine.identity_checked(&mut || {
            engine.checkpoint()?;
            remaining(start, total)?;
            Ok(())
        })? != version
        || captured.iter().any(|(p, h)| inspected.get(p) != Some(h))
    {
        result.invalidate("source_changed_during_check");
    }
    result.set("check_snapshot", &before)?;
    result.set("check_dependencies", &dependency_before)?;
    result.set("check_engine", &version)?;
    engine.checkpoint()?;
    remaining(start, total)?;
    Ok(result)
}
pub fn execute_batch_observation(
    request: &QueryRequest,
    queries: &BTreeMap<String, String>,
    seeds: Option<&[String]>,
    incoming: bool,
    engine: &mut dyn QueryEngine,
    inputs: &mut dyn SourceInputs,
) -> BatchObservation {
    match catch_unwind(AssertUnwindSafe(|| {
        engine.observe_batch(request, queries, seeds, incoming, inputs)
    })) {
        Ok(Ok(batch)) => batch,
        other => {
            let reason = match other {
                Ok(Err(e)) => e.to_string(),
                _ => "native query worker panicked".into(),
            };
            BatchObservation {
                results: queries
                    .keys()
                    .map(|name| (name.clone(), Observation::unknown(reason.clone())))
                    .collect(),
                snapshot: None,
                engine: None,
                selection: None,
            }
        }
    }
}
pub fn execute_batch(
    request: &QueryRequest,
    queries: &BTreeMap<String, String>,
    seeds: Option<&[String]>,
    incoming: bool,
    engine: &mut dyn QueryEngine,
    inputs: &mut dyn SourceInputs,
) -> Result<Value> {
    execute_batch_observation(request, queries, seeds, incoming, engine, inputs).to_json()
}
pub(super) fn evaluate_batch<E: QueryEngine + ?Sized>(
    request: &QueryRequest,
    queries: &BTreeMap<String, String>,
    seeds: Option<&[String]>,
    incoming: bool,
    engine: &mut E,
    inputs: &mut dyn SourceInputs,
) -> Result<BatchObservation> {
    if !(1..=8).contains(&queries.len()) {
        return Err(invalid("a batch requires 1..8 queries"));
    }
    let start = Instant::now();
    let total = budget(request)?;
    engine.checkpoint()?;
    inputs.checkpoint()?;
    let before = inputs.capture(
        &request.root,
        &request.path,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    let inspected = manifest(&before)?;
    let version = engine.identity_checked(&mut || {
        engine.checkpoint()?;
        remaining(start, total)?;
        Ok(())
    })?;
    let selection = if let Some(seeds) = seeds.filter(|s| !s.is_empty()) {
        Some(inputs.select(
            &request.root,
            &before,
            seeds,
            incoming,
            remaining(start, total)?,
        )?)
    } else {
        None
    };
    let selected_paths = selection
        .as_ref()
        .map(|s| {
            s["paths"]
                .as_array()
                .ok_or_else(|| invalid("native source selection unavailable"))?
                .iter()
                .map(|p| {
                    p.as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| invalid("invalid selected source path"))
                })
                .collect::<Result<Vec<_>>>()
        })
        .transpose()?;
    let mut results = BTreeMap::new();
    for (name, source) in queries {
        engine.checkpoint()?;
        inputs.checkpoint()?;
        let result = match remaining(start, total) {
            Ok(left) => {
                let mut actual = request.clone();
                actual.source = source.clone();
                actual.timeout_ms = Some(left.as_secs_f64() * 1000.);
                actual.source_paths = selected_paths
                    .clone()
                    .or_else(|| request.source_paths.clone());
                engine
                    .run_observation(&actual)
                    .unwrap_or_else(|e| Observation::unknown(e.to_string()))
            }
            Err(e) => Observation::unknown(e.to_string()),
        };
        results.insert(name.clone(), result);
    }
    let after = inputs.capture(
        &request.root,
        &request.path,
        remaining(start, total)?.min(Duration::from_secs(2)),
    )?;
    let consistent = before == after
        && engine.identity_checked(&mut || {
            engine.checkpoint()?;
            remaining(start, total)?;
            Ok(())
        })? == version;
    for result in results.values_mut() {
        if !consistent
            || captured(result)?
                .iter()
                .any(|(p, h)| inspected.get(p) != Some(h))
        {
            result.invalidate("source_changed_during_check");
        }
        result.set("check_snapshot", &before)?;
        result.set("check_engine", &version)?;
    }
    engine.checkpoint()?;
    remaining(start, total)?;
    Ok(BatchObservation {
        results,
        snapshot: Some(before),
        engine: Some(version),
        selection,
    })
}
