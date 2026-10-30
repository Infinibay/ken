use ken_knowledge::findings::ScalarMath;
use ken_knowledge::{arithmetic, context, dependencies, findings, reasoning, records};
use rusqlite::Connection;
use serde_json::{Value, json};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/domain.json")).unwrap()
}
fn project() -> tempfile::TempDir {
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join("src")).unwrap();
    std::fs::write(d.path().join("src/cache.py"), "KEY = 1\n").unwrap();
    std::fs::write(d.path().join("src/other.py"), "OTHER = 2\n").unwrap();
    d
}
fn atom(p: &str, s: &str, o: &str) -> Value {
    json!({"predicate":p,"subject":s,"object":o})
}
#[test]
fn frozen_reasoning_trace_matches_and_checkpoints_resume() {
    let f = fixture();
    let db = Connection::open_in_memory().unwrap();
    reasoning::ensure_schema(&db).unwrap();
    for (op, expected) in f["reasoning"]["operations"]
        .as_array()
        .unwrap()
        .iter()
        .zip(f["reasoning"]["results"].as_array().unwrap())
    {
        let actual = if op["op"] == "record" {
            reasoning::record(&db, op).unwrap()
        } else {
            reasoning::ask(&db, op).unwrap()
        };
        assert_eq!(&actual, expected, "operation {op}");
    }
}
#[test]
fn interrupted_join_restarts_without_extra_work_or_assumption_leaks() {
    let full = Connection::open_in_memory().unwrap();
    let resumed = Connection::open_in_memory().unwrap();
    let input = json!({"source":"doc","facts":[atom("p","a","b"),atom("q","b","c"),atom("p","c","d")],"rules":[{"body":[atom("p","?x","?y"),atom("q","?y","?z"),atom("p","?z","?w")],"head":atom("joined","?x","?w")}]});
    for db in [&full, &resumed] {
        reasoning::ensure_schema(db).unwrap();
        reasoning::record(db, &input).unwrap();
    }
    let goal = atom("joined", "?x", "?y");
    let expected = reasoning::ask(&full, &json!({"goal":goal,"budget":10000})).unwrap();
    let mut got = Value::Null;
    for _ in 0..500 {
        got = reasoning::ask(&resumed, &json!({"goal":goal,"budget":1})).unwrap();
        if got["metrics"]["complete"] == true {
            break;
        }
    }
    assert_eq!(got["answers"], expected["answers"]);
    assert_eq!(
        got["metrics"]["total_work"],
        expected["metrics"]["total_work"]
    );
    assert_eq!(
        reasoning::ask(
            &resumed,
            &json!({"goal":atom("absent","a","b"),"assumptions":[atom("absent","a","b")]})
        )
        .unwrap()["status"],
        "supported"
    );
    assert_eq!(
        reasoning::ask(&resumed, &json!({"goal":atom("absent","a","b")})).unwrap()["status"],
        "unknown"
    );
}
#[test]
fn exact_arithmetic_matches_frozen_acceptance_and_rejection() {
    for c in fixture()["arithmetic"].as_array().unwrap() {
        let result = arithmetic::calculate(c["expression"].as_str().unwrap());
        if c.get("result").is_some() {
            assert_eq!(result.unwrap(), c["result"]);
        } else {
            assert!(result.is_err(), "{c}");
        }
    }
}
#[test]
fn declared_inputs_and_context_match_frozen_contract() {
    let f = fixture();
    let d = project();
    let spec = json!({"kind":"decision","rationale":" Keep scope. ","evidence":[{"path":"src/cache.py","note":"Observation"}],"dependencies":[{"kind":"tree","path":"src","pattern":"*.py"}],"assumptions":["Configuration matches."],"recheck":"Check again."});
    let just = records::prepare(&spec, Some(d.path()), &[]).unwrap();
    assert_eq!(just, f["justification"]);
    let live = dependencies::assess(
        &just["dependencies"],
        Some(d.path()),
        dependencies::Budget::default(),
    );
    assert_eq!(live, f["validity"]);
    let hit = json!({"topic":"cache identity","content":"Include rules in the cache key.","justification":just,"validity":live});
    assert_eq!(context::summary(&hit), f["contexts"]["summary"]);
    assert_eq!(context::answer(&hit), f["contexts"]["answer"]);
    assert_eq!(
        context::compact(std::slice::from_ref(&hit), 1000, "answer").unwrap(),
        f["contexts"]["compact"]
    );
    assert_eq!(context::brief_line(&hit, 450), f["contexts"]["brief"]);
    std::fs::write(d.path().join("src/new.py"), "NEW=3").unwrap();
    assert_eq!(
        dependencies::assess(
            &just["dependencies"],
            Some(d.path()),
            dependencies::Budget::default()
        ),
        f["stale"]
    );
    assert_eq!(
        dependencies::assess(
            &just["dependencies"],
            Some(d.path()),
            dependencies::Budget {
                max_files: 0,
                ..Default::default()
            }
        )["state"],
        "unknown"
    );
    let mut long = hit;
    long["content"] = json!("Never omit the caveat. ".repeat(500));
    assert_eq!(
        context::compact(&[long], 500, "answer").unwrap(),
        f["contexts"]["omitted"]
    );
    assert!(
        records::prepare(
            &json!({"rationale":"why","dependencies":[{"path":"../outside"}]}),
            Some(d.path()),
            &[]
        )
        .is_err()
    );
    assert!(
        records::prepare(
            &json!({"rationale":"why","check_runs":["run"]}),
            Some(d.path()),
            &[]
        )
        .is_err()
    );
}
fn graph_db() -> Connection {
    let db = Connection::open_in_memory().unwrap();
    db.execute_batch("PRAGMA foreign_keys=ON;CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE ci_files(id INTEGER PRIMARY KEY,path TEXT);CREATE TABLE ci_symbols(id INTEGER PRIMARY KEY,file_id INTEGER,name TEXT,qualname TEXT);INSERT INTO ci_files VALUES(1,'src/cache.py'),(2,'src/other.py');INSERT INTO ci_symbols VALUES(1,1,'CacheEntry','CacheEntry');").unwrap();
    findings::ensure_schema(&db).unwrap();
    db
}
#[test]
fn findings_persist_anchors_graph_and_plain_overwrite_revokes_justification() {
    let db = graph_db();
    let f = fixture();
    for (topic, content, tags, now) in [
        (
            "cache",
            "src/cache.py CacheEntry",
            json!(["cache", "kind:finding"]),
            1000,
        ),
        ("reuse", "src/cache.py", json!(["cache", "reuse"]), 1001),
    ] {
        findings::remember(
            &db,
            &json!({"topic":topic,"content":content,"tags":tags}),
            None,
            now,
            None,
            &[],
            &ScalarMath,
        )
        .unwrap();
    }
    assert_eq!(
        findings::extract_refs(&db, "src/cache.py:42 `CacheEntry` missing.rs").unwrap(),
        f["graph"]["refs"]
    );
    findings::set_anchors(
        &db,
        1,
        &json!({"file":"src/cache.py","error":"database is locked"}),
        1000,
    )
    .unwrap();
    assert_eq!(
        json!(
            findings::by_anchor(
                &db,
                &json!({"error":"Error: database is locked on open"}),
                3
            )
            .unwrap()
        ),
        f["graph"]["anchor"]
    );
    assert_eq!(
        findings::related(&db, "cache", 8, 0.3, None, &ScalarMath).unwrap(),
        f["graph"]["related"]
    );
    assert_eq!(
        findings::for_file(&db, "src/cache.py", true, 15, None).unwrap(),
        f["graph"]["file"]
    );
    findings::remember(
        &db,
        &json!({"topic":"proof","content":"first","justification":{"rationale":"why"}}),
        None,
        1002,
        None,
        &[],
        &ScalarMath,
    )
    .unwrap();
    assert!(
        findings::list(&db, 20, None, None, &[])
            .unwrap()
            .iter()
            .any(|x| x.get("justification").is_some())
    );
    findings::remember(
        &db,
        &json!({"topic":"proof","content":"replacement"}),
        None,
        1003,
        None,
        &[],
        &ScalarMath,
    )
    .unwrap();
    assert!(
        findings::list(&db, 20, None, None, &[])
            .unwrap()
            .iter()
            .find(|x| x["topic"] == "proof")
            .unwrap()
            .get("justification")
            .is_none()
    );
    assert_eq!(
        findings::forget(&db, "proof", 1004, &ScalarMath).unwrap()["deleted"],
        1
    );
}
#[test]
fn session_delivery_repeats_only_changed_validity() {
    let f = fixture();
    let mut seen = std::collections::BTreeMap::new();
    let hit = json!({"topic":"cache identity","content":"Include rules in the cache key.","justification":f["justification"],"validity":f["validity"]});
    assert!(!context::render_brief(std::slice::from_ref(&hit), 1100, &mut seen).is_empty());
    assert!(context::render_brief(std::slice::from_ref(&hit), 1100, &mut seen).is_empty());
    let mut changed = hit;
    changed["validity"] = f["stale"].clone();
    assert!(context::render_brief(&[changed], 1100, &mut seen).contains("REVISAR"));
}
#[test]
fn reasoning_rejects_invalid_replacements_without_destroying_old_sources() {
    let db = Connection::open_in_memory().unwrap();
    reasoning::ensure_schema(&db).unwrap();
    reasoning::record(&db, &json!({"source":"a","facts":[atom("p","x","yes")]})).unwrap();
    assert!(
        reasoning::record(&db, &json!({"source":"a","facts":[atom("bad","?x","yes")]})).is_err()
    );
    assert_eq!(
        reasoning::ask(&db, &json!({"goal":atom("p","x","yes")})).unwrap()["status"],
        "supported"
    );
    assert_eq!(
        reasoning::record(&db, &json!({"source":"a","facts":[atom("p","x","yes")]})).unwrap()["changed"],
        false
    );
    assert!(
        reasoning::record(
            &db,
            &json!({"source":"@builtin","facts":[atom("p","x","yes")]})
        )
        .is_err()
    );
    assert!(reasoning::record(&db,&json!({"source":"b","rules":[{"body":[atom("p","?x","yes")],"head":atom("q","?other","yes")}]})).is_err());
}
#[cfg(unix)]
#[test]
fn fingerprints_reject_symlinks_and_preserve_unknown() {
    let d = project();
    std::os::unix::fs::symlink(d.path().join("src/cache.py"), d.path().join("alias.py")).unwrap();
    assert!(dependencies::capture(&json!([{"path":"alias.py"}]), d.path()).is_err());
    let expected = dependencies::capture(&json!([{"kind":"tree","path":"src"}]), d.path()).unwrap();
    std::os::unix::fs::symlink(d.path().join("src"), d.path().join("src/alias")).unwrap();
    assert_eq!(
        dependencies::assess(&expected, Some(d.path()), dependencies::Budget::default())["state"],
        "unknown"
    );
}
#[test]
fn tree_receipt_hash_uses_legacy_ascii_json_for_unicode_names() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("caché.py"), "KEY = 1\n").unwrap();
    let captured = dependencies::capture(
        &json!([{"kind":"tree","path":".","pattern":"*.py"}]),
        d.path(),
    )
    .unwrap();
    // Legacy tree receipt serializes filenames with json.dumps ensure_ascii=True.
    assert_eq!(
        captured[0]["sha256"],
        "c9e650afd8980d440743deaaf4315d48786f6ac90a401e91025d70e2bc565c45"
    );
    assert_eq!(captured[0]["path"], ".");
}
#[test]
fn recall_handles_tiny_vectors_and_reports_all_stale_dimensions() {
    let db = graph_db();
    findings::remember(
        &db,
        &json!({"topic":"tiny","content":"Tiny is nonzero."}),
        Some(&[1e-13, 0.0]),
        0,
        None,
        &[],
        &ScalarMath,
    )
    .unwrap();
    let hits =
        findings::recall(&db, &[1e-13, 0.0], 5, Some(0.001), None, &[], &ScalarMath).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0]["score"], 0.008);
    let err = findings::recall(&db, &[1.0, 0.0, 0.0], 5, None, None, &[], &ScalarMath).unwrap_err();
    assert!(err.to_string().contains("ken reembed"));
    findings::remember(
        &db,
        &json!({"topic":"current","content":"Current generation."}),
        Some(&[1.0, 0.0, 0.0]),
        1,
        None,
        &[],
        &ScalarMath,
    )
    .unwrap();
    let current =
        findings::recall(&db, &[1.0, 0.0, 0.0], 5, Some(0.25), None, &[], &ScalarMath).unwrap();
    assert_eq!(current.len(), 1);
    assert_eq!(current[0]["topic"], "current");
}
#[test]
fn numerical_runtime_failure_remains_explicit_and_does_not_lose_finding() {
    struct Unavailable;
    impl findings::VectorMath for Unavailable {
        fn query_norm(&self, _: &[f32]) -> ken_knowledge::Result<f32> {
            Err(ken_knowledge::Error::Invalid(
                "numerical runtime unavailable".into(),
            ))
        }
        fn row_norm(&self, _: &[f32]) -> ken_knowledge::Result<f32> {
            Err(ken_knowledge::Error::Invalid(
                "numerical runtime unavailable".into(),
            ))
        }
        fn scores(&self, _: &[f32], _: usize, _: &[f32]) -> ken_knowledge::Result<Vec<f32>> {
            Err(ken_knowledge::Error::Invalid(
                "numerical runtime unavailable".into(),
            ))
        }
        fn symmetric_product(
            &self,
            _: &[f32],
            _: usize,
            _: usize,
        ) -> ken_knowledge::Result<Vec<f32>> {
            Err(ken_knowledge::Error::Invalid(
                "numerical runtime unavailable".into(),
            ))
        }
    }
    let db = graph_db();
    findings::remember(
        &db,
        &json!({"topic":"one","content":"Preserve finding."}),
        Some(&[1., 0.]),
        0,
        None,
        &[],
        &Unavailable,
    )
    .unwrap();
    assert!(findings::recall(&db, &[1., 0.], 5, Some(0.25), None, &[], &Unavailable).is_err());
    let saved = findings::remember(
        &db,
        &json!({"topic":"two","content":"Graph failure never loses content."}),
        Some(&[1., 0.]),
        1,
        None,
        &[],
        &Unavailable,
    )
    .unwrap();
    assert_eq!(saved["ok"], true);
    assert_eq!(findings::list(&db, 20, None, None, &[]).unwrap().len(), 2);
}
#[test]
fn existing_python_checkpoint_reopens_without_new_inference() {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/reasoning-checkpoint.json")).unwrap();
    let db = Connection::open_in_memory().unwrap();
    reasoning::ensure_schema(&db).unwrap();
    for r in fixture["contexts"].as_array().unwrap() {
        db.execute(
            "INSERT INTO contexts VALUES(?,?)",
            rusqlite::params![r[0].as_str(), r[1].as_i64()],
        )
        .unwrap();
    }
    for r in fixture["sources"].as_array().unwrap() {
        db.execute(
            "INSERT INTO sources VALUES(?,?,?)",
            rusqlite::params![r[0].as_str(), r[1].as_str(), r[2].as_str()],
        )
        .unwrap();
    }
    for r in fixture["checkpoints"].as_array().unwrap() {
        db.execute(
            "INSERT INTO checkpoints VALUES(?,?,?,?)",
            rusqlite::params![r[0].as_str(), r[1].as_str(), r[2].as_str(), r[3].as_str()],
        )
        .unwrap();
    }
    let reply = reasoning::ask(&db, &json!({"goal":atom("different","x","yes")})).unwrap();
    assert_eq!(reply["status"], "supported");
    assert_eq!(reply["metrics"]["work"], 0);
    assert_eq!(reply["reuse"]["checkpoint"], true);
}
#[test]
fn enriched_batch_shares_one_dependency_budget_and_cache() {
    let d = tempfile::tempdir().unwrap();
    let db = graph_db();
    for group in 0..9 {
        let mut deps = Vec::new();
        for index in 0..32 {
            let path = format!("source-{}.txt", group * 32 + index);
            std::fs::write(d.path().join(&path), "evidence").unwrap();
            deps.push(json!({"path":path}));
        }
        let saved=findings::remember(&db,&json!({"topic":format!("note-{group}"),"content":"Recorded conclusion.","justification":{"rationale":"Declared inputs only.","dependencies":deps}}),None,group,Some(d.path()),&[],&ScalarMath).unwrap();
        assert_eq!(saved["ok"], true);
    }
    let hits = findings::list(&db, 20, None, Some(d.path()), &[]).unwrap();
    assert_eq!(hits.len(), 9);
    assert!(hits.iter().any(|h| h["validity"]["state"] == "unknown"));
    let deps = dependencies::capture(&json!([{"path":"source-0.txt"}]), d.path()).unwrap();
    let mut fp = dependencies::Fingerprints::new(
        d.path(),
        dependencies::Budget {
            max_files: 1,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(
        dependencies::assess_with_fingerprints(&deps, Some(&mut fp))["state"],
        "unchanged"
    );
    assert_eq!(
        dependencies::assess_with_fingerprints(&deps, Some(&mut fp))["state"],
        "unchanged"
    );
}

#[cfg(unix)]
#[test]
fn tree_wildcards_cover_newlines_and_literal_patterns_match_whole_names() {
    let d = tempfile::tempdir().unwrap();
    let path = d.path().join("a\nb.py");
    for pattern in ["*", "*.py", "a?b.py"] {
        std::fs::write(&path, "before").unwrap();
        let receipt = dependencies::capture(
            &json!([{"kind":"tree","path":".","pattern":pattern}]),
            d.path(),
        )
        .unwrap();
        std::fs::write(&path, "after").unwrap();
        assert_eq!(
            dependencies::assess(&receipt, Some(d.path()), dependencies::Budget::default())["state"],
            "stale",
            "pattern {pattern:?} omitted a newline filename"
        );
    }
    std::fs::write(d.path().join("exact.py"), "tracked").unwrap();
    std::fs::write(d.path().join("exact.py\n"), "before").unwrap();
    let receipt = dependencies::capture(
        &json!([{"kind":"tree","path":".","pattern":"exact.py"}]),
        d.path(),
    )
    .unwrap();
    std::fs::write(d.path().join("exact.py\n"), "after").unwrap();
    assert_eq!(
        dependencies::assess(&receipt, Some(d.path()), dependencies::Budget::default())["state"],
        "unchanged"
    );
}
