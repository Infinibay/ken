//! Source-only exploration lifecycle, separate from linked declaration/BODY sessions.
use ken_query::execution::Cancellation;
use ken_structural::application::{
    exploration::{ExplorationOptions, SyntaxExploration},
    modules::ModuleRegistry,
    sessions::{QueryApplication, QueryOptions, SessionOptions},
};
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
};
const CODE: &str =
    "if x == 3:\n pass\nif y != \"a\":\n pass\nif x == y:\n pass\nif 3 == x:\n pass\n";
fn query(body: &str, projection: &str) -> String {
    format!("language \"kql/2\";module syntax_source;query q{{{body} select {projection};}}")
}
fn grammars() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("native grammar fixture manifest"),
        ))
        .unwrap(),
    )
}
fn app(root: &Path, cache: Option<PathBuf>) -> SyntaxExploration {
    SyntaxExploration::new(root, grammars(), BTreeMap::new(), cache).unwrap()
}
fn report(app: &SyntaxExploration, source: &str, options: ExplorationOptions) -> Value {
    app.search(Some(source), options)
        .unwrap()
        .to_json()
        .unwrap()
}
#[test]
fn raw_structure_operators_and_captures_run_without_building_a_semantic_graph() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), CODE).unwrap();
    let text = query(
        "node $n {kind:\"if\";node $condition {kind:\"compare\";role:\"condition\";node $left {kind:\"identifier\";}node $right {kind:\"literal\";}}} where $condition.operator in [\"==\",\"!=\"];where $left.start_byte < $right.start_byte;",
        "$n.line,$left.name,$right.text",
    );
    let out = report(
        &app(d.path(), None),
        &text,
        ExplorationOptions {
            cache_mb: 0.,
            profile: true,
            ..Default::default()
        },
    );
    assert_eq!(out["rows"], json!([[1, "x", "3"], [3, "y", "\"a\""]]));
    assert_eq!(out["capability"], "syntax-exploration/1");
    assert_eq!(out["analysis"]["backend"], "native_syntax_exploration");
    assert_eq!(out["analysis"]["semantic_resolution"], "not_requested");
    assert_eq!(out["analysis"]["storage"], "native_preorder/1");
    assert_eq!(out["analysis"]["result_cache"], "disabled");
    assert!(
        !out["analysis"]["operator_profile"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn admitted_python_rust_and_typescript_agree_with_indexed_results_and_full_tree_walk() {
    for (name, source) in [
        ("a.py", "if x == 3:\n pass\nif y != \"a\":\n pass\n"),
        ("a.rs", "fn f(x:i32) { if x == 3 {} if y != \"a\" {} }"),
        ("a.ts", "if (x == 3) {} if (y != \"a\") {}"),
    ] {
        let d = tempfile::tempdir().unwrap();
        std::fs::write(d.path().join(name), source).unwrap();
        let q = query("node $n {kind:\"if\";}", "$n.start_byte,$n.end_byte");
        let a = app(d.path(), None);
        let fast = report(
            &a,
            &q,
            ExplorationOptions {
                cache_mb: 0.,
                ..Default::default()
            },
        );
        let slow = report(
            &a,
            &q,
            ExplorationOptions {
                cache_mb: 0.,
                reference: true,
                ..Default::default()
            },
        );
        let indexed = QueryApplication::new(d.path(), grammars(), BTreeMap::new()).unwrap();
        let mut s = indexed.open_transient(SessionOptions::default()).unwrap();
        let old = s
            .search(Some(&q), QueryOptions::default())
            .unwrap()
            .to_json()
            .unwrap();
        s.close().unwrap();
        assert_eq!(fast["rows"], old["rows"], "{name}");
        assert_eq!(fast["rows"], slow["rows"], "{name}");
        assert_eq!(fast["analysis"]["scanned_nodes"], 2);
        assert!(slow["analysis"]["scanned_nodes"].as_u64().unwrap() > 2);
    }
}
#[test]
fn unsupported_semantics_and_invalid_options_fail_before_scope_io_or_cache_creation() {
    let d = tempfile::tempdir().unwrap();
    let a = app(d.path(), None);
    for body in [
        "callable $n {}",
        "node $n {namespace:\"x\";}",
        "node $n {} node $m {} where same_symbol($n,$m);",
    ] {
        let err = a
            .search(
                Some(&query(body, "1")),
                ExplorationOptions {
                    path: "absent".into(),
                    ..Default::default()
                },
            )
            .unwrap_err()
            .to_string();
        assert!(
            err.contains("unsupported") || err.contains("exploration"),
            "{err}"
        );
        assert!(!err.contains("does not exist"), "{err}");
    }
    for options in [
        ExplorationOptions {
            cache_mb: f64::NAN,
            ..Default::default()
        },
        ExplorationOptions {
            max_file_bytes: 0,
            ..Default::default()
        },
        ExplorationOptions {
            max_states: Some(0),
            ..Default::default()
        },
    ] {
        assert!(a.search(Some(&query("", "1")), options).is_err());
    }
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn cold_and_warm_cache_observe_edits_deletion_and_explicit_source_scope() {
    let d = tempfile::tempdir().unwrap();
    let cache = tempfile::tempdir().unwrap();
    let a = app(d.path(), Some(cache.path().into()));
    let p = d.path().join("a.py");
    std::fs::write(&p, "if x: pass\n").unwrap();
    std::fs::write(d.path().join("b.py"), "if b: pass\n").unwrap();
    let q = query("node $n {kind:\"if\";}", "$n.path,$n.line");
    let first = report(&a, &q, Default::default());
    assert_eq!(first["analysis"]["parsed_units"], 2);
    let warm = report(&a, &q, Default::default());
    assert_eq!(warm["analysis"]["reused_units"], 2);
    assert_eq!(warm["analysis"]["parsed_units"], 0);
    std::fs::write(&p, "x=1\nif a: pass\nif b: pass\n").unwrap();
    let changed = report(&a, &q, Default::default());
    assert_eq!(changed["analysis"]["parsed_units"], 1);
    assert_eq!(
        changed["rows"],
        json!([["a.py", 2], ["a.py", 3], ["b.py", 1]])
    );
    let scoped = report(
        &a,
        &q,
        ExplorationOptions {
            source_paths: Some(vec!["b.py".into()]),
            ..Default::default()
        },
    );
    assert_eq!(scoped["rows"], json!([["b.py", 1]]));
    assert_eq!(scoped["source_scope"]["kind"], "explicit_files");
    std::fs::remove_file(p).unwrap();
    assert_eq!(
        report(&a, &q, Default::default())["rows"],
        json!([["b.py", 1]])
    );
    assert!(cache.path().join("syntax.sqlite").exists());
    assert!(!d.path().join(".ken").exists());
    assert_eq!(
        std::fs::read_dir(cache.path())
            .unwrap()
            .filter_map(Result::ok)
            .filter(|e| e.path().extension().is_some_and(|s| s == "sqlite"))
            .count(),
        1
    );
}
#[test]
fn cache_zero_and_subthreshold_retention_create_no_persistent_directory() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), "if x: pass\n").unwrap();
    let cache = d.path().join("external");
    let a = app(d.path(), Some(cache.clone()));
    for capacity in [0., 0.1] {
        let out = report(
            &a,
            &query("node $n {kind:\"if\";}", "$n.line"),
            ExplorationOptions {
                cache_mb: capacity,
                ..Default::default()
            },
        );
        assert_eq!(out["rows"], json!([[1]]));
        assert_eq!(out["analysis"]["ephemeral"], true);
        assert_eq!(out["analysis"]["retention_budget_bytes"], 0);
        assert!(!cache.exists());
    }
}
#[test]
fn retention_eviction_never_discards_live_query_units() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(
        d.path().join("a.py"),
        format!("#{}\nif x: pass\n", "x".repeat(650000)),
    )
    .unwrap();
    let out = report(
        &app(d.path(), None),
        &query("node $n {kind:\"if\";}", "$n.line"),
        ExplorationOptions {
            cache_mb: 0.6,
            ..Default::default()
        },
    );
    assert_eq!(out["rows"], json!([[2]]));
    assert_eq!(out["complete"], true);
    assert_eq!(out["analysis"]["evicted_units"], 1);
    assert!(out["analysis"]["allocated_bytes"].as_u64().unwrap() <= 600000);
}
#[test]
fn parse_error_reuse_and_skipped_frontends_keep_global_absence_uncertain_but_close_valid_subtrees()
{
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), "def good():\n return 1\n").unwrap();
    std::fs::write(d.path().join("broken.py"), "if x == :\n pass\n").unwrap();
    std::fs::write(d.path().join("unknown.swift"), "let x=1\n").unwrap();
    let a = app(d.path(), None);
    for _ in 0..2 {
        let global = report(
            &a,
            &query("not exists {node $n {kind:\"yield\";}}", "1"),
            Default::default(),
        );
        assert_eq!(global["coverage_complete"], false);
        assert_eq!(global["rows"], json!([]));
        assert!(global["unknown_candidates"].as_u64().unwrap() > 0);
        let skipped = global["analysis"]["skipped"].as_array().unwrap();
        assert!(skipped.iter().any(|s| s["reason"] == "parse_error"));
        assert!(
            skipped
                .iter()
                .any(|s| s["reason"] == "unsupported_frontend")
        );
        let local = report(
            &a,
            &query(
                "node $n {kind:\"return\";} not exists {node $c {kind:\"call\";} where contains($n,$c);}",
                "$n.line",
            ),
            Default::default(),
        );
        assert_eq!(local["rows"], json!([[2]]));
        assert_eq!(local["unknown_candidates"], 0);
    }
}
#[test]
fn raw_literal_types_preserve_hex_and_exponent_spelling() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(
        d.path().join("a.ts"),
        "const a = 1e3; const b = 0xdead; const c = 1.5;\n",
    )
    .unwrap();
    let out = report(
        &app(d.path(), None),
        &query("node $n {kind:\"literal\";}", "$n.text,$n.type_kind"),
        ExplorationOptions {
            cache_mb: 0.,
            ..Default::default()
        },
    );
    assert_eq!(
        out["rows"],
        json!([["1e3", "float"], ["0xdead", "int"], ["1.5", "float"]])
    );
}
#[test]
fn saved_modules_and_explicit_libraries_use_the_native_resolver_without_semantic_preparation() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), "if x: pass\n").unwrap();
    let registry = ModuleRegistry::new(d.path()).unwrap();
    let library = "language \"kql/2\";module syntax_lib;pattern Pick(out CodeNode $n){node $n {kind:\"if\";}}";
    registry.save_at(library, None, None, 1).unwrap();
    let source = "language \"kql/2\";module syntax_saved;import syntax_lib;query chosen {use syntax_lib.Pick(n:$n);select $n.line;}";
    registry.save_at(source, None, None, 2).unwrap();
    let a = app(d.path(), None);
    let found = a
        .search(
            None,
            ExplorationOptions {
                saved_query: Some("syntax_saved".into()),
                query_name: Some("chosen".into()),
                cache_mb: 0.,
                ..Default::default()
            },
        )
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(found["rows"], json!([[1]]));
    let absent = library.replace("kind:\"if\"", "kind:\"while\"");
    let out = a
        .search(
            None,
            ExplorationOptions {
                saved_query: Some("syntax_saved".into()),
                libraries: Some(BTreeMap::from([("syntax_lib".into(), absent)])),
                cache_mb: 0.,
                ..Default::default()
            },
        )
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(out["rows"], json!([]));
    assert!(!d.path().join(".ken/structural").exists());
}
#[test]
fn whole_request_controls_and_partial_limits_do_not_poison_reused_units() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), "if x: pass\nif y: pass\n").unwrap();
    let a = app(d.path(), None);
    let q = query("node $n {kind:\"if\";}", "$n.line");
    let cancellation = Cancellation::default();
    cancellation.cancel();
    for (options, reason) in [
        (
            ExplorationOptions {
                timeout_ms: Some(0.),
                ..Default::default()
            },
            "timeout",
        ),
        (
            ExplorationOptions {
                cancellation,
                ..Default::default()
            },
            "cancelled",
        ),
        (
            ExplorationOptions {
                max_states: Some(1),
                ..Default::default()
            },
            "max_states",
        ),
        (
            ExplorationOptions {
                max_rows: Some(1),
                ..Default::default()
            },
            "max_rows",
        ),
    ] {
        let stopped = report(&a, &q, options);
        assert_eq!(stopped["complete"], false);
        assert_eq!(stopped["reason"], reason);
        assert_eq!(
            report(&a, &q, Default::default())["rows"],
            json!([[1], [2]])
        );
    }
}
#[test]
fn public_json_transport_preserves_big_integers_and_lone_surrogates() {
    let d = tempfile::tempdir().unwrap();
    let a = app(d.path(), None);
    let q = query("", "123456789012345678901234567890,\"\\ud800\"");
    let out = a
        .search(
            Some(&q),
            ExplorationOptions {
                cache_mb: 0.,
                ..Default::default()
            },
        )
        .unwrap();
    assert!(out.to_json().is_err());
    let encoded = a
        .search_json(
            Some(&q),
            ExplorationOptions {
                cache_mb: 0.,
                ..Default::default()
            },
        )
        .unwrap();
    assert!(encoded.contains("123456789012345678901234567890"));
    assert!(encoded.contains("\\ud800"));
}
