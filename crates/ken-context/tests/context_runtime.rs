//! Policy oracle is isolated at the numerical-provider boundary. These tests
//! separately exercise actual SQLite rows, public native policy, and rendering.
use flate2::read::GzDecoder;
use ken_context::{
    BriefOptions, Clock, ContextNumerics, LiveScores, NativeNumerics, Policy, RankRequest,
    RankResult, RenderOptions, Result, VectorScores, build_session_brief, channels, explain, rank,
    render_block, snapshot_session_scores, visible_file_paths,
};
use ken_text::PythonText;
use rusqlite::{Connection, params_from_iter, types::Value as SqlValue};
use serde_json::{Value, json};
use sha2::Digest;
use std::{collections::BTreeMap, io::Read, path::Path};
fn fixture() -> Value {
    let bytes = include_bytes!("fixtures/context-policy-reference.json.gz");
    assert_eq!(bytes.len(), 66549);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "cc38c48f6dcaefa5172d0733c36c883c73639802ac528b497a2f3499dfac79ed"
    );
    let mut json = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut json)
        .unwrap();
    serde_json::from_str(&json).unwrap()
}
fn database(f: &Value) -> ken_store::ProjectDatabase {
    let mut db = ken_store::ProjectDatabase::open(Path::new(":memory:")).unwrap();
    db.initialize().unwrap();
    for step in f["sql"].as_array().unwrap() {
        let values = step["params"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| {
                if let Some(vector) = v.get("blob_f32") {
                    SqlValue::Blob(
                        vector
                            .as_array()
                            .unwrap()
                            .iter()
                            .flat_map(|n| (n.as_f64().unwrap() as f32).to_le_bytes())
                            .collect(),
                    )
                } else {
                    match v {
                        Value::Null => SqlValue::Null,
                        Value::String(s) => SqlValue::Text(s.clone()),
                        Value::Number(n) => {
                            if let Some(i) = n.as_i64() {
                                SqlValue::Integer(i)
                            } else {
                                SqlValue::Real(n.as_f64().unwrap())
                            }
                        }
                        _ => panic!("fixture parameter"),
                    }
                }
            })
            .collect::<Vec<_>>();
        db.connection()
            .execute(step["sql"].as_str().unwrap(), params_from_iter(values))
            .unwrap();
    }
    db
}
fn materialize(root: &Path, f: &Value) {
    for (path, text) in f["contents"].as_object().unwrap() {
        let p = root.join(path);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, text.as_str().unwrap()).unwrap();
    }
}
fn scores(v: &Value) -> Vec<f32> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|n| n.as_f64().unwrap() as f32)
        .collect()
}
/// Controlled scores recorded at the original policy's external vector seam.
/// This provider is deliberately test-only; native CPU/model parity is separate.
struct ObservedNumerics {
    records: Vec<Value>,
    live: Option<Value>,
}
impl ObservedNumerics {
    fn new(f: &Value) -> Self {
        Self {
            records: f["numeric"].as_array().unwrap().clone(),
            live: None,
        }
    }
}
impl ContextNumerics for ObservedNumerics {
    fn normalize_query(&mut self, q: &[f32]) -> Result<Vec<f32>> {
        assert_eq!(q, &[1.]);
        Ok(q.to_vec())
    }
    fn rank_inline(&mut self, q: &[f32], blobs: &[Vec<u8>]) -> Result<VectorScores> {
        assert_eq!(q, &[1.]);
        let kept = blobs
            .iter()
            .enumerate()
            .filter_map(|(i, b)| (b.len() == 4).then_some(i))
            .collect::<Vec<_>>();
        let sims = kept
            .iter()
            .map(|&i| f32::from_le_bytes(blobs[i][..4].try_into().unwrap()))
            .collect();
        Ok(VectorScores { scores: sims, kept })
    }
    fn live_scores(
        &mut self,
        _conn: &Connection,
        _root: Option<&Path>,
        space: &str,
        q: &[f32],
    ) -> Result<Option<LiveScores>> {
        assert_eq!(q, &[1.]);
        let Some(value) = self.live.as_ref().and_then(|v| v.get(space)) else {
            return Ok(None);
        };
        let slots = value[0]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n.as_i64().unwrap())
            .collect::<Vec<_>>();
        if slots.is_empty() {
            Ok(None)
        } else {
            Ok(Some(LiveScores {
                slots,
                scores: scores(&value[1]),
            }))
        }
    }
    fn adaptive_threshold(&mut self, sims: &[f32], fixed: f64, enabled: bool) -> Result<f64> {
        if !enabled {
            return Ok(fixed);
        }
        let record = self
            .records
            .iter()
            .find(|v| {
                v["kind"] == "threshold"
                    && v["adaptive"] == true
                    && v["fixed"].as_f64() == Some(fixed)
                    && scores(&v["scores"]) == sims
            })
            .expect("captured numerical threshold");
        Ok(record["value"].as_f64().unwrap())
    }
    fn capped_indices(
        &mut self,
        sims: &[f32],
        threshold: f64,
        headroom: f64,
        cap: usize,
    ) -> Result<Vec<usize>> {
        let record = self
            .records
            .iter()
            .find(|v| {
                v["kind"] == "cap"
                    && v["cap"].as_u64() == Some(cap as u64)
                    && v["threshold"].as_f64() == Some(threshold)
                    && v["headroom"].as_f64() == Some(headroom)
                    && scores(&v["scores"]) == sims
            })
            .expect("captured numerical candidate selection");
        Ok(record["selected"]
            .as_array()
            .unwrap()
            .iter()
            .map(|slot| {
                record["slots"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .position(|value| value == slot)
                    .unwrap()
            })
            .collect())
    }
}
fn request(case: &Value, root: &Path, f: &Value) -> RankRequest {
    let r = &case["request"];
    RankRequest {
        agent_id: r["agent_id"].as_str().unwrap().into(),
        current_iteration: r["current_iteration"].as_i64().unwrap(),
        prompt: r["prompt"].as_str().unwrap().into(),
        prompt_embedding: scores(&r["prompt_embedding"]),
        top_files: r["top_files"].as_i64().unwrap(),
        top_symbols: r["top_symbols"].as_i64().unwrap(),
        top_findings: r["top_findings"].as_i64().unwrap(),
        project_root: r["project_root"].as_bool().unwrap().then(|| root.into()),
        include_reactive: r["include_reactive"].as_bool().unwrap(),
        clock: serde_json::from_value(f["clock"].clone()).unwrap(),
    }
}
fn compare(got: &Value, want: &Value, at: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!((a - b).abs() <= 1e-9 * (1. + b.abs()), "{at}: {a} != {b}");
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{at}: array lengths");
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                compare(a, b, &format!("{at}[{i}]"));
            }
        }
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(
                a.keys().collect::<Vec<_>>(),
                b.keys().collect::<Vec<_>>(),
                "{at}: object keys"
            );
            for (key, a) in a {
                compare(a, &b[key], &format!("{at}.{key}"));
            }
        }
        _ => assert_eq!(got, want, "{at}"),
    }
}
#[test]
fn frozen_complete_policy_matches_all_channels_boosts_modes_and_explanation() {
    let f = fixture();
    let db = database(&f);
    let t = tempfile::tempdir().unwrap();
    materialize(t.path(), &f);
    let before = db.connection().total_changes();
    db.connection()
        .pragma_update(None, "query_only", true)
        .unwrap();
    for (i, case) in f["cases"].as_array().unwrap().iter().enumerate() {
        let environment: BTreeMap<String, String> =
            serde_json::from_value(case["env"].clone()).unwrap();
        let policy = Policy::capture(&environment).unwrap();
        let request = request(case, t.path(), &f);
        let mut numerical = ObservedNumerics::new(&f);
        let result = rank(db.connection(), &request, &policy, &mut numerical).unwrap();
        compare(
            &serde_json::to_value(result).unwrap(),
            &case["result"],
            &format!("case{i}.rank"),
        );
        let mut detail = serde_json::to_value(
            explain(db.connection(), &request, &policy, &mut numerical, 8).unwrap(),
        )
        .unwrap();
        for (_, changes) in detail["boosts"].as_object_mut().unwrap() {
            changes
                .as_array_mut()
                .unwrap()
                .sort_by(|a, b| a["target"].as_str().cmp(&b["target"].as_str()));
        }
        compare(
            &detail,
            &case["explanation"],
            &format!("case{i}.explanation"),
        );
    }
    assert_eq!(db.connection().total_changes(), before);
}
#[test]
fn frozen_rendering_preserves_verbose_caps_unicode_codepoints_and_whole_lines() {
    let f = fixture();
    let db = database(&f);
    for (i, case) in f["renders"].as_array().unwrap().iter().enumerate() {
        let raw = case["result_json"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| case["result"].to_string());
        let result: RankResult = serde_json::from_str(&raw).unwrap();
        let expected: PythonText =
            serde_json::from_str(case["block_json"].as_str().unwrap()).unwrap();
        let options = RenderOptions {
            verbose: case["verbose"].as_i64().unwrap(),
            max_chars: case["max_chars"].as_i64(),
            ..Default::default()
        };
        let block = render_block(db.connection(), &result, &options).unwrap();
        assert_eq!(block, expected, "render{i}");
        let visible = visible_file_paths(&block);
        let expected: Vec<PythonText> = if let Some(raw) = case["visible_json"].as_str() {
            serde_json::from_str(raw).unwrap()
        } else {
            serde_json::from_str(&case["visible"].to_string()).unwrap()
        };
        assert_eq!(visible, expected);
        if let Some(max) = options.max_chars.filter(|n| *n > 0) {
            assert!(block.codepoints().len() <= max as usize);
        }
    }
}
#[test]
fn mapped_fuzzy_candidate_policy_preserves_headroom_and_cap_selection() {
    let f = fixture();
    let db = database(&f);
    let mut numerical = ObservedNumerics::new(&f);
    numerical.live = Some(f["mapped"]["live"].clone());
    let policy = Policy {
        fuzzy_resolve_cap: 3,
        ..Default::default()
    };
    let pair = channels::fuzzy_scores(
        db.connection(),
        &[1.],
        None,
        &serde_json::from_value::<Clock>(f["clock"].clone()).unwrap(),
        &policy,
        &mut numerical,
    )
    .unwrap();
    compare(
        &serde_json::to_value(pair).unwrap(),
        &f["mapped"]["result"],
        "mapped",
    );
}
#[test]
fn durable_snapshot_keeps_strongest_turn_and_rolls_back_failed_replacement() {
    let f = fixture();
    let db = database(&f);
    let conn = db.connection();
    let clock: Clock = serde_json::from_value(f["clock"].clone()).unwrap();
    assert_eq!(
        snapshot_session_scores(conn, "current", 12, clock.now_ms).unwrap(),
        f["snapshot"]["count"].as_u64().unwrap() as usize
    );
    let load = || {
        let mut s=conn.prepare("SELECT target_path,score,pattern,created_at FROM cr_session_scores WHERE session_id=1 ORDER BY target_path").unwrap();
        s.query_map([],|r|Ok(json!({"target_path":r.get::<_,String>(0)?,"score":r.get::<_,f64>(1)?,"pattern":r.get::<_,String>(2)?,"created_at":r.get::<_,i64>(3)?}))).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap()
    };
    assert_eq!(json!(load()), f["snapshot"]["rows"]);
    let before = load();
    conn.execute("INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(1,90,'edit','file','new-failure.py',1,0)",[]).unwrap();
    conn.execute_batch("CREATE TRIGGER fail_snapshot BEFORE INSERT ON cr_session_scores WHEN NEW.target_path='new-failure.py' BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END").unwrap();
    assert!(snapshot_session_scores(conn, "current", 90, clock.now_ms).is_err());
    assert_eq!(load(), before);
    assert_eq!(
        snapshot_session_scores(conn, "absent", 0, clock.now_ms).unwrap(),
        0
    );
}
#[test]
fn session_brief_uses_latest_prompt_narrative_and_real_knowledge_records() {
    let f = fixture();
    let db = database(&f);
    db.connection()
        .execute(
            "UPDATE cr_findings SET tags='[]' WHERE topic='unrelated'",
            [],
        )
        .unwrap();
    let t = tempfile::tempdir().unwrap();
    materialize(t.path(), &f);
    let options = BriefOptions {
        now_ms: f["clock"]["now_ms"].as_i64().unwrap(),
        project_root: Some(t.path().into()),
        ..Default::default()
    };
    let expected: PythonText = serde_json::from_str(f["brief_json"].as_str().unwrap()).unwrap();
    assert_eq!(
        build_session_brief(db.connection(), &options).unwrap(),
        expected
    );
}
#[test]
fn gate_preserves_rejected_evidence_and_manual_requests_can_disable_reactive() {
    let f = fixture();
    let mut db = ken_store::ProjectDatabase::open(Path::new(":memory:")).unwrap();
    db.initialize().unwrap();
    let conn = db.connection();
    conn.execute_batch("INSERT INTO cr_sessions(id,agent_id,started_at) VALUES(1,'quiet',0);INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(1,0,'read','file','weak.py',0.1,0)").unwrap();
    let request = RankRequest {
        agent_id: "quiet".into(),
        prompt: "hello".into(),
        prompt_embedding: vec![1.],
        clock: Clock {
            now_ms: 0,
            now_ns: 0,
        },
        ..Default::default()
    };
    let mut numbers = ObservedNumerics::new(&f);
    let result = rank(conn, &request, &Policy::default(), &mut numbers).unwrap();
    assert!(result.empty());
    let detail = serde_json::to_value(
        explain(conn, &request, &Policy::default(), &mut numbers, 10).unwrap(),
    )
    .unwrap();
    assert_eq!(
        detail["confidence_gate"],
        json!({"threshold":1.5,"suppressed":true})
    );
    assert_eq!(detail["candidates_before_gate"][0]["target"], "weak.py");
    let manual = RankRequest {
        include_reactive: false,
        ..request
    };
    assert!(
        rank(conn, &manual, &Policy::default(), &mut numbers)
            .unwrap()
            .empty()
    );
}
#[test]
fn native_vector_boundary_reads_stored_bytes_and_skips_other_model_dimensions() {
    let mut numerical = NativeNumerics::default();
    let blob = |values: &[f32]| {
        values
            .iter()
            .flat_map(|f| f.to_le_bytes())
            .collect::<Vec<_>>()
    };
    let result = numerical
        .rank_inline(
            &[1., 0.],
            &[blob(&[2., 0.]), blob(&[0., 4.]), blob(&[1., 2., 3.])],
        )
        .unwrap();
    assert_eq!(result.kept, vec![0, 1]);
    assert_eq!(result.scores, vec![1., 0.]);
    let query = numerical.normalize_query(&[3., 4.]).unwrap();
    assert!((query[0] - 0.6).abs() < 1e-7);
    assert!((query[1] - 0.8).abs() < 1e-7);
    assert_eq!(
        numerical
            .capped_indices(&[0.2, 0.8, 0.4, 0.9], 0.3, 0., 2)
            .unwrap()
            .into_iter()
            .collect::<std::collections::BTreeSet<_>>(),
        [1, 3].into_iter().collect()
    );
}
#[test]
fn current_postings_match_inline_names_and_stale_postings_fall_back() {
    use ken_retrieval::vocabulary::{NAME_TOKEN_VERSION, name_tokens};
    let f = fixture();
    let db = database(&f);
    let conn = db.connection();
    let prompt: PythonText = "relay packet encoding source".into();
    let inline = channels::lexical_scores(conn, &prompt, None, None).unwrap();
    let stops = std::collections::BTreeSet::new();
    let mut statement = conn.prepare("SELECT id,path FROM ci_files").unwrap();
    for row in statement
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
        .unwrap()
    {
        let (id, path) = row.unwrap();
        for token in name_tokens(&path, &stops) {
            conn.execute(
                "INSERT OR IGNORE INTO ci_name_tokens(kind,row_id,token) VALUES(0,?,?)",
                rusqlite::params![id, token],
            )
            .unwrap();
        }
    }
    let mut statement = conn
        .prepare("SELECT id,kind,qualname,name FROM ci_symbols")
        .unwrap();
    for row in statement
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                format!(
                    "{} {} {}",
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?
                ),
            ))
        })
        .unwrap()
    {
        let (id, text) = row.unwrap();
        for token in name_tokens(&text, &stops) {
            conn.execute(
                "INSERT OR IGNORE INTO ci_name_tokens(kind,row_id,token) VALUES(1,?,?)",
                rusqlite::params![id, token],
            )
            .unwrap();
        }
    }
    conn.execute("INSERT INTO meta(key,value) VALUES('name_token_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[NAME_TOKEN_VERSION.to_string()]).unwrap();
    let mut posted = channels::lexical_scores(conn, &prompt, None, None).unwrap();
    let mut expected = inline.clone();
    for items in [
        &mut expected.0,
        &mut expected.1,
        &mut posted.0,
        &mut posted.1,
    ] {
        items.sort_by(|a, b| a.target.codepoints().cmp(b.target.codepoints()));
    }
    assert_eq!(posted, expected);
    conn.execute(
        "UPDATE meta SET value='stale-vocabulary' WHERE key='name_token_version'",
        [],
    )
    .unwrap();
    conn.execute("DELETE FROM ci_name_tokens", []).unwrap();
    assert_eq!(
        channels::lexical_scores(conn, &prompt, None, None).unwrap(),
        inline
    );
}
#[test]
fn native_mapped_vectors_remove_freed_slots_before_distribution_and_infer_project_root() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(root.path().join(".ken")).unwrap();
    let mut db = ken_store::ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    db.initialize().unwrap();
    let store = ken_store::VectorStore::open(
        &root.path().join(".ken/vectors"),
        ken_store::VectorSpace::Files,
        2,
        Some("context-boundary-fixture"),
    )
    .unwrap();
    store
        .write(
            &[0, 1, 2],
            &[vec![1., 0.], vec![0., 1.], vec![0., 0.]],
            true,
        )
        .unwrap();
    db.connection()
        .execute(
            "INSERT OR REPLACE INTO ci_vec_alloc(space,next_slot) VALUES('ci_files',3)",
            [],
        )
        .unwrap();
    db.connection()
        .execute(
            "INSERT INTO ci_vec_free(space,slot) VALUES('ci_files',1)",
            [],
        )
        .unwrap();
    let mut numerical = NativeNumerics::default();
    let live = numerical
        .live_scores(db.connection(), None, "ci_files", &[3., 4.])
        .unwrap()
        .unwrap();
    assert_eq!(live.slots, vec![0, 2]);
    assert_eq!(live.scores, vec![0.6, 0.]);
    assert!(
        numerical
            .live_scores(db.connection(), None, "ci_files", &[1., 0., 0.])
            .unwrap()
            .is_none()
    );
}
#[test]
fn brief_narrative_and_host_model_notices_are_throttled_independently() {
    let mut db = ken_store::ProjectDatabase::open(Path::new(":memory:")).unwrap();
    db.initialize().unwrap();
    let conn = db.connection();
    let clock = 2_000_000_000_000;
    let options = BriefOptions {
        now_ms: clock,
        model_upgrade: Some(("old/model".into(), "new/context-model".into())),
        ..Default::default()
    };
    let first = build_session_brief(conn, &options)
        .unwrap()
        .to_utf8()
        .unwrap();
    assert!(first.contains("new/context-model"));
    assert!(build_session_brief(conn, &options).unwrap().is_empty());
    let reembed = BriefOptions {
        now_ms: clock,
        reembed_reason: Some("Stored vectors belong to the earlier document space".into()),
        ..Default::default()
    };
    assert!(
        build_session_brief(conn, &reembed)
            .unwrap()
            .to_utf8()
            .unwrap()
            .contains("ken reembed")
    );
    assert!(build_session_brief(conn, &reembed).unwrap().is_empty());
    conn.execute_batch("INSERT INTO cr_sessions(id,agent_id,started_at) VALUES(1,'resume',0);INSERT INTO cr_contexts(session_id,kind,content,iteration,created_at) VALUES(1,'user_prompt','repair relay capture',0,1);INSERT INTO cr_contexts(session_id,kind,content,iteration,created_at) VALUES(1,'turn_end','Preserve the detached source witness.',1,2);INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(1,1,'read','file','read.py',1,3);INSERT INTO cr_interactions(session_id,iteration,event_type,target_kind,target_path,weight,created_at) VALUES(1,1,'edit','file','edited.py',1,4)").unwrap();
    let brief = build_session_brief(
        conn,
        &BriefOptions {
            now_ms: clock,
            ..Default::default()
        },
    )
    .unwrap()
    .to_utf8()
    .unwrap();
    assert!(brief.contains("repair relay capture"));
    assert!(brief.contains("Preserve the detached source witness."));
    assert!(brief.contains("edited.py, read.py"));
}
#[test]
fn legacy_duplicate_snapshot_rows_use_the_last_observation_once() {
    let mut db = ken_store::ProjectDatabase::open(Path::new(":memory:")).unwrap();
    db.initialize().unwrap();
    db.connection().execute_batch("INSERT INTO cr_sessions(id,agent_id,started_at) VALUES(1,'historical',0);INSERT INTO cr_session_scores(session_id,target_kind,target_path,score,pattern,created_at) VALUES(1,'file','duplicate.py',5,'cited',0),(1,'file','duplicate.py',0.1,'neutral',0)").unwrap();
    let result = channels::predictive_scores(
        db.connection(),
        &[channels::SimilarPrompt {
            session_id: 1,
            sim: 0.5,
            days_ago: 0.,
        }],
        &Policy::default(),
    )
    .unwrap();
    assert_eq!(result.len(), 1);
    assert!((result[0].score - 0.1).abs() < 1e-12);
}
