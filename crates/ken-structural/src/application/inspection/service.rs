use super::{
    InspectionQueries, InspectionSources, ObservationLog, Program, Result, availability,
    exploration::{ExploreRequest, explore},
    impact, invalid, roles,
};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    path::Path,
    time::{Duration, Instant},
};
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct InspectRequest {
    pub target: String,
    pub relation: String,
    pub path: String,
    pub depth: usize,
    pub limit: usize,
    pub timeout_ms: f64,
    pub full: bool,
    pub from_path: String,
}
impl Default for InspectRequest {
    fn default() -> Self {
        Self {
            target: String::new(),
            relation: "impact".into(),
            path: ".".into(),
            depth: 2,
            limit: 10,
            timeout_ms: 10000.,
            full: false,
            from_path: String::new(),
        }
    }
}
fn normalize(paths: &ProjectPaths, context: &DiscoveryContext, value: &str) -> Result<String> {
    let file = paths.resolve_inside(Path::new(value), context)?;
    let relative = file
        .strip_prefix(paths.root())
        .map_err(|_| invalid("source path escapes project root"))?
        .to_string_lossy()
        .into_owned();
    Ok(if relative.is_empty() {
        ".".into()
    } else {
        relative
    })
}
fn available_result(
    root: &Path,
    path: &str,
    scope: &str,
    program: &mut Program,
    seeds: &mut Vec<String>,
    sources: &mut dyn InspectionSources,
    deadline: Instant,
) -> Value {
    let outcome = (|| -> Result<Value> {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| invalid("inspection time budget exhausted"))?;
        let facts = sources.facts(root, path, remaining)?;
        let expected = program
            .snapshot
            .as_ref()
            .and_then(|snapshot| snapshot["manifest"].as_array())
            .and_then(|m| m.iter().find(|p| p[0] == path))
            .and_then(|p| p[1].as_str());
        let context_changed = expected.is_some_and(|hash| hash != facts.sha256);
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| invalid("inspection time budget exhausted"))?;
        let current = sources.capture(root, scope, remaining)?;
        if context_changed
            || program
                .snapshot
                .as_ref()
                .is_some_and(|before| before != &current)
        {
            program.discard("source_changed_during_inspection");
            seeds.clear();
            return Ok(
                json!({"status":"unknown","context":path,"candidates":[],"reason":"source_changed_during_inspection"}),
            );
        }
        Ok(availability::describe(program, seeds, &facts))
    })();
    match outcome {
        Ok(result) => result,
        Err(error) => {
            json!({"status":"unknown","context":path,"candidates":[],"reason":error.to_string()})
        }
    }
}
pub fn inspect_with(
    root: &Path,
    request: &InspectRequest,
    queries: &mut dyn InspectionQueries,
    sources: &mut dyn InspectionSources,
) -> Result<Value> {
    let started = Instant::now();
    if !(1..=8).contains(&request.depth) || !(1..=100).contains(&request.limit) {
        return Err(invalid("depth must be 1..8 and limit 1..100"));
    }
    if !["impact", "roles", "available"].contains(&request.relation.as_str()) {
        return Err(invalid("relation must be impact, roles or available"));
    }
    if request.target.trim().is_empty() || request.target.chars().count() > 2000 {
        return Err(invalid("target must be a nonempty path or symbol"));
    }
    if !request.timeout_ms.is_finite() || !(1.0..=120000.).contains(&request.timeout_ms) {
        return Err(invalid("timeout_ms must be 1..120000"));
    }
    let deadline = started
        .checked_add(Duration::from_secs_f64(request.timeout_ms / 1000.))
        .ok_or_else(|| invalid("inspection budget out of range"))?;
    let context = DiscoveryContext::from_process()?;
    let paths = ProjectPaths::at(root, &context)?;
    let scope = normalize(&paths, &context, &request.path)?;
    let mut target = request.target.clone();
    let (file, symbol) = target
        .split_once("::")
        .map_or((target.as_str(), None), |(p, s)| (p, Some(s)));
    if symbol.is_some() || file.contains('/') || paths.root().join(file).exists() {
        let file = normalize(&paths, &context, file)?;
        target = if let Some(symbol) = symbol {
            format!("{file}::{symbol}")
        } else {
            file
        };
    }
    let from_path = if request.relation == "available" {
        if request.from_path.is_empty() {
            return Err(invalid("available requires from_path"));
        }
        normalize(&paths, &context, &request.from_path)?
    } else {
        String::new()
    };
    let exploration = ExploreRequest {
        path: scope.clone(),
        targets: vec![target.clone()],
        relation: request.relation.clone(),
        depth: request.depth,
        timeout_ms: (request.timeout_ms - started.elapsed().as_secs_f64() * 1000.).max(1.),
        max_rows: 1000,
    };
    let batch = match explore(paths.root(), &exploration, queries, sources) {
        Ok(batch) => batch,
        Err(error) => {
            let mut log = ObservationLog::new();
            log.fail(&error.to_string(), false);
            log.batch(&Value::Null, &queries.identity(), &Value::Null)
        }
    };
    let mut program = Program::from_batch(&scope, &batch)?;
    let mut seeds = program.select(&target);
    let mut result = match request.relation.as_str() {
        "roles" => roles::describe(&program, &seeds, request.depth, request.limit),
        "available" => available_result(
            paths.root(),
            &from_path,
            &scope,
            &mut program,
            &mut seeds,
            sources,
            deadline,
        ),
        _ => impact::analyze(&program, &seeds, request.depth, request.limit),
    };
    if result.get("status").is_none() {
        result["status"] = json!(if seeds.is_empty() {
            "unknown"
        } else {
            "observed"
        });
    }
    result["acquisition"] = match &program.selection {
        None => Value::Null,
        Some(selection) if request.full => selection.clone(),
        Some(selection) => {
            let mut selection = selection.clone();
            if let Some(map) = selection.as_object_mut() {
                map.remove("steps");
            }
            selection
        }
    };
    if seeds.is_empty() {
        let incomplete = program
            .coverage()
            .as_object()
            .into_iter()
            .flatten()
            .any(|(_, v)| !super::truth(&v["complete"]));
        result["reason"] = json!(if incomplete {
            "Analysis incomplete; inspect coverage for budgets or unsupported code."
        } else {
            "Target not resolved in the inspected scope; qualify with file::symbol."
        });
    }
    if request.full {
        result["observations"] = program.observations;
        result["snapshot"] = program.snapshot.unwrap_or(Value::Null);
    }
    Ok(result)
}
