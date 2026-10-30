//! Corroborate selected hypotheses with one bounded inspection acquisition.
//! Structural observations never feed back into heuristic confidence.
use crate::{Result, WhoReport, invalid};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_structural::application::inspection::{
    self, ExploreRequest, InspectionQueries, InspectionSources, Program,
};
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::Arc,
};
pub fn enrich_program(report: &mut WhoReport, program: &Program) -> Result<()> {
    let manifest = program
        .snapshot
        .as_ref()
        .and_then(|s| s["manifest"].as_array())
        .into_iter()
        .flatten()
        .filter_map(|p| p[0].as_str().zip(p[1].as_str()))
        .collect::<BTreeMap<_, _>>();
    let coverage = program.coverage();
    let mut seeds = Vec::new();
    let mut seen = BTreeSet::new();
    for candidate in &mut report.candidates {
        if manifest.get(candidate.path.as_str()).copied() != Some(candidate.source.sha256.as_str())
        {
            candidate.structure = Some(
                json!({"scope":program.scope,"reason":"Source changed or structural acquisition incomplete."}),
            );
            continue;
        }
        let selected = program
            .select(&candidate.path)
            .into_iter()
            .filter(|key| {
                let node = &program.nodes[key];
                node["path"] == candidate.path
                    && (candidate.kind == "module"
                        || node["line"].as_u64() == Some(candidate.line as u64)
                        || candidate.kind == "class"
                            && inspection::qualname(node)
                                .starts_with(&format!("{}.", candidate.symbol)))
            })
            .collect::<BTreeSet<_>>();
        if selected.is_empty() {
            continue;
        }
        for key in program.select(&candidate.path) {
            if selected.contains(&key) && seen.insert(key.clone()) {
                seeds.push(key);
            }
        }
        let calls = program
            .calls
            .iter()
            .filter(|c| selected.contains(&c.owner))
            .collect::<Vec<_>>();
        let returned = calls
            .iter()
            .copied()
            .filter(|c| {
                c.targets.iter().any(|target| {
                    inspection::result_uses(program, c, target)
                        .iter()
                        .any(|u| u["kind"] == "return")
                })
            })
            .collect::<Vec<_>>();
        let mut evidence = serde_json::Map::new();
        for (kind, observed, channel) in [
            ("calls", calls, "calls"),
            ("returned_calls", returned, "usages"),
        ] {
            let mut value = coverage[channel].as_object().cloned().unwrap_or_default();
            value.insert(
                "sites".into(),
                json!(
                    observed
                        .iter()
                        .take(5)
                        .map(|c| inspection::location(&c.site))
                        .collect::<Vec<_>>()
                ),
            );
            if observed.len() > 5 {
                value.insert("truncated".into(), json!(true));
            }
            evidence.insert(kind.into(), Value::Object(value));
        }
        let mut observations = serde_json::Map::new();
        for (name, answer) in program.observations.as_object().into_iter().flatten() {
            let result = ken_contracts::checks::query_view(answer, false)
                .map_err(|error| invalid(error.to_string()))?;
            observations.insert(name.clone(),json!({"result":result,"snapshot":answer.get("check_snapshot"),"engine":answer.get("check_engine")}));
        }
        candidate.structure = Some(
            json!({"scope":program.scope,"evidence":evidence,"observations":observations,"claim":"Observed calls and returned identities; business roles remain hypotheses."}),
        );
    }
    if !seeds.is_empty() {
        let mut map = inspection::roles(program, &seeds, 2, 15);
        let mut acquisition = program.selection.clone().unwrap_or(Value::Null);
        if let Some(object) = acquisition.as_object_mut() {
            object.remove("steps");
        }
        map["acquisition"] = acquisition;
        report.responsibility_map = Some(map);
    }
    Ok(())
}
pub fn enrich_with(
    root: &Path,
    report: &mut WhoReport,
    timeout_ms: f64,
    queries: &mut dyn InspectionQueries,
    sources: &mut dyn InspectionSources,
) -> Result<()> {
    if !timeout_ms.is_finite() || !(1.0..=120000.).contains(&timeout_ms) {
        return Err(invalid("timeout_ms must be 1..120000"));
    }
    if report.candidates.is_empty() {
        return Ok(());
    }
    let context = DiscoveryContext::from_process()?;
    let paths = ProjectPaths::at(root, &context)?;
    let scope = report.coverage["scope"].as_str().unwrap_or(".");
    let scope_path = paths.resolve_inside(Path::new(scope), &context)?;
    let analysis_scope = if scope_path.is_file() {
        ".".to_owned()
    } else {
        scope_path
            .strip_prefix(paths.root())
            .map_err(|_| invalid("structural scope escapes project"))?
            .to_string_lossy()
            .into_owned()
    };
    let analysis_scope = if analysis_scope.is_empty() {
        ".".to_owned()
    } else {
        analysis_scope
    };
    let targets = report
        .candidates
        .iter()
        .map(|c| c.path.clone())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let request = ExploreRequest {
        path: analysis_scope.clone(),
        targets,
        relation: "outgoing".into(),
        depth: 2,
        timeout_ms,
        max_rows: 1000,
    };
    let batch = inspection::explore(paths.root(), &request, queries, sources)?;
    let program = Program::from_batch(&analysis_scope, &batch)?;
    enrich_program(report, &program)
}
pub fn enrich_native(
    root: &Path,
    report: &mut WhoReport,
    timeout_ms: f64,
    catalog: Arc<GrammarCatalog>,
    packaged: BTreeMap<String, String>,
) -> Result<()> {
    if !timeout_ms.is_finite() || !(1.0..=120000.).contains(&timeout_ms) {
        return Err(invalid("timeout_ms must be 1..120000"));
    }
    if report.candidates.is_empty() {
        return Ok(());
    }
    let mut queries = inspection::SessionQueries::new(root, catalog.clone(), packaged)?;
    let mut sources = inspection::NativeSources::new(catalog);
    enrich_with(root, report, timeout_ms, &mut queries, &mut sources)
}
