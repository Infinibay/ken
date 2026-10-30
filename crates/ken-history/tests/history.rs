use ken_history::{clones, cochange, graphs, intent};
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{collections::BTreeSet, path::Path, time::Duration};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/history-domain.json")).unwrap()
}
fn database(root: &Path) -> Connection {
    std::fs::create_dir_all(root.join(".ken")).unwrap();
    let path = root.join(".ken/ken.db");
    let mut db = ken_store::ProjectDatabase::open(&path).unwrap();
    db.initialize().unwrap();
    drop(db);
    Connection::open(path).unwrap()
}
fn indexed(root: &Path, db: &Connection) {
    let f = fixture();
    for row in f["files"].as_array().unwrap() {
        let path = root.join(row["path"].as_str().unwrap());
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, row["source"].as_str().unwrap()).unwrap();
        db.execute(
            "INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at) VALUES(?,?,X'00',0,0)",
            params![row["id"].as_i64(), row["path"].as_str()],
        )
        .unwrap();
    }
    for r in f["symbols"].as_array().unwrap() {
        db.execute("INSERT INTO ci_symbols(id,file_id,qualname,name,kind,line_start,line_end) VALUES(?,?,?,?,?,?,?)",params![r["id"].as_i64(),r["file_id"].as_i64(),r["qualname"].as_str(),r["name"].as_str(),r["kind"].as_str(),r["line_start"].as_i64(),r["line_end"].as_i64()]).unwrap();
    }
    for (i, e) in f["edges"].as_array().unwrap().iter().enumerate() {
        db.execute("INSERT INTO ci_imports(from_file_id,to_file_id,to_module,line,resolution) VALUES(?,?,?,1,?)",params![e[0].as_i64(),e[1].as_i64(),format!("module{i}"),e[2].as_str()]).unwrap();
    }
}
fn commits(db: &Connection) {
    for r in fixture()["commits"].as_array().unwrap() {
        db.execute("INSERT INTO cr_commits(sha,committed_at,author,subject,n_files) VALUES(?,?,'Fixture','observation',?)",params![r["sha"].as_str(),r["committed_at"].as_i64(),r["files"].as_array().unwrap().len() as i64]).unwrap();
        let id = db.last_insert_rowid();
        for path in r["files"].as_array().unwrap() {
            db.execute(
                "INSERT INTO cr_commit_files(commit_id,path) VALUES(?,?)",
                params![id, path.as_str()],
            )
            .unwrap();
        }
    }
}
#[test]
fn cochange_and_existing_native_navigation_match_frozen_policy() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    commits(&db);
    let f = fixture();
    let options = cochange::CochangeOptions {
        now_seconds: f["now"].as_f64().unwrap(),
        auto_ingest: false,
        ..Default::default()
    };
    assert_eq!(
        cochange::cochange(&db, "./a.py", Some(d.path()), &options).unwrap(),
        f["outputs"]["cochange"]
    );
    let context = ken_core::project::DiscoveryContext::from_process().unwrap();
    let paths = ken_core::project::ProjectPaths::at(d.path(), &context).unwrap();
    let nav = ken_search::navigation::IndexNavigation::open(&paths).unwrap();
    assert_eq!(
        graphs::architecture(&nav, 1, 3).unwrap(),
        f["outputs"]["architecture"]
    );
    assert_eq!(
        graphs::blast_radius(&db, "./a.py", 4, &nav, Some(d.path()), &options).unwrap(),
        f["outputs"]["blast"]
    );
}
#[test]
fn minhash_definition_shingles_signatures_and_exact_reports_match_original() {
    use sha2::Digest;
    let bytes = include_bytes!("../resources/minhash-permutations.json");
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "aa3e0e39bb8d4fa6282f45759107b63a6b97705aa7d0fa20a6b4c3c11560aa48"
    );
    let f = fixture();
    for case in f["clone_primitives"].as_array().unwrap() {
        let sh = clones::shingles(case["source"].as_str().unwrap());
        assert_eq!(json!(sh), case["shingles"]);
        if !case["signature"].is_null() {
            assert_eq!(json!(clones::signature(&sh).unwrap()), case["signature"]);
        }
    }
    for c in f["lsh"].as_array().unwrap() {
        let (b, r) = clones::lsh_params(c["threshold"].as_f64().unwrap());
        assert_eq!(json!([b, r]), c["params"]);
    }
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    let options = clones::CloneOptions {
        min_similarity: 0.5,
        ..Default::default()
    };
    assert_eq!(
        clones::clones(&db, None, None, Some(d.path()), &options).unwrap(),
        f["outputs"]["clones"]
    );
    assert_eq!(
        clones::clones(&db, Some(".hidden/mod.py"), None, Some(d.path()), &options).unwrap(),
        f["outputs"]["target_clones"]
    );
    assert_eq!(
        clones::clones(&db, Some("c.py"), None, Some(d.path()), &Default::default()).unwrap(),
        f["outputs"]["clone_small"]
    );
}
struct ControlledVectors {
    scores: Vec<f32>,
    order: Vec<usize>,
}
impl intent::IntentVectors for ControlledVectors {
    fn embed_query(&mut self, _: &str) -> ken_history::Result<Vec<f32>> {
        Ok(vec![1., 0., 0.])
    }
    fn rank(&mut self, _: &[f32], rows: &[Vec<f32>]) -> ken_history::Result<intent::Ranking> {
        assert_eq!(rows.len(), self.scores.len());
        Ok(intent::Ranking {
            scores: self.scores.clone(),
            order: self.order.clone(),
        })
    }
}
fn history(db: &Connection) {
    for r in fixture()["intent"]["contexts"].as_array().unwrap() {
        db.execute(
            "INSERT OR IGNORE INTO cr_sessions(id,started_at) VALUES(?,0)",
            [r["session_id"].as_i64()],
        )
        .unwrap();
        let blob = r["embedding"]
            .as_array()
            .unwrap()
            .iter()
            .flat_map(|v| (v.as_f64().unwrap() as f32).to_le_bytes())
            .collect::<Vec<_>>();
        db.execute("INSERT INTO cr_contexts(id,session_id,kind,content,iteration,embedding,created_at) VALUES(?,?,?,?,0,?,0)",params![r["id"].as_i64(),r["session_id"].as_i64(),r["kind"].as_str(),r["content"].as_str(),blob]).unwrap();
    }
    for r in fixture()["intent"]["interactions"].as_array().unwrap() {
        db.execute("INSERT INTO cr_interactions(session_id,context_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(?,?,0,'edit','file',?,?,0)",params![r["session_id"].as_i64(),r["context_id"].as_i64(),r["path"].as_str(),r["weight"].as_f64()]).unwrap();
    }
}
#[test]
fn intent_aggregation_obeys_injected_numpy_order_and_float32_gate() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    let f = fixture();
    let r = &f["intent"]["ranking"];
    let mut vectors = ControlledVectors {
        scores: r["scores"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap() as f32)
            .collect(),
        order: r["order"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_u64().unwrap() as usize)
            .collect(),
    };
    assert_eq!(
        intent::intent_history(&db, "history query", 12, 15, Some(d.path()), &mut vectors).unwrap(),
        f["intent"]["empty"]
    );
    history(&db);
    assert_eq!(
        intent::intent_history(&db, "history query", 12, 15, Some(d.path()), &mut vectors).unwrap(),
        f["intent"]["result"]
    );
    db.execute("DELETE FROM cr_interactions", []).unwrap();
    db.execute("DELETE FROM cr_contexts WHERE id!=4", [])
        .unwrap();
    vectors.scores = vec![0.2f32];
    vectors.order = vec![0];
    assert_eq!(
        intent::intent_history(&db, "history query", 12, 15, None, &mut vectors).unwrap()["note"],
        "no sufficiently similar prior prompts"
    );
    db.execute("UPDATE cr_contexts SET embedding=X'0000803F00000000'", [])
        .unwrap();
    assert_eq!(
        intent::intent_history(&db, "history query", 12, 15, None, &mut vectors).unwrap(),
        f["intent"]["mismatch"]
    );
}
fn git(root: &Path, args: &[&str]) {
    let out = std::process::Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .env("GIT_AUTHOR_NAME", "Fixture")
        .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
        .env("GIT_COMMITTER_NAME", "Fixture")
        .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
        .env("GIT_AUTHOR_DATE", "@1700000000 +0000")
        .env("GIT_COMMITTER_DATE", "@1700000000 +0000")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}
