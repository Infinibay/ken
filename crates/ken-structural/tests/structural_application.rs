use ken_query::execution::QueryBudget;
use ken_structural::application::search::{
    SearchOptions, SearchRequest, StructuralApplication, present,
};
use ken_syntax::GrammarCatalog;
use serde_json::json;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
fn app(root: &Path) -> StructuralApplication {
    let grammars = GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap();
    StructuralApplication::new(root, Arc::new(grammars)).unwrap()
}
#[test]
fn invalid_queries_and_selection_fail_before_source_scan_or_cache_creation() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let options = SearchOptions {
        path: "missing".into(),
        ..Default::default()
    };
    assert!(
        app.search(
            SearchRequest {
                query: "query broken { emit $unbound; }".into(),
                ..Default::default()
            },
            options.clone()
        )
        .is_err()
    );
    assert!(!root.path().join(".ken").exists());
    assert!(
        app.search(
            SearchRequest {
                query: "require $x ENTITY CLASS".into(),
                rules: vec!["singleton".into()],
                ..Default::default()
            },
            options
        )
        .is_err()
    );
    assert!(!root.path().join(".ken").exists());
}
#[test]
fn saved_and_inline_queries_share_live_source_locations_and_reusable_complete_results() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("a.py"), "class Alpha:\n    pass\n").unwrap();
    let app = app(root.path());
    let request = SearchRequest {
        query: "require $unit ENTITY CLASS".into(),
        ..Default::default()
    };
    let first = app.search(request.clone(), Default::default()).unwrap();
    assert_eq!(first["matches"].as_array().unwrap().len(), 1);
    assert_eq!(first["matches"][0]["path"], "a.py");
    assert_eq!(first["matches"][0]["symbol"], "Alpha");
    assert_eq!(first["directories"][0]["rules"][0]["matching_files"], 1);
    let second = app.search(request.clone(), Default::default()).unwrap();
    assert!(second["analysis"]["query_cache"]["hits"].as_u64().unwrap() > 0);
    std::fs::write(
        root.path().join("a.py"),
        "class Beta:\n    pass\nclass Gamma:\n    pass\n",
    )
    .unwrap();
    let third = app.search(request, Default::default()).unwrap();
    assert_eq!(third["matches"].as_array().unwrap().len(), 2);
    assert_eq!(third["analysis"]["query_cache"]["hits"], 0);
    assert_eq!(third["directories"][0]["rules"][0]["matching_files"], 1);
    let block = app
        .search(
            SearchRequest {
                query: "query classes { class() as $c; emit $c; }".into(),
                ..Default::default()
            },
            Default::default(),
        )
        .unwrap();
    assert_eq!(block["matches"].as_array().unwrap().len(), 2);
}
#[test]
fn saved_dependency_edits_invalidate_the_callers_results_and_named_selection_is_executable() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(
        root.path().join("a.py"),
        "class Alpha: pass\nclass Beta: pass\n",
    )
    .unwrap();
    std::fs::create_dir_all(root.path().join(".ken/rules")).unwrap();
    let saved = root.path().join(".ken/rules/team.toml");
    std::fs::write(
        &saved,
        "id='team.classes'\nquery='class(name:\"Alpha\") as x;'\n",
    )
    .unwrap();
    let app = app(root.path());
    let request = SearchRequest {
        query: "query caller { match \"team.classes\"(x:$x); emit $x; }".into(),
        ..Default::default()
    };
    let first = app.search(request.clone(), Default::default()).unwrap();
    assert_eq!(first["matches"].as_array().unwrap().len(), 1);
    std::fs::write(
        &saved,
        "id='team.classes'\nquery='class(name:\"Absent\") as x;'\n",
    )
    .unwrap();
    let second = app.search(request, Default::default()).unwrap();
    assert_eq!(second["matches"].as_array().unwrap().len(), 0);
    assert_eq!(second["analysis"]["query_cache"]["hits"], 0);
    let selected = app
        .search(
            SearchRequest {
                rules: vec!["legacy.gof.singleton".into()],
                ..Default::default()
            },
            Default::default(),
        )
        .unwrap();
    assert!(selected["outcomes"].get("legacy.gof.singleton").is_some());
}
#[test]
fn bugs_coverage_budgets_and_compact_presentation_keep_uncertainty() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(
        root.path().join("a.py"),
        "def mutable(xs=[]): return xs\nclass Alpha: pass\nclass Beta: pass\n",
    )
    .unwrap();
    std::fs::write(root.path().join("gap.c"), "int gap;\n").unwrap();
    let app = app(root.path());
    let bugs = app.bugs(Default::default()).unwrap();
    assert!(
        bugs["findings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|f| f["id"] == "mutable-default-argument")
    );
    assert_eq!(bugs["analysis"]["coverage_complete"], false);
    let request = SearchRequest {
        query: "require $x ENTITY CLASS".into(),
        ..Default::default()
    };
    let limited = app
        .search(
            request.clone(),
            SearchOptions {
                budget: QueryBudget {
                    max_matches: Some(1),
                    ..Default::default()
                },
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(limited["complete"], false);
    assert!(!limited["unknown"].as_array().unwrap().is_empty());
    let full = app.search(request, Default::default()).unwrap();
    assert_eq!(full["matches"].as_array().unwrap().len(), 2);
    let compact = present(&limited, "structure", false);
    assert_eq!(compact["complete"], false);
    assert!(compact.get("analysis").is_some());
    assert!(compact["matches"][0].get("evidence").is_none());
    assert_eq!(present(&bugs, "bugs", true), bugs);
    let patterns = app
        .patterns(&["singleton".into()], Default::default())
        .unwrap();
    assert!(patterns["outcomes"].get("singleton").is_some());
}
#[test]
fn zero_cache_works_without_persistent_artifacts_and_metadata_escapes_are_rejected() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("a.py"), "class Alpha: pass\n").unwrap();
    let app = app(root.path());
    let request = SearchRequest {
        query: "require $x ENTITY CLASS".into(),
        ..Default::default()
    };
    let answer = app
        .search(
            request.clone(),
            SearchOptions {
                cache_mb: Some(0.),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(answer["matches"].as_array().unwrap().len(), 1);
    assert_eq!(answer["analysis"]["query_cache"]["enabled"], false);
    assert!(!root.path().join(".ken").exists());
    let outside = tempfile::tempdir().unwrap();
    std::os::unix::fs::symlink(outside.path(), root.path().join(".ken")).unwrap();
    assert!(app.search(request, Default::default()).is_err());
    assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
    let rendered = present(
        &json!({"ok":true,"findings":[],"complete":false,"outcomes":{},"incomplete":{"x":["budget:max_states"]},"analysis":{"files":["a.py"],"skipped":[],"coverage_complete":true,"elapsed_ms":1.}}),
        "patterns",
        false,
    );
    assert_eq!(rendered["complete"], false);
    assert_eq!(rendered["analysis"]["files"], 1);
}
#[test]
fn public_queries_bugs_patterns_locations_and_reports_match_fresh_original_observations() {
    use sha2::Digest;
    use std::io::Read;
    let bytes = include_bytes!("fixtures/structural-service-reference.json.gz");
    assert_eq!(bytes.len(), 828);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "686443b8d68b150f69b5a8db2d6f78aaac31d38dc4b00f91d50792a4bc2abd86"
    );
    let mut text = String::new();
    flate2::read::GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let fixture: serde_json::Value = serde_json::from_str(&text).unwrap();
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("pkg")).unwrap();
    std::fs::write(
        root.path().join("pkg/a.py"),
        "class Alpha:\n    pass\nclass Beta:\n    pass\ndef mutable(xs=[]): return xs\n",
    )
    .unwrap();
    std::fs::write(root.path().join("pkg/b.py"), "class Gamma: pass\n").unwrap();
    let app = app(root.path());
    for case in fixture["cases"].as_array().unwrap() {
        let options = SearchOptions {
            cache_mb: Some(0.),
            ..Default::default()
        };
        let kind = case["kind"].as_str().unwrap();
        let result = match kind {
            "bugs" => app.bugs(options),
            "patterns" => app.patterns(&["singleton".into()], options),
            _ => app.search(
                SearchRequest {
                    query: case["query"].as_str().unwrap().into(),
                    ..Default::default()
                },
                options,
            ),
        }
        .unwrap();
        let field = if kind == "structure" {
            "matches"
        } else {
            "findings"
        };
        let rows = result[field]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| {
                serde_json::Value::Object(
                    item.as_object()
                        .unwrap()
                        .iter()
                        .filter(|(key, _)| {
                            [
                                "id",
                                "path",
                                "line",
                                "symbol",
                                "variant",
                                "status",
                                "unknown",
                                "evidence_score",
                                "category",
                                "caveat",
                                "message",
                                "severity",
                            ]
                            .contains(&key.as_str())
                        })
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect(),
                )
            })
            .collect::<Vec<_>>();
        let mut compact = present(&result, kind, false);
        compact["analysis"]
            .as_object_mut()
            .unwrap()
            .remove("elapsed_ms");
        let mut expected = case["expected"].clone();
        expected["compact"]["analysis"]
            .as_object_mut()
            .unwrap()
            .remove("elapsed_ms");
        let projected = json!({"complete":result["complete"],"rows":rows,"directories":result.get("directories").cloned().unwrap_or(json!([])),"compact":compact});
        assert_eq!(projected, expected, "{}", case["name"]);
    }
}
#[test]
fn explicit_cache_configuration_overrides_unused_invalid_values() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    let path = root.path().join(".ken/structural.json");
    std::fs::write(&path, r#"{"cache":{"max_mb":"0"}}"#).unwrap();
    let application = app(root.path());
    assert_eq!(application.cache_capacity(None).unwrap(), 0.);
    std::fs::write(&path, r#"{"cache":{"max_mb":"invalid"}}"#).unwrap();
    assert_eq!(application.cache_capacity(Some(12.)).unwrap(), 12.);
    assert!(application.cache_capacity(None).is_err());
    assert!(application.cache_capacity(Some(f64::NAN)).is_err());
}
