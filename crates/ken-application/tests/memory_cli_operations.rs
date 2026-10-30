//! Application graph options share canonical memory policy without loading models.
use ken_application::knowledge::{FindingEmbeddings, KnowledgeApplication, SessionSignals};
use ken_knowledge as domain;
use rusqlite::Connection;
use serde_json::{Value, json};
use std::{cell::Cell, rc::Rc};
#[derive(Default)]
struct Offline(Cell<usize>);
impl FindingEmbeddings for Offline {
    fn embed_finding(&self, _: &Connection, _: &str, _: &str) -> Option<Vec<f32>> {
        None
    }
    fn embed_query(&self, _: &Connection, _: &str) -> domain::Result<Vec<f32>> {
        self.0.set(self.0.get() + 1);
        Err(domain::Error::Invalid("unexpected query model".into()))
    }
}
struct Signals;
impl SessionSignals for Signals {
    fn dismiss(&self, _: &str, _: &str) -> domain::Result<Value> {
        unreachable!()
    }
}
fn fixture() -> (
    tempfile::TempDir,
    ken_store::ProjectDatabase,
    KnowledgeApplication,
    Rc<Offline>,
) {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    let mut db = ken_store::ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    db.initialize().unwrap();
    let embeddings = Rc::new(Offline::default());
    let app =
        KnowledgeApplication::new(root.path(), embeddings.clone(), Rc::new(Signals), None).unwrap();
    (root, db, app, embeddings)
}
#[test]
fn related_explicit_weight_and_exact_topic_reuse_application_selection_without_query_model() {
    let (_root, db, app, embeddings) = fixture();
    for topic in ["first", "second"] {
        app.remember(
            db.connection(),
            &json!({"topic":topic,"content":"plain note"}),
            10,
        )
        .unwrap();
    }
    db.connection().execute("INSERT INTO cr_finding_edges(src,dst,edge_type,weight,evidence,updated_at) VALUES(1,2,'test_edge',0.65,'{}',10)",[]).unwrap();
    assert!(
        app.related_findings(db.connection(), "first", 8, 0.7, 20)
            .unwrap()["neighbors"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        app.related_findings(db.connection(), "first", 8, 0.6, 20)
            .unwrap()["neighbors"][0]["topic"],
        "second"
    );
    assert_eq!(embeddings.0.get(), 0);
    assert!(
        app.related_findings(db.connection(), "absent", 8, 0.3, 20)
            .is_err()
    );
    assert_eq!(embeddings.0.get(), 1);
}
#[test]
fn file_expand_and_rebuild_preserve_domain_refs_and_counts_without_query_encoding() {
    let (root, db, app, embeddings) = fixture();
    std::fs::create_dir(root.path().join("src")).unwrap();
    std::fs::write(root.path().join("src/a.rs"), "fn entry(){}\n").unwrap();
    db.connection()
        .execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at) VALUES('src/a.rs',x'',0,0)",
            [],
        )
        .unwrap();
    app.remember(
        db.connection(),
        &json!({"topic":"source-note","content":"See src/a.rs for entry behavior"}),
        10,
    )
    .unwrap();
    app.remember(
        db.connection(),
        &json!({"topic":"neighbor","content":"other note"}),
        11,
    )
    .unwrap();
    db.connection().execute("INSERT INTO cr_finding_edges(src,dst,edge_type,weight,evidence,updated_at) VALUES(1,2,'test_edge',0.65,'{}',10)",[]).unwrap();
    let direct = app
        .file_findings(db.connection(), "./src/a.rs", false, 15, 20)
        .unwrap();
    assert_eq!(direct["findings"][0]["topic"], "source-note");
    assert!(direct.get("related").is_none());
    let expanded = app
        .file_findings(db.connection(), "src/a.rs", true, 15, 20)
        .unwrap();
    assert_eq!(expanded["related"][0]["topic"], "neighbor");
    let rebuilt = app.rebuild_findings_graph(db.connection(), 30).unwrap();
    assert_eq!(rebuilt["ok"], true);
    assert_eq!(
        rebuilt["refs"],
        db.connection()
            .query_row("SELECT count(*) FROM cr_finding_refs", [], |r| r
                .get::<_, i64>(0))
            .unwrap()
    );
    assert_eq!(
        rebuilt["edges"],
        db.connection()
            .query_row("SELECT count(*) FROM cr_finding_edges", [], |r| r
                .get::<_, i64>(0))
            .unwrap()
    );
    assert!(db.connection().is_autocommit());
    assert_eq!(embeddings.0.get(), 0);
}

struct QueryVectors(Cell<usize>);
impl FindingEmbeddings for QueryVectors {
    fn embed_finding(&self, _: &Connection, _: &str, _: &str) -> Option<Vec<f32>> {
        None
    }
    fn embed_query(&self, _: &Connection, _: &str) -> domain::Result<Vec<f32>> {
        self.0.set(self.0.get() + 1);
        Ok(vec![1., 0.])
    }
}
#[test]
fn ordinary_semantic_recall_keeps_nonfinite_threshold_and_empty_query_semantics_in_domain() {
    let (root, db, _, _) = fixture();
    let vectors = Rc::new(QueryVectors(Cell::new(0)));
    let app =
        KnowledgeApplication::new(root.path(), vectors.clone(), Rc::new(Signals), None).unwrap();
    app.remember(
        db.connection(),
        &json!({"topic":"semantic","content":"stored vector"}),
        10,
    )
    .unwrap();
    let blob = [1f32, 0.]
        .iter()
        .flat_map(|x| x.to_le_bytes())
        .collect::<Vec<_>>();
    db.connection()
        .execute("UPDATE cr_findings SET embedding=?", [blob])
        .unwrap();
    assert!(
        app.recall_findings(db.connection(), "query", 5, Some(f64::INFINITY))
            .unwrap()
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        app.recall_findings(db.connection(), "query", 5, Some(0.25))
            .unwrap()[0]["topic"],
        "semantic"
    );
    assert_eq!(
        app.recall_findings(db.connection(), "", 5, Some(0.25))
            .unwrap()[0]["topic"],
        "semantic"
    );
    assert_eq!(
        vectors.0.get(),
        3,
        "explicit ordinary recall stays semantic even for an empty argument"
    );
}