fn commit(root: &Path, files: &[(&str, &str)], message: &str) {
    for (path, text) in files {
        let p = root.join(path);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, text).unwrap();
    }
    git(root, &["add", "-A"]);
    git(root, &["commit", "-m", message]);
}
#[test]
fn actual_git_ingest_is_incremental_idempotent_and_scopes_workspace_repositories() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    for name in ["backend", "service"] {
        std::fs::create_dir(d.path().join(name)).unwrap();
        git(&d.path().join(name), &["init"]);
    }
    let backend = d.path().join("backend");
    let service = d.path().join("service");
    commit(
        &backend,
        &[("model.py", "x=1"), ("schema.sql", "--1")],
        "one",
    );
    commit(&service, &[("other.py", "x=2")], "other");
    let options = cochange::IngestOptions {
        timeout: Duration::from_secs(5),
        ..Default::default()
    };
    assert_eq!(
        cochange::ingest_commits(&db, d.path(), &options).unwrap()["ingested"],
        2
    );
    assert_eq!(
        cochange::ingest_commits(&db, d.path(), &options).unwrap()["ingested"],
        0
    );
    commit(
        &backend,
        &[("model.py", "x=2"), ("schema.sql", "--2")],
        "two",
    );
    let only = cochange::IngestOptions {
        only_path: Some("backend/model.py".into()),
        ..options.clone()
    };
    let next = cochange::ingest_commits(&db, d.path(), &only).unwrap();
    assert_eq!(next["ingested"], 1);
    assert_eq!(next["per_repo"], json!({"backend":1}));
    let paths = db
        .prepare("SELECT DISTINCT path FROM cr_commit_files ORDER BY path")
        .unwrap()
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<rusqlite::Result<BTreeSet<_>>>()
        .unwrap();
    assert_eq!(
        paths,
        BTreeSet::from([
            "backend/model.py".into(),
            "backend/schema.sql".into(),
            "service/other.py".into()
        ])
    );
    let shas = db
        .prepare("SELECT sha FROM cr_commits")
        .unwrap()
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert!(shas.iter().all(|s| s.contains('\x01')));
}
#[test]
fn cancelled_git_and_failed_repo_transaction_do_not_publish_last_sha() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    let repo = d.path().join("repo");
    std::fs::create_dir(&repo).unwrap();
    git(&repo, &["init"]);
    commit(&repo, &[("a.py", "x=1")], "first");
    let cancelled = cochange::Cancellation::default();
    cancelled.cancel();
    let options = cochange::IngestOptions {
        cancellation: cancelled,
        ..Default::default()
    };
    let report = cochange::ingest_commits(&db, d.path(), &options).unwrap();
    assert_eq!(report["ingested"], 0);
    assert!(
        db.query_row(
            "SELECT value FROM meta WHERE key='cochange_last_sha:repo'",
            [],
            |r| r.get::<_, String>(0)
        )
        .is_err()
    );
    db.execute_batch("CREATE TRIGGER reject_commit BEFORE INSERT ON cr_commit_files BEGIN SELECT RAISE(ABORT,'rejected commit files'); END;").unwrap();
    assert!(cochange::ingest_commits(&db, d.path(), &Default::default()).is_err());
    assert_eq!(
        db.query_row("SELECT COUNT(*) FROM cr_commits", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert!(
        db.query_row(
            "SELECT value FROM meta WHERE key='cochange_last_sha:repo'",
            [],
            |r| r.get::<_, String>(0)
        )
        .is_err()
    );
}

#[test]
fn native_statistical_gates_and_history_absence_remain_honest() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    let mut options = cochange::CochangeOptions {
        auto_ingest: false,
        ..Default::default()
    };
    assert_eq!(
        cochange::cochange(&db, ".hidden/config.py", None, &options).unwrap()["note"],
        "no commit history ingested"
    );
    commits(&db);
    assert_eq!(
        cochange::cochange(&db, "missing.py", None, &options).unwrap()["total_commits"],
        30
    );
    options.now_seconds = fixture()["now"].as_f64().unwrap();
    options.min_support = 6;
    assert_eq!(
        cochange::cochange(&db, "a.py", None, &options).unwrap()["partners"],
        json!([])
    );
    options.min_support = 3;
    options.min_llr = 14.;
    assert_eq!(
        cochange::cochange(&db, "a.py", None, &options).unwrap()["partners"],
        json!([])
    );
    assert!((cochange::llr(5, 5, 5, 10) - 13.862943611198906).abs() < 1e-13);
    assert_eq!(cochange::llr(3, 2, 3, 10), 0.);
    assert_eq!(cochange::wilson_lower(0, 0), 0.);
    assert!(cochange::wilson_lower(3, 3) < cochange::wilson_lower(20, 20));
}

