use ken_maintenance::{BenchDataset, BenchObservation, BenchOptions, BenchRunner, benchmark};
use ken_text::PythonText;
use serde_json::{Value, json};
use std::{collections::BTreeMap, io::Read};
struct Runner;
impl BenchRunner for Runner {
    fn evaluate(
        &mut self,
        prompt: &PythonText,
        top: usize,
        max_chars: Option<i64>,
    ) -> ken_maintenance::Result<BenchObservation> {
        assert_eq!(prompt, &"locate a".into());
        assert_eq!(top, 2);
        assert_eq!(max_chars, Some(100));
        Ok(BenchObservation {
            ranked: vec![
                ken_context::RankedItem::file("src/b.py", 2., "second"),
                ken_context::RankedItem::file("src/a.py", 1., "first"),
            ],
            visible_files: vec!["src/b.py".into()],
            block: "12345".into(),
            timings_ms: BTreeMap::from([
                ("embed".into(), 1.),
                ("rank".into(), 2.),
                ("render".into(), 3.),
                ("e2e".into(), 6.),
            ]),
        })
    }
}
fn dataset() -> BenchDataset {
    BenchDataset::from_jsonl("{\"prompt\":\"  locate a  \",\"expected_files\":[\"src/a.py\",\"src/b.py\"],\"judgments\":{\"src/a.py\":3,\"src/b.py\":1,\"irrelevant\":0}}\n").unwrap()
}
#[test]
fn original_dataset_and_graded_metric_match_and_visible_exposure_has_separate_gate() {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(&include_bytes!("fixtures/maintenance-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    let original: Value = serde_json::from_str(&raw).unwrap();
    let cases = dataset();
    assert_eq!(
        serde_json::to_value(&cases.cases).unwrap(),
        original["bench"]["cases"]
    );
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    let root = tempfile::tempdir().unwrap();
    let report = benchmark(
        &conn,
        root.path(),
        &cases,
        &BenchOptions {
            top: 2,
            max_chars: Some(100),
            verify_index: false,
            explain_misses: true,
            fail_under_case_recall: Some(1.),
            fail_under_expected_file_recall: Some(1.),
        },
        &mut Runner,
    )
    .unwrap();
    let report = serde_json::to_value(report).unwrap();
    assert_eq!(report["ndcg"], original["bench"]["ndcg"]);
    assert_eq!(report["ok"], true);
    assert_eq!(report["case_recall"], 1.);
    assert_eq!(report["expected_file_recall"], 1.);
    assert_eq!(report["visible_case_recall"], 1.);
    assert_eq!(report["visible_expected_file_recall"], 0.5);
    assert_eq!(report["mrr"], 1.);
    assert_eq!(report["avg_context_chars"], 5.);
    assert_eq!(report["avg_context_est_tokens"], 2.);
    assert_eq!(report["avg_timings_ms"]["rank"], 2.);
}
#[test]
fn dataset_rejects_ambiguous_or_invalid_ground_truth() {
    for row in [
        json!([]),
        json!({"prompt":" ","expected_files":["a"]}),
        json!({"prompt":"x","expected_files":[]}),
        json!({"prompt":"x","expected_files":["a","a"]}),
        json!({"prompt":"x","expected_files":["a"],"judgments":{"b":1}}),
        json!({"prompt":"x","expected_files":["a"],"judgments":{"a":true}}),
        json!({"prompt":"x","expected_files":["a"],"judgments":{"a":4}}),
    ] {
        assert!(BenchDataset::from_jsonl(&row.to_string()).is_err(), "{row}");
    }
    assert!(BenchDataset::from_jsonl("# header\n\n").is_err());
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    let root = tempfile::tempdir().unwrap();
    assert!(
        benchmark(
            &conn,
            root.path(),
            &dataset(),
            &BenchOptions {
                top: 0,
                verify_index: false,
                ..Default::default()
            },
            &mut Runner
        )
        .is_err()
    );
}
#[test]
fn copied_index_is_rejected_for_stale_or_escaping_source_before_model_work() {
    struct Never;
    impl BenchRunner for Never {
        fn evaluate(
            &mut self,
            _: &PythonText,
            _: usize,
            _: Option<i64>,
        ) -> ken_maintenance::Result<BenchObservation> {
            panic!("incompatible index reached model")
        }
    }
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("CREATE TABLE ci_files(path TEXT,content_hash BLOB)")
        .unwrap();
    let root = tempfile::tempdir().unwrap();
    let cases = dataset();
    assert!(benchmark(&conn, root.path(), &cases, &Default::default(), &mut Never).is_err());
    std::fs::write(root.path().join("a.py"), "new source").unwrap();
    for path in ["a.py", "../outside.py"] {
        conn.execute("DELETE FROM ci_files", []).unwrap();
        conn.execute(
            "INSERT INTO ci_files VALUES(?1,?2)",
            rusqlite::params![path, vec![0u8; 32]],
        )
        .unwrap();
        assert!(benchmark(&conn, root.path(), &cases, &Default::default(), &mut Never).is_err());
    }
}
#[test]
fn empty_rankings_score_zero_and_threshold_failure_remains_a_report() {
    struct Empty;
    impl BenchRunner for Empty {
        fn evaluate(
            &mut self,
            _: &PythonText,
            _: usize,
            _: Option<i64>,
        ) -> ken_maintenance::Result<BenchObservation> {
            Ok(BenchObservation::default())
        }
    }
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    let root = tempfile::tempdir().unwrap();
    let report = serde_json::to_value(
        benchmark(
            &conn,
            root.path(),
            &dataset(),
            &BenchOptions {
                verify_index: false,
                fail_under_case_recall: Some(0.5),
                ..Default::default()
            },
            &mut Empty,
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(report["ok"], false);
    for key in [
        "case_recall",
        "expected_file_recall",
        "mrr",
        "ndcg",
        "visible_case_recall",
    ] {
        assert_eq!(report[key], 0., "{key}");
    }
    assert_eq!(report["failures"].as_array().unwrap().len(), 1);
}
#[test]
fn native_context_benchmark_adapter_uses_actual_rank_and_budget_renderer() {
    use ken_core::project::{DiscoveryContext, ProjectPaths};
    use ken_retrieval::query_encoder::QueryEncoder;
    struct Query;
    impl QueryEncoder for Query {
        fn embed_query(&self, _: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
            Ok(vec![1., 0.])
        }
    }
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("src")).unwrap();
    std::fs::write(root.path().join("src/a.py"), "def current(): return 42\n").unwrap();
    let paths = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut store = ken_store::ProjectStore::open(&paths).unwrap();
    store.initialize().unwrap();
    store
        .database()
        .connection()
        .execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES('src/a.py',x'',0,0)",
            [],
        )
        .unwrap();
    let mut numerics = ken_context::NativeNumerics::default();
    let mut runner = ken_maintenance::ContextBenchRunner::new(
        store.database().connection(),
        root.path(),
        &Query,
        &mut numerics,
        ken_context::Policy::default(),
        ken_context::Clock {
            now_ms: 0,
            now_ns: 0,
        },
    );
    let result = runner.evaluate(&"src/a.py".into(), 8, Some(1000)).unwrap();
    assert!(
        result
            .ranked
            .iter()
            .any(|item| item.target == "src/a.py".into())
    );
    assert_eq!(
        result.visible_files,
        ken_context::visible_file_paths(&result.block)
    );
    assert!(result.block.codepoints().len() <= 1000);
    assert!(result.timings_ms["e2e"] >= result.timings_ms["embed"]);
}
#[test]
fn matching_live_source_index_reaches_benchmark_after_provenance_validation() {
    use blake2::digest::{Update, VariableOutput};
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join("src")).unwrap();
    let bytes = b"def current(): return 42\n";
    std::fs::write(root.path().join("src/a.py"), bytes).unwrap();
    let mut hash = blake2::Blake2bVar::new(32).unwrap();
    hash.update(bytes);
    let mut expected = [0; 32];
    hash.finalize_variable(&mut expected).unwrap();
    let conn = rusqlite::Connection::open_in_memory().unwrap();
    conn.execute_batch("CREATE TABLE ci_files(path TEXT,content_hash BLOB)")
        .unwrap();
    conn.execute(
        "INSERT INTO ci_files VALUES('src/a.py',?1)",
        [expected.to_vec()],
    )
    .unwrap();
    let report = benchmark(
        &conn,
        root.path(),
        &dataset(),
        &BenchOptions {
            top: 2,
            max_chars: Some(100),
            ..Default::default()
        },
        &mut Runner,
    )
    .unwrap();
    assert!(report.ok);
    assert_eq!(report.cases, 1);
}
