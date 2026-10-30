use ken_application::embedding::FindingVectorMath;
use ken_application::knowledge::{
    EmbeddingResources, FindingEmbeddings, KnowledgeApplication, SessionSignals,
};
use ken_knowledge::{self as knowledge, findings};
use ken_maintenance::{ConfigEnvironment, UserConfig};
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ModelCatalog, ModelFactory, PreparedModelResources,
};
use ken_retrieval::project_embeddings::TransformerOverrides;
use rusqlite::Connection;
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
    time::Duration,
};
#[derive(Default)]
struct Offline {
    documents: Cell<usize>,
    queries: Cell<usize>,
}
impl FindingEmbeddings for Offline {
    fn embed_finding(&self, _: &Connection, _: &str, _: &str) -> Option<Vec<f32>> {
        self.documents.set(self.documents.get() + 1);
        None
    }
    fn embed_query(&self, _: &Connection, _: &str) -> knowledge::Result<Vec<f32>> {
        self.queries.set(self.queries.get() + 1);
        Err(knowledge::Error::Invalid("model assets unavailable".into()))
    }
}
#[derive(Default)]
struct Signals {
    received: RefCell<Vec<(String, String)>>,
}
impl SessionSignals for Signals {
    fn dismiss(&self, target: &str, reason: &str) -> knowledge::Result<Value> {
        self.received
            .borrow_mut()
            .push((target.into(), reason.into()));
        Ok(json!({"ok":false,"error":"no active session"}))
    }
}
fn db() -> Connection {
    let conn = Connection::open_in_memory().unwrap();
    findings::ensure_schema(&conn).unwrap();
    conn.execute_batch("CREATE TABLE ci_files(id INTEGER PRIMARY KEY,path TEXT,embedding BLOB,vec_slot INTEGER);CREATE TABLE ci_symbols(id INTEGER PRIMARY KEY,file_id INTEGER,qualname TEXT);INSERT INTO meta VALUES('findings_graph_enabled','0');").unwrap();
    conn
}
fn app(root: &Path, embeddings: Rc<Offline>, signals: Rc<Signals>) -> KnowledgeApplication {
    KnowledgeApplication::new(root, embeddings, signals, None).unwrap()
}
#[test]
fn domain_callback_rejects_invalid_kind_and_justification_before_embedding_or_writes() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let calls = Cell::new(0);
    let mut embed = |_: &str, _: &str| {
        calls.set(calls.get() + 1);
        Some(vec![1., 0.])
    };
    for input in [
        json!({"topic":"", "content":"note"}),
        json!({"topic":"bad-kind","content":"note","kind":"invented"}),
        json!({"topic":"bad-evidence","content":"note","justification":{"rationale":"because","evidence":[{"path":"../escape"}]}}),
    ] {
        let result = findings::remember_with_embedding(
            &conn,
            &input,
            &mut embed,
            10,
            Some(root.path()),
            &[],
            &FindingVectorMath::default(),
        )
        .unwrap();
        assert_eq!(result["ok"], false);
    }
    assert_eq!(calls.get(), 0);
    assert_eq!(
        conn.query_row("SELECT count(*) FROM cr_findings", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn plain_save_survives_embedding_failure_and_anchor_and_exact_topic_need_no_query_model() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let embeddings = Rc::new(Offline::default());
    let app = app(root.path(), embeddings.clone(), Rc::default());
    assert_eq!(app.remember(&conn,&json!({"topic":"writes","content":"Persist before publication.","anchor_tool":"cargo","tags":["bugfix"]}),10).unwrap()["ok"],true);
    assert_eq!(embeddings.documents.get(), 1);
    assert!(
        conn.query_row("SELECT embedding FROM cr_findings", [], |r| r
            .get::<_, Option<Vec<u8>>>(0))
            .unwrap()
            .is_none()
    );
    let answer = app
        .recall(&conn, &json!({"topic":"writes","detail":"answer"}), 10)
        .unwrap();
    assert_eq!(
        answer["memories"][0]["conclusion"],
        "Persist before publication."
    );
    assert_eq!(answer["memories"][0]["validity"]["state"], "untracked");
    let anchored = app
        .recall(
            &conn,
            &json!({"anchor_tool":"cargo","query":"must not embed"}),
            10,
        )
        .unwrap();
    assert_eq!(anchored[0]["topic"], "writes");
    let exact = app.recall(&conn, &json!({"topic":"writes"}), 10).unwrap();
    assert_eq!(exact["finding"]["content"], "Persist before publication.");
    assert_eq!(embeddings.queries.get(), 0);
}
#[test]
fn native_resource_configuration_is_cold_until_validated_embedding_work() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let config = UserConfig::new(&ConfigEnvironment {
        config_dir: Some(root.path().join("user")),
        xdg_config_home: None,
        home: root.path().into(),
    });
    config.set_default_model(Some("user/selected")).unwrap();
    let factory = Arc::new(ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.path().join("cache")).unwrap(),
        PreparedModelResources::new(
            &root.path().join("private"),
            &root.path().join("missing.npz"),
        )
        .unwrap(),
        AcquisitionPolicy::Offline,
    ));
    let resources = EmbeddingResources::new(
        factory,
        config,
        Some("explicit/model".into()),
        TransformerOverrides::default(),
    );
    let app = KnowledgeApplication::new(
        root.path(),
        Rc::new(resources),
        Rc::new(Signals::default()),
        None,
    )
    .unwrap();
    for input in [
        json!({"topic":"kind","content":"note","kind":"bad"}),
        json!({"topic":"proof","content":"note","justification":{"rationale":"why","dependencies":[{"path":"../escape"}]}}),
    ] {
        assert_eq!(app.remember(&conn, &input, 10).unwrap()["ok"], false);
    }
    assert_eq!(
        conn.query_row(
            "SELECT count(*) FROM meta WHERE key IN ('embed_model','embed_doc_space')",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
    assert!(!root.path().join("private").exists());
}
#[test]
fn dismiss_uses_injected_live_session_signal_and_does_not_write_fake_sql_sessions() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let signals = Rc::new(Signals::default());
    let embeddings = Rc::new(Offline::default());
    let app = app(root.path(), embeddings.clone(), signals.clone());
    let response = app
        .remember(
            &conn,
            &json!({"action":"dismiss","topic":"src/old.rs","reason":"unrelated"}),
            10,
        )
        .unwrap();
    assert_eq!(response["error"], "no active session");
    assert_eq!(
        &*signals.received.borrow(),
        &[("src/old.rs".into(), "unrelated".into())]
    );
    assert_eq!(embeddings.documents.get(), 0);
    assert_eq!(
        conn.query_row(
            "SELECT count(*) FROM sqlite_master WHERE name LIKE '%session%'",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
}
#[test]
fn explicit_reasoning_goals_reuse_persistent_checkpoints_without_model_assets() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let reasoning = Connection::open_in_memory().unwrap();
    let embeddings = Rc::new(Offline::default());
    let app = app(root.path(), embeddings.clone(), Rc::default());
    app.reason_record(&reasoning,&json!({"source":"read-source","facts":[{"predicate":"owns","subject":"store","object":"writes"}],"evidence":"source observation"})).unwrap();
    let input = json!({"question":"Who owns writes?","goal":{"predicate":"owns","subject":"store","object":"writes"}});
    let first = app.reason(&conn, &reasoning, &input, 10).unwrap();
    assert_eq!(first["status"], "supported");
    let second = app.reason(&conn, &reasoning, &input, 11).unwrap();
    assert_eq!(second["reuse"]["checkpoint"], true);
    assert_eq!(second["reuse"]["new_work"], 0);
    assert_eq!(second["question"], "Who owns writes?");
    assert_eq!(embeddings.documents.get() + embeddings.queries.get(), 0);
}
#[test]
fn invalid_recall_view_is_rejected_before_query_and_missing_goal_never_asserts_retrieval_as_facts()
{
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let reasoning = Connection::open_in_memory().unwrap();
    let embeddings = Rc::new(Offline::default());
    let app = app(root.path(), embeddings.clone(), Rc::default());
    let result = app
        .recall(&conn, &json!({"query":"query","detail":"bad"}), 10)
        .unwrap();
    assert_eq!(result["ok"], false);
    assert_eq!(
        app.recall(&conn, &json!({"query":"query","max_chars":-1}), 10)
            .unwrap()["ok"],
        false
    );
    assert_eq!(embeddings.queries.get(), 0);
    let result = app
        .reason(&conn, &reasoning, &json!({"question":"unformalized"}), 10)
        .unwrap();
    assert_eq!(result["status"], "needs_interpretation");
    assert!(result["candidates"]["error"].is_string());
    assert_eq!(
        reasoning
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name='sources'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
}
fn checks(root: &Path) -> (ken_checks_application::ChecksApplication, String) {
    let grammar =
        PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared native grammars"));
    let resources = ken_checks_application::Resources::prepared(
        &grammar,
        ken_checks_application::WorkerProgram::new(root.join("worker-never-needed-for-freshness")),
    )
    .unwrap();
    let identity = resources.identity().unwrap();
    (
        ken_checks_application::ChecksApplication::new(root, resources).unwrap(),
        identity,
    )
}
#[test]
fn check_receipt_justification_and_recall_use_live_freshness_metadata_not_raw_witnesses() {
    use ken_contracts::checks::{Receipt, Rule, Store, capture_sources};
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("a.py"), "def f():\n return 1\n").unwrap();
    let conn = db();
    let (checks, identity) = checks(root.path());
    let definition = json!({"id":"application.memory","description":"Controlled source contract observation","query":"language \"kql/2\";module sample;query q{callable $c;}select $c;","path":".","expectation":"some_match"});
    let rule = Rule::read(&definition).unwrap();
    let store = Store::new(root.path()).unwrap();
    store
        .save_rule(&json!({"version":1,"definition":definition}), None)
        .unwrap();
    let snapshot = capture_sources(root.path(), ".", Duration::from_secs(2)).unwrap();
    let receipt=Receipt::from_json(&json!({"version":1,"run_id":"application-memory-run","created_at":"2026-10-30T00:00:00Z","scope":"all","selection":"explicit","status":"pass","checks":[{"rule":rule.id,"description":rule.description,"revision":rule.revision(),"path":".","query":rule.query,"libraries":{},"expectation":"some_match","status":"pass","engine":identity,"result":{"rows":[["RAW_WITNESS_MUST_STAY_IN_RECEIPT"]],"check_snapshot":snapshot}}]})).unwrap();
    store.write_receipt(&receipt).unwrap();
    let embeddings = Rc::new(Offline::default());
    let app = KnowledgeApplication::new(
        root.path(),
        embeddings.clone(),
        Rc::new(Signals::default()),
        None,
    )
    .unwrap()
    .with_checks_provider(move || Ok(checks.clone()));
    assert_eq!(app.remember(&conn,&json!({"topic":"contract-note","content":"Review this source contract within its scope.","check_run":"application-memory-run"}),10).unwrap()["ok"],true);
    let recalled = app
        .recall(&conn, &json!({"topic":"contract-note"}), 10)
        .unwrap();
    let finding = &recalled["finding"];
    assert_eq!(finding["validity"]["state"], "unchanged");
    assert_eq!(
        finding["validity"]["checks"][0]["observations"][0]["rule"],
        "application.memory"
    );
    assert_eq!(
        finding["validity"]["checks"][0]["observations"][0]["validity"],
        "unchanged"
    );
    assert!(
        !recalled
            .to_string()
            .contains("RAW_WITNESS_MUST_STAY_IN_RECEIPT")
    );
    std::fs::write(root.path().join("a.py"), "def f():\n return 2\n").unwrap();
    let recalled = app
        .recall(&conn, &json!({"topic":"contract-note"}), 11)
        .unwrap();
    assert_eq!(recalled["finding"]["validity"]["state"], "stale");
    let before = embeddings.documents.get();
    assert!(
        app.remember(
            &conn,
            &json!({"topic":"reject-stale","content":"note","check_run":"application-memory-run"}),
            11
        )
        .is_err()
    );
    assert_eq!(embeddings.documents.get(), before);
}

#[test]
fn optional_checks_are_loaded_only_for_selected_checked_memories_and_fail_unknown() {
    let root = tempfile::tempdir().unwrap();
    let conn = db();
    let calls = Rc::new(Cell::new(0));
    let observe = calls.clone();
    let app = app(root.path(), Rc::new(Offline::default()), Rc::default()).with_checks_provider(
        move || {
            observe.set(observe.get() + 1);
            Err(knowledge::Error::Invalid(
                "explicit grammar manifest unavailable".into(),
            ))
        },
    );
    assert_eq!(
        app.remember(
            &conn,
            &json!({"topic":"ordinary","content":"No check dependency."}),
            10
        )
        .unwrap()["ok"],
        true
    );
    assert_eq!(
        app.recall(&conn, &json!({"topic":"ordinary","detail":"answer"}), 10)
            .unwrap()["memories"][0]["conclusion"],
        "No check dependency."
    );
    assert_eq!(calls.get(), 0);
    let justification = json!({"version":1,"kind":"observation","rationale":"Fixture-only checked note","evidence":[],"dependencies":[],"assumptions":[],"recheck":"rerun ken_check","check_runs":["missing-receipt"]});
    let id = conn
        .query_row(
            "SELECT id FROM cr_findings WHERE topic='ordinary'",
            [],
            |r| r.get::<_, i64>(0),
        )
        .unwrap();
    knowledge::records::save(&conn, id, Some(&justification)).unwrap();
    let result = app.recall(&conn, &json!({"topic":"ordinary"}), 11).unwrap();
    assert_eq!(calls.get(), 1);
    assert_eq!(result["finding"]["validity"]["state"], "unknown");
    assert!(
        result["finding"]["validity"]["issues"]
            .to_string()
            .contains("explicit grammar manifest unavailable")
    );
}