#[test]
fn supplied_ranking_must_be_a_permutation_and_stale_rows_are_never_ranked() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    history(&db);
    let mut broken = ControlledVectors {
        scores: vec![0.9; 19],
        order: vec![0; 19],
    };
    assert!(
        intent::intent_history(&db, "q", 12, 15, None, &mut broken)
            .unwrap_err()
            .to_string()
            .contains("permutation")
    );
    // IDs1/3 have equal scores but different interactions. The caller's tie order
    // must survive into matched_prompts even when k/limit are less than one.
    db.execute(
        "DELETE FROM cr_interactions WHERE context_id NOT IN (1,3)",
        [],
    )
    .unwrap();
    db.execute("DELETE FROM cr_contexts WHERE id NOT IN (1,3)", [])
        .unwrap();
    let mut reversed = ControlledVectors {
        scores: vec![0.9, 0.9],
        order: vec![1, 0],
    };
    let out = intent::intent_history(&db, "q", 0, 0, None, &mut reversed).unwrap();
    assert_eq!(out["matched_prompts"].as_array().unwrap().len(), 1);
    assert_eq!(out["matched_prompts"][0]["text"], "prompt 3");
    assert_eq!(out["files"].as_array().unwrap().len(), 1);
}

#[test]
fn root_ingest_keeps_legacy_sha_and_timeout_or_output_limit_cannot_advance_it() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    git(d.path(), &["init"]);
    commit(d.path(), &[("a.py", "1")], "first");
    for options in [
        cochange::IngestOptions {
            timeout: Duration::ZERO,
            ..Default::default()
        },
        cochange::IngestOptions {
            max_output_bytes: 1,
            ..Default::default()
        },
    ] {
        let out = cochange::ingest_commits(&db, d.path(), &options).unwrap();
        assert_eq!(out["ingested"], 0);
        assert!(
            out["history_gaps"]
                .as_array()
                .is_some_and(|a| !a.is_empty())
        );
        assert_eq!(
            db.query_row("SELECT COUNT(*) FROM cr_commits", [], |r| r
                .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
    let out = cochange::ingest_commits(&db, d.path(), &Default::default()).unwrap();
    assert_eq!(out["ingested"], 1);
    assert_eq!(out["per_repo"], json!({".":1}));
    let sha: String = db
        .query_row("SELECT sha FROM cr_commits", [], |r| r.get(0))
        .unwrap();
    assert!(!sha.contains('\x01'));
    assert_eq!(out["last_sha"], sha);
    assert_eq!(
        db.query_row(
            "SELECT value FROM meta WHERE key='cochange_last_sha'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        sha
    );
}

#[test]
fn clone_exact_scores_ignore_empty_shingles_and_boilerplate_is_reported() {
    let a = BTreeSet::from([1, 2, 3, 4]);
    let b = BTreeSet::from([1, 2]);
    assert_eq!(clones::exact_similarity(&a, &b), (0.5, 1.));
    assert_eq!(clones::exact_similarity(&a, &BTreeSet::new()), (0., 0.));
    assert!(clones::signature(&BTreeSet::new()).is_err());
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    let out = clones::clones(
        &db,
        Some("a.py"),
        Some("wrong"),
        Some(d.path()),
        &Default::default(),
    )
    .unwrap();
    assert_eq!(out["ok"], false);
    db.execute("DELETE FROM ci_symbols", []).unwrap();
    for id in 1..=101 {
        db.execute("INSERT INTO ci_symbols(id,file_id,qualname,name,kind,line_start,line_end) VALUES(?,1,?,?,'function',1,13)",params![id,format!("duplicate{id}"),format!("duplicate{id}")]).unwrap();
    }
    let out = clones::clones(&db, None, None, Some(d.path()), &Default::default()).unwrap();
    assert_eq!(out["clones"], json!([]));
    assert!(out["note"].as_str().unwrap().contains("boilerplate"));
    let bounded = clones::CloneOptions {
        max_source_bytes: 1,
        ..Default::default()
    };
    let out = clones::clones(&db, None, None, Some(d.path()), &bounded).unwrap();
    assert!(
        out["source_gaps"]["a.py"]
            .as_str()
            .unwrap()
            .contains("limit")
    );
}

#[test]
#[cfg(unix)]
fn clone_live_reads_cannot_escape_through_indexed_symlinks() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    std::fs::copy(d.path().join("a.py"), outside.path().join("secret.py")).unwrap();
    std::fs::remove_file(d.path().join("a.py")).unwrap();
    std::os::unix::fs::symlink(outside.path().join("secret.py"), d.path().join("a.py")).unwrap();
    let out = clones::clones(&db, None, None, Some(d.path()), &Default::default()).unwrap();
    assert!(
        out["source_gaps"]["a.py"]
            .as_str()
            .unwrap()
            .contains("escapes")
    );
    assert!(
        out["clones"]
            .as_array()
            .unwrap()
            .iter()
            .all(|pair| pair["a"]["file"] != "a.py" && pair["b"]["file"] != "a.py")
    );
}

struct EmptyNavigation;
impl graphs::NavigationEvidence for EmptyNavigation {
    fn architecture(&self, depth: i64, limit: i64) -> ken_history::Result<Value> {
        Ok(json!({"depth":depth,"limit":limit}))
    }
    fn find_tests(&self, _: &str, _: i64) -> ken_history::Result<Value> {
        Ok(json!({"tests":[]}))
    }
}
#[test]
fn blast_radius_bounds_transitive_imports_without_inventing_channels() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    db.execute("INSERT INTO ci_imports(from_file_id,to_file_id,to_module,line,resolution) VALUES(6,3,'c',1,'internal'),(8,6,'other',1,'internal')",[]).unwrap();
    let options = cochange::CochangeOptions {
        auto_ingest: false,
        ..Default::default()
    };
    let one = graphs::blast_radius(&db, "a.py", 0, &EmptyNavigation, None, &options).unwrap();
    assert_eq!(
        one["direct_importers"],
        json!(["b.py", "c.py", "tests/test_a.py"])
    );
    assert!(
        one["impacted"]
            .as_array()
            .unwrap()
            .iter()
            .all(|v| v["hops"] == 1)
    );
    let two = graphs::blast_radius(&db, "a.py", 2, &EmptyNavigation, None, &options).unwrap();
    let impacted = two["impacted"].as_array().unwrap();
    assert!(
        impacted
            .iter()
            .any(|v| v["path"] == "other.py" && v["hops"] == 2)
    );
    assert!(
        impacted
            .iter()
            .all(|v| v["path"] != "tiny.py" && v["path"] != "a.py")
    );
    assert_eq!(
        graphs::blast_radius(&db, "missing.py", 4, &EmptyNavigation, None, &options).unwrap()["error"],
        "file not indexed"
    );
    assert_eq!(
        graphs::architecture(&EmptyNavigation, 3, 7).unwrap(),
        json!({"depth":3,"limit":7})
    );
}

#[test]
fn clone_symbol_line_ranges_follow_unicode_splitlines() {
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    indexed(d.path(), &db);
    let f = fixture();
    for row in f["files"].as_array().unwrap() {
        let source = row["source"].as_str().unwrap();
        std::fs::write(
            d.path().join(row["path"].as_str().unwrap()),
            source.replace('\n', "\u{2028}"),
        )
        .unwrap();
    }
    let options = clones::CloneOptions {
        min_similarity: 0.5,
        ..Default::default()
    };
    assert_eq!(
        clones::clones(&db, None, None, Some(d.path()), &options).unwrap(),
        f["outputs"]["clones"]
    );
}

#[test]
fn clone_full_ties_preserve_original_pair_order_before_limit() {
    let ties: Value = serde_json::from_str(include_str!("fixtures/clone-ties.json")).unwrap();
    let d = tempfile::tempdir().unwrap();
    let db = database(d.path());
    let source = ties["source"].as_str().unwrap();
    std::fs::write(
        d.path().join("copies.py"),
        source.repeat(ties["symbols"].as_array().unwrap().len()),
    )
    .unwrap();
    db.execute("INSERT INTO ci_files(id,path,content_hash,mtime,indexed_at) VALUES(1,'copies.py',X'00',0,0)",[]).unwrap();
    for row in ties["symbols"].as_array().unwrap() {
        db.execute("INSERT INTO ci_symbols(id,file_id,qualname,name,kind,line_start,line_end) VALUES(?,1,?,?,'function',?,?)",params![row["id"].as_i64(),row["qualname"].as_str(),row["qualname"].as_str(),row["line"].as_i64(),row["line_end"].as_i64()]).unwrap();
    }
    let options = clones::CloneOptions {
        min_similarity: 1.,
        limit: 5,
        ..Default::default()
    };
    assert_eq!(
        clones::clones(&db, None, None, Some(d.path()), &options).unwrap(),
        ties["global_result"]
    );
    assert_eq!(
        clones::clones(&db, Some("copies.py"), None, Some(d.path()), &options).unwrap(),
        ties["target_result"]
    );
    let all = clones::clones(
        &db,
        None,
        None,
        Some(d.path()),
        &clones::CloneOptions {
            limit: 100,
            ..options
        },
    )
    .unwrap();
    let actual: Vec<_> = all["clones"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| json!([p["a"]["qualname"], p["b"]["qualname"]]))
        .collect();
    let expected: Vec<_> = ties["pair_order"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| json!([format!("copy{}", p[0]), format!("copy{}", p[1])]))
        .collect();
    assert_eq!(actual, expected);
}
