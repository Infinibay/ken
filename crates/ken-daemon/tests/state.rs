use ken_context::{NativeNumerics, Policy};
use ken_daemon::state::DaemonState;
use ken_retrieval::{Result, query_encoder::QueryEncoder};
use serde_json::{Value, json};
use std::{cell::Cell, rc::Rc};

struct Encoder(Rc<Cell<usize>>);
impl QueryEncoder for Encoder {
    fn embed_query(&self, _: &ken_text::PythonText) -> Result<Vec<f32>> {
        self.0.set(self.0.get() + 1);
        Ok(vec![1., 0.])
    }
}
fn fixture() -> (tempfile::TempDir, DaemonState, Rc<Cell<usize>>) {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    std::fs::write(
        root.path().join(".ken/meta.json"),
        br#"{"project_id":"fixture","auth_token":"secret"}"#,
    )
    .unwrap();
    let calls = Rc::new(Cell::new(0));
    let state = DaemonState::open(
        root.path(),
        Rc::new(Encoder(calls.clone())),
        Box::new(NativeNumerics::default()),
        Policy::default(),
    )
    .unwrap();
    (root, state, calls)
}
fn handle(state: &mut DaemonState, path: &str, body: Value) -> Value {
    state.handle(path, body).unwrap()
}
fn number(state: &DaemonState, sql: &str) -> i64 {
    state.connection().query_row(sql, [], |r| r.get(0)).unwrap()
}

#[test]
fn sessions_are_idempotent_lazy_and_keep_separate_event_iteration_and_prompt_anchors() {
    let (_root, mut state, _calls) = fixture();
    let one =
        handle(&mut state, "/sessions/start", json!({"session_id":"a"}))["ken_session_pk"].clone();
    assert_eq!(
        handle(&mut state, "/sessions/start", json!({"session_id":"a"}))["ken_session_pk"],
        one
    );
    assert_eq!(number(&state, "SELECT count(*) FROM cr_sessions"), 1);
    handle(
        &mut state,
        "/prompts",
        json!({"session_id":"lazy","prompt":""}),
    );
    handle(
        &mut state,
        "/tools/pre",
        json!({"session_id":"lazy","tool":"Edit","input":{"file_path":"src/a.rs"}}),
    );
    let conn = state.connection();
    let row:(i64,i64,i64)=conn.query_row("SELECT i.iteration,c.iteration,i.context_id FROM cr_interactions i JOIN cr_contexts c ON c.id=i.context_id",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap();
    assert_eq!((row.0, row.1), (3, 1));
    assert!(row.2 > 0);
    assert_eq!(state.active_sessions(), 2);
    handle(&mut state, "/sessions/end", json!({"session_id":"a"}));
    assert_eq!(state.active_sessions(), 1);
    state.finalize().unwrap();
    assert_eq!(
        number(
            &state,
            "SELECT count(*) FROM cr_sessions WHERE ended_at IS NULL"
        ),
        0
    );
}

#[test]
fn failed_post_retracts_latest_matching_interaction_and_preserves_other_attention() {
    let (_root, mut state, _calls) = fixture();
    for path in ["src/a.rs", "src/b.rs", "src/a.rs"] {
        handle(
            &mut state,
            "/tools/pre",
            json!({"session_id":"a","tool":"functions.apply_patch","input":{"path":path}}),
        );
    }
    handle(
        &mut state,
        "/tools/post",
        json!({"session_id":"a","tool":"functions.apply_patch","input":{"path":"src/a.rs"},"success":false}),
    );
    assert_eq!(number(&state, "SELECT count(*) FROM cr_interactions"), 2);
    assert_eq!(
        number(
            &state,
            "SELECT count(*) FROM cr_interactions WHERE target_path='src/a.rs'"
        ),
        1
    );
    assert_eq!(
        number(
            &state,
            "SELECT count(*) FROM cr_contexts WHERE kind='tool_call_post'"
        ),
        1
    );
}

#[test]
fn prompt_embeds_once_and_rank_rerender_reuses_cache_while_restart_falls_back_to_persisted_prompt()
{
    let (root, mut state, calls) = fixture();
    let response = handle(
        &mut state,
        "/prompts",
        json!({"session_id":"a","prompt":"explain the architecture"}),
    );
    assert_eq!(response["ok"], true);
    assert_eq!(calls.get(), 1);
    let rendered = handle(&mut state, "/rank", json!({"verbose":2,"max_chars":200}));
    assert_eq!(rendered["prompt"], "explain the architecture");
    assert_eq!(calls.get(), 1);
    assert!(rendered["context_chars"].as_u64().unwrap() <= 200);
    drop(state);
    let mut reopened = DaemonState::open(
        root.path(),
        Rc::new(Encoder(calls.clone())),
        Box::new(NativeNumerics::default()),
        Policy::default(),
    )
    .unwrap();
    assert_eq!(
        handle(&mut reopened, "/rank", json!({}))["prompt"],
        "explain the architecture"
    );
    assert_eq!(calls.get(), 2);
    handle(
        &mut reopened,
        "/explain",
        json!({"query":"new direct query"}),
    );
    assert_eq!(calls.get(), 3);
}

#[test]
fn turn_end_truncates_unicode_and_cites_only_exact_or_unique_indexed_source_paths() {
    let (root, mut state, _calls) = fixture();
    for path in [
        "src/a.rs",
        "src/unique.rs",
        "x/duplicate.rs",
        "y/duplicate.rs",
    ] {
        state.connection().execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at) VALUES(?,'rust','x',0,0)",[path]).unwrap();
        std::fs::create_dir_all(root.path().join(path).parent().unwrap()).unwrap();
        std::fs::write(root.path().join(path), "").unwrap();
    }
    let text = format!(
        "src/a.rs:10 unique.rs duplicate.rs missing.rs {}",
        "🦀".repeat(9000)
    );
    handle(
        &mut state,
        "/turn-end",
        json!({"session_id":"a","assistant_text":text}),
    );
    assert_eq!(
        number(
            &state,
            "SELECT length(content) FROM cr_contexts WHERE kind='turn_end'"
        ),
        8000
    );
    let mut stmt = state
        .connection()
        .prepare(
            "SELECT target_path FROM cr_interactions WHERE event_type='cited' ORDER BY target_path",
        )
        .unwrap();
    let cites = stmt
        .query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert_eq!(cites, ["src/a.rs", "src/unique.rs"]);
}

#[test]
fn direct_rank_without_sessions_and_unknown_requests_have_controlled_contracts() {
    let (_root, mut state, _calls) = fixture();
    let empty = handle(&mut state, "/rank", json!({}));
    assert_eq!(empty["ok"], false);
    assert!(
        empty["error"]
            .as_str()
            .unwrap()
            .contains("no cached prompt")
    );
    let rank = handle(&mut state, "/rank", json!({"query":"direct","verbose":99}));
    assert_eq!(rank["ok"], true);
    assert_eq!(state.active_sessions(), 0);
    assert!(state.handle("/sessions/start", json!({})).is_err());
    assert!(state.handle("/not-present", json!({})).is_err());
}
