use ken_structural::application::inspection::{
    self, InspectRequest, InspectionQueries, NativeSources, ObservationKind, ObservationLog,
    ObservationRequest, Program,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/inspection-policy-domain.json")).unwrap()
}
fn catalog() -> Arc<ken_syntax::GrammarCatalog> {
    Arc::new(
        ken_syntax::GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
fn project() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    for (path, source) in fixture()["files"].as_object().unwrap() {
        let file = d.path().join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, source.as_str().unwrap()).unwrap();
    }
    d
}
fn id(v: &Value) -> String {
    v.as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| v["local_id"].as_str().unwrap_or("").to_owned())
}
struct PreparedQueries {
    f: Value,
    fail_after: Option<usize>,
    calls: usize,
    change: Option<PathBuf>,
}
impl PreparedQueries {
    fn new() -> Self {
        Self {
            f: fixture(),
            fail_after: None,
            calls: 0,
            change: None,
        }
    }
}
impl InspectionQueries for PreparedQueries {
    fn identity(&self) -> String {
        "prepared-inspection/1".into()
    }
    fn observe(&mut self, request: &ObservationRequest) -> inspection::Result<Value> {
        if self.fail_after == Some(self.calls) {
            return Err(inspection::InspectionError::Invalid(
                "test interruption".into(),
            ));
        }
        self.calls += 1;
        let base = &self.f["batch"]["results"];
        let paths = request.paths.iter().cloned().collect::<BTreeSet<_>>();
        let selected = match &request.kind {
            ObservationKind::Definitions { name } => base["definitions"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|r| {
                    paths.contains(r[0]["path"].as_str().unwrap())
                        && name.as_ref().is_none_or(|n| r[0]["name"] == n.as_str())
                })
                .cloned()
                .collect::<Vec<_>>(),
            ObservationKind::Neighbors {
                identities,
                incoming,
                outgoing,
            } => base["calls"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|r| {
                    let targets = base["targets"]["rows"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .chain(base["possible_targets"]["rows"].as_array().unwrap())
                        .filter(|t| id(&t[0]) == id(&r[1]))
                        .map(|t| id(&t[1]))
                        .collect::<BTreeSet<_>>();
                    paths.contains(r[0]["path"].as_str().unwrap())
                        && ((*incoming && identities.iter().any(|i| targets.contains(i)))
                            || (*outgoing && identities.contains(&id(&r[0]))))
                })
                .cloned()
                .collect(),
            ObservationKind::Targets { sites, possible } => base[if *possible {
                "possible_targets"
            } else {
                "targets"
            }]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|r| {
                    sites.contains(&id(&r[0])) && paths.contains(r[0]["path"].as_str().unwrap())
                })
                .cloned()
                .collect(),
            ObservationKind::Usages { sites } => base["usages"]["rows"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|r| {
                    sites.contains(&id(&r[2])) && paths.contains(r[0]["path"].as_str().unwrap())
                })
                .cloned()
                .collect(),
        };
        let mut result = base[request.kind.name()].clone();
        result["rows"] = json!(selected);
        result["source_scope"] = json!({"kind":"explicit_files","paths":request.paths});
        let manifest = self.f["batch"]["snapshot"]["manifest"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|p| paths.contains(p[0].as_str().unwrap()))
            .cloned()
            .collect::<Vec<_>>();
        result["analysis"] = json!({"manifest":manifest,"parsed_units":paths.len(),"reused_units":0,"scanned_nodes":selected.len(),"states":selected.len(),"build_ms":0.0,"query_ms":0.0,"total_ms":0.0,"result_cache":"disabled"});
        if let Some(path) = self.change.take() {
            std::fs::write(path, "def save():\n return 88\n")?;
        }
        Ok(result)
    }
}
#[test]
fn program_views_match_original_prepared_observation_policy() {
    let f = fixture();
    let p = Program::from_batch(".", &f["batch"]).unwrap();
    let selected = p.select("storage.py::save");
    assert_eq!(
        inspection::impact(&p, &selected, 3, 20),
        f["views"]["impact"]
    );
    assert_eq!(
        inspection::roles(&p, &p.select("api.py::wrapper"), 3, 20),
        f["views"]["roles"]
    );
    assert_eq!(p.coverage(), f["views"]["coverage"]);
    assert_eq!(json!(p.connected(&selected, 3)), f["views"]["connected"]);
}
#[test]
fn transformations_and_ambiguous_returns_stop_identity_propagation() {
    let f = fixture();
    for (case, expected) in [
        ("transformed_batch", "transformed"),
        ("ambiguous_batch", "ambiguous"),
    ] {
        let p = Program::from_batch(".", &f[case]).unwrap();
        let out = inspection::impact(&p, &p.select("storage.py::save"), 3, 20);
        assert_eq!(out, f["views"][expected]);
        assert!(out["tests"].as_array().unwrap().is_empty());
    }
}
#[test]
fn native_python_import_and_access_facts_match_original_ast_metadata() {
    let f = fixture();
    let c = catalog();
    for (path, source) in f["files"].as_object().unwrap() {
        let facts =
            inspection::source_facts(&c, path, source.as_str().unwrap().as_bytes()).unwrap();
        assert_eq!(
            serde_json::to_value(facts).unwrap(),
            f["facts"][path],
            "{path}"
        );
    }
    let p = Program::from_batch(".", &f["batch"]).unwrap();
    for case in f["availability"].as_array().unwrap() {
        let facts = inspection::source_facts(
            &c,
            "consumer.py",
            case["source"].as_str().unwrap().as_bytes(),
        )
        .unwrap();
        assert_eq!(serde_json::to_value(&facts).unwrap(), case["facts"]);
        assert_eq!(
            inspection::available(&p, &p.select("storage.py::save"), &facts),
            case["result"]
        );
    }
}
#[test]
fn explorer_runs_focused_frontiers_and_matches_original_public_contract() {
    let d = project();
    let f = fixture();
    for (relation, target) in [
        ("impact", "storage.py::save"),
        ("roles", "api.py::wrapper"),
        ("available", "storage.py::save"),
    ] {
        let mut queries = PreparedQueries::new();
        let mut sources = NativeSources::new(catalog());
        let request = InspectRequest {
            target: target.into(),
            relation: relation.into(),
            depth: 3,
            from_path: if relation == "available" {
                "consumer.py".into()
            } else {
                String::new()
            },
            ..Default::default()
        };
        let actual =
            inspection::inspect_with(d.path(), &request, &mut queries, &mut sources).unwrap();
        assert_eq!(actual, f["public"][relation], "{relation}");
    }
}
#[test]
fn coherent_partial_frontier_survives_but_source_changes_discard_all_facts() {
    let d = project();
    let mut sources = NativeSources::new(catalog());
    let mut queries = PreparedQueries::new();
    queries.fail_after = Some(1);
    let request = InspectRequest {
        target: "storage.py::save".into(),
        full: true,
        depth: 3,
        ..Default::default()
    };
    let partial = inspection::inspect_with(d.path(), &request, &mut queries, &mut sources).unwrap();
    assert!(!partial["targets"].as_array().unwrap().is_empty());
    assert_eq!(partial["coverage"]["calls"]["complete"], false);
    let mut queries = PreparedQueries::new();
    queries.change = Some(d.path().join("storage.py"));
    let changed = inspection::inspect_with(d.path(), &request, &mut queries, &mut sources).unwrap();
    assert_eq!(changed["status"], "unknown");
    assert!(changed["targets"].as_array().unwrap().is_empty());
    assert_eq!(
        changed["coverage"]["calls"]["reason"],
        "source_changed_during_inspection"
    );
}
#[test]
fn observation_log_retains_partial_rows_and_discards_mixed_manifests() {
    let f = fixture();
    let mut log = ObservationLog::new();
    let a = f["batch"]["results"]["definitions"]["rows"][0][0].clone();
    let b = f["batch"]["results"]["calls"]["rows"][1].clone();
    let mut definitions = f["batch"]["results"]["definitions"].clone();
    definitions["rows"] = json!([[a]]);
    definitions["analysis"] = json!({"manifest":[["storage.py","a".repeat(64)]],"parsed_units":1});
    definitions["source_scope"] = json!({"kind":"explicit_files","paths":["storage.py"]});
    log.add("definitions", "locate fixture", &definitions)
        .unwrap();
    let mut calls = f["batch"]["results"]["calls"].clone();
    calls["rows"] = json!([b]);
    calls["complete"] = json!(false);
    calls["reason"] = json!("test interruption");
    calls["analysis"] = json!({"manifest":[["api.py","b".repeat(64)]]});
    log.add("calls", "partial fixture", &calls).unwrap();
    let selection = json!({"paths":["api.py","storage.py"]});
    assert_eq!(
        log.batch(&f["batch"]["snapshot"], "prepared-inspection/1", &selection),
        f["partial"]
    );
    definitions["analysis"] = json!({"manifest":[["storage.py","c".repeat(64)]]});
    definitions.as_object_mut().unwrap().remove("source_scope");
    log.add("definitions", "changed fixture", &definitions)
        .unwrap();
    assert_eq!(
        log.batch(&f["batch"]["snapshot"], "prepared-inspection/1", &selection),
        f["invalidated"]
    );
}
#[test]
fn actual_native_session_inspection_observes_return_chain_and_access_alias() {
    let d = project();
    let c = catalog();
    let request = InspectRequest {
        target: "storage.py::save".into(),
        depth: 3,
        ..Default::default()
    };
    let actual =
        inspection::inspect_native(d.path(), &request, c.clone(), Default::default()).unwrap();
    assert_eq!(actual["status"], "observed");
    assert!(
        actual["consumers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["caller"]["name"] == "wrapper")
    );
    assert!(
        actual["tests"]
            .as_array()
            .unwrap()
            .iter()
            .any(|v| v["caller"]["name"] == "test_value")
    );
    let request = InspectRequest {
        target: "storage.py::save".into(),
        relation: "available".into(),
        from_path: "consumer.py".into(),
        ..Default::default()
    };
    assert_eq!(
        inspection::inspect_native(d.path(), &request, c, Default::default()).unwrap()["candidates"]
            [0]["expression"],
        "backend.save"
    );
}
#[test]
fn qualified_targets_are_confined_and_missing_targets_do_not_scan_unrelated_scope() {
    let d = project();
    let mut q = PreparedQueries::new();
    let mut s = NativeSources::new(catalog());
    let bad = InspectRequest {
        target: "../outside.py::save".into(),
        ..Default::default()
    };
    assert!(inspection::inspect_with(d.path(), &bad, &mut q, &mut s).is_err());
    let missing = InspectRequest {
        target: "missing.py::save".into(),
        ..Default::default()
    };
    let out = inspection::inspect_with(d.path(), &missing, &mut q, &mut s).unwrap();
    assert_eq!(out["status"], "unknown");
    assert!(out["targets"].as_array().unwrap().is_empty());
}
#[test]
fn changed_availability_context_cannot_mix_new_binding_with_old_snapshot() {
    struct Changing {
        inner: NativeSources,
        changed: bool,
    }
    impl inspection::InspectionSources for Changing {
        fn capture(
            &mut self,
            root: &Path,
            scope: &str,
            budget: std::time::Duration,
        ) -> inspection::Result<Value> {
            inspection::InspectionSources::capture(&mut self.inner, root, scope, budget)
        }
        fn facts(
            &mut self,
            root: &Path,
            path: &str,
            budget: std::time::Duration,
        ) -> inspection::Result<inspection::SourceFacts> {
            if path == "consumer.py" && !self.changed {
                self.changed = true;
                std::fs::write(root.join(path), "from storage import save as persist\n")?;
            }
            inspection::InspectionSources::facts(&mut self.inner, root, path, budget)
        }
    }
    let d = project();
    let mut source = Changing {
        inner: NativeSources::new(catalog()),
        changed: false,
    };
    let mut queries = PreparedQueries::new();
    let request = InspectRequest {
        target: "storage.py::save".into(),
        relation: "available".into(),
        from_path: "consumer.py".into(),
        full: true,
        ..Default::default()
    };
    let out = inspection::inspect_with(d.path(), &request, &mut queries, &mut source).unwrap();
    assert_eq!(out["status"], "unknown");
    assert!(out["candidates"].as_array().unwrap().is_empty());
    assert_eq!(
        out["observations"]["definitions"]["reason"],
        "source_changed_during_inspection"
    );
}
#[test]
fn import_selection_does_not_expand_through_a_shared_dependency_and_notices_new_targets() {
    use inspection::InspectionSources;
    let d = project();
    std::fs::write(d.path().join("common.py"), "def helper(): return 1\n").unwrap();
    std::fs::write(
        d.path().join("storage.py"),
        "from common import helper\ndef save(): return helper()\n",
    )
    .unwrap();
    std::fs::write(
        d.path().join("unrelated.py"),
        "from common import helper\ndef other(): return helper()\n",
    )
    .unwrap();
    let mut sources = NativeSources::new(catalog());
    let snapshot = sources
        .capture(d.path(), ".", std::time::Duration::from_secs(2))
        .unwrap();
    let selected = inspection::select_sources(
        d.path(),
        &snapshot,
        &["storage.py".into()],
        true,
        &mut sources,
        std::time::Duration::from_secs(2),
    )
    .unwrap();
    let paths = selected["paths"].as_array().unwrap();
    for path in ["storage.py", "common.py", "api.py", "tests/test_api.py"] {
        assert!(paths.contains(&json!(path)));
    }
    assert!(!paths.contains(&json!("unrelated.py")));
    std::fs::write(
        d.path().join("api.py"),
        "from optional_store import save\ndef wrapper(): return save()\n",
    )
    .unwrap();
    let api = sources
        .capture(d.path(), "api.py", std::time::Duration::from_secs(2))
        .unwrap();
    let before = inspection::dependencies(
        d.path(),
        &api,
        &mut sources,
        std::time::Duration::from_secs(2),
    )
    .unwrap();
    std::fs::write(d.path().join("optional_store.py"), "def save(): return 1\n").unwrap();
    let after = inspection::dependencies(
        d.path(),
        &api,
        &mut sources,
        std::time::Duration::from_secs(2),
    )
    .unwrap();
    assert_ne!(before, after);
    assert!(
        after["manifest"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p[0] == "optional_store.py")
    );
}
