//! Same semantic catalog, two real physical readers; no syntax-only reinterpretation.
use ken_query::execution::{Cancellation, QueryBudget};
use ken_structural::application::{
    exploration::{PatternBackend, PatternOptions},
    search::{SearchOptions, StructuralApplication},
};
use ken_syntax::GrammarCatalog;
use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
fn app(root: &Path, cache: Option<PathBuf>) -> StructuralApplication {
    let catalog = Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    StructuralApplication::new_with_cache_directory(root, catalog, cache).unwrap()
}
fn options(backend: PatternBackend, profile: bool) -> PatternOptions {
    PatternOptions {
        search: SearchOptions::default(),
        backend,
        profile,
    }
}
fn run(app: &StructuralApplication, backend: PatternBackend, profile: bool) -> Value {
    app.patterns_with_options(&["singleton".into()], options(backend, profile))
        .unwrap()
}
fn semantic(value: &Value) -> Value {
    let mut v = value.clone();
    if let Some(items) = v.get_mut("findings").and_then(Value::as_array_mut) {
        for item in items {
            if let Some(map) = item.as_object_mut() {
                map.remove("stats");
            }
        }
    }
    serde_json::json!({"findings":v["findings"],"complete":v["complete"],"incomplete":v["incomplete"]})
}
#[test]
fn native_buckets_and_indexed_reader_preserve_the_same_full_semantic_evidence() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(
        d.path().join("Subject.java"),
        include_str!("fixtures/exploration/singleton.java"),
    )
    .unwrap();
    let a = app(d.path(), None);
    let indexed = run(&a, PatternBackend::Indexed, true);
    let explored = run(&a, PatternBackend::Exploration, true);
    assert!(!indexed["findings"].as_array().unwrap().is_empty());
    assert_eq!(semantic(&explored), semantic(&indexed));
    assert_eq!(
        explored["analysis"]["pattern_engine"]["backend"],
        "exploration"
    );
    assert_eq!(
        explored["analysis"]["pattern_engine"]["storage"],
        "native_buckets/1"
    );
    assert_eq!(indexed["analysis"]["pattern_engine"]["backend"], "indexed");
    assert!(indexed["analysis"]["pattern_engine"]["buckets"].is_null());
    assert!(
        explored["analysis"]["pattern_engine"]["buckets"]["builds"]
            .as_u64()
            .unwrap()
            > 0
    );
}
#[test]
fn profile_bypasses_result_cache_and_reuses_real_retained_buckets() {
    let d = tempfile::tempdir().unwrap();
    let cache = tempfile::tempdir().unwrap();
    std::fs::write(
        d.path().join("Subject.java"),
        include_str!("fixtures/exploration/singleton.java"),
    )
    .unwrap();
    let a = app(d.path(), Some(cache.path().into()));
    let cold = run(&a, PatternBackend::Exploration, true);
    let warm = run(&a, PatternBackend::Exploration, true);
    assert_eq!(semantic(&cold), semantic(&warm));
    assert_eq!(cold["analysis"]["query_cache"]["hits"], 0);
    assert_eq!(warm["analysis"]["query_cache"]["hits"], 0);
    assert!(
        warm["analysis"]["pattern_engine"]["buckets"]["disk_hits"]
            .as_u64()
            .unwrap()
            > 0
    );
    assert!(cache.path().join("pattern-buckets.sqlite").exists());
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn cache_zero_retains_no_source_results_or_bucket_sqlite_files() {
    let d = tempfile::tempdir().unwrap();
    let cache = d.path().join("external");
    std::fs::write(d.path().join("a.py"), "def f():\n return 1\n").unwrap();
    let a = app(d.path(), Some(cache.clone()));
    let out = a
        .patterns_with_options(
            &["singleton".into()],
            PatternOptions {
                search: SearchOptions {
                    cache_mb: Some(0.),
                    ..Default::default()
                },
                backend: PatternBackend::Exploration,
                profile: true,
            },
        )
        .unwrap();
    assert_eq!(out["analysis"]["query_index"]["persistent"], false);
    assert_eq!(out["analysis"]["pattern_engine"]["backend"], "exploration");
    assert!(!cache.exists());
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn source_changes_invalidate_both_the_semantic_result_and_bucket_revision() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("Subject.java");
    std::fs::write(&p, include_str!("fixtures/exploration/singleton.java")).unwrap();
    let a = app(d.path(), None);
    let first = run(&a, PatternBackend::Exploration, true);
    std::fs::write(&p, "class Empty {}\n").unwrap();
    let changed = run(&a, PatternBackend::Exploration, true);
    let indexed = run(&a, PatternBackend::Indexed, true);
    assert_ne!(
        first["analysis"]["graph_key"],
        changed["analysis"]["graph_key"]
    );
    assert_eq!(
        changed["analysis"]["pattern_engine"]["buckets"]["disk_hits"],
        0
    );
    assert_eq!(semantic(&changed), semantic(&indexed));
}
#[test]
fn cancellation_and_limits_still_belong_to_the_shared_semantic_executor() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(
        d.path().join("Subject.java"),
        include_str!("fixtures/exploration/singleton.java"),
    )
    .unwrap();
    let a = app(d.path(), None);
    let cancel = Cancellation::default();
    cancel.cancel();
    let stopped = a.patterns_with_options(
        &["singleton".into()],
        PatternOptions {
            search: SearchOptions {
                cancellation: cancel,
                budget: QueryBudget {
                    max_states: Some(1),
                    ..Default::default()
                },
                cache_mb: Some(0.),
                ..Default::default()
            },
            backend: PatternBackend::Exploration,
            profile: true,
        },
    );
    match stopped {
        Ok(value) => assert_eq!(value["complete"], false),
        Err(e) => assert!(e.to_string().contains("cancel")),
    }
    assert!(!d.path().join(".ken").exists());
    assert_eq!(run(&a, PatternBackend::Exploration, true)["complete"], true);
}
#[test]
fn default_patterns_wrapper_selects_the_exploration_backend() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("a.py"), "def f():\n return 1\n").unwrap();
    let a = app(d.path(), None);
    let out = a
        .patterns(
            &["singleton".into()],
            SearchOptions {
                cache_mb: Some(0.),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(out["analysis"]["pattern_engine"]["backend"], "exploration");
}
