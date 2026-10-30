//! Watcher maintenance must preserve the profile activated by foreground search.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_daemon::{
    native::{IndexResources, IndexRetrieval},
    queue::{Action, Batch},
};
use ken_index::{IndexOptions, Indexer, VectorStorage, changes::content_hash};
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, LexicalCounter, Result, TokenCounter,
    embedding_store::load_vectors,
    encoder::EncoderLoader,
    projections::{View, index_embeddings, stored_profile},
    representations::bounded_passage_text,
    storage::load_passage_map,
};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::{Value, json};
use std::{
    fs,
    path::PathBuf,
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
};

#[derive(Default)]
struct Calls {
    loads: AtomicUsize,
    encodes: AtomicUsize,
    reject_loads: AtomicBool,
}

struct TinyEncoder {
    calls: Arc<Calls>,
    behavior: bool,
}
impl TinyEncoder {
    fn vector(&self, text: &str) -> Vec<f32> {
        let changed = if text.contains("added") {
            3.
        } else if text.contains("after") {
            2.
        } else {
            1.
        };
        vec![if self.behavior { 2. } else { 1. }, changed, 1.]
    }
}
impl DocumentEncoder for TinyEncoder {
    fn dim(&self) -> Result<usize> {
        Ok(3)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        LexicalCounter.count(text)
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        self.calls.encodes.fetch_add(1, Ordering::SeqCst);
        Ok(texts.iter().map(|text| self.vector(text)).collect())
    }
}
struct TinyLoader(Arc<Calls>);
impl EncoderLoader for TinyLoader {
    fn load(&self, spec: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        self.0.loads.fetch_add(1, Ordering::SeqCst);
        if self.0.reject_loads.load(Ordering::SeqCst) {
            return Err(ken_retrieval::RetrievalError::Invalid(
                "unchanged maintenance unexpectedly loaded an encoder".into(),
            ));
        }
        Ok(Rc::new(TinyEncoder {
            calls: self.0.clone(),
            behavior: spec.model_id == "provided/behavior",
        }))
    }
}
fn runtime() -> LegacyRuntimeIdentity {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/linux.json"
    ))
    .unwrap();
    LegacyRuntimeIdentity::from_json(&fixture["legacy_runtime"].to_string()).unwrap()
}
fn profile() -> RetrievalProfile {
    RetrievalProfile::from_json(
        &json!({
            "identity": {"model_id":"provided/identity", "revision":"a".repeat(40), "backend":"provided"},
            "behavior": {"model_id":"provided/behavior", "revision":"b".repeat(40), "backend":"provided"},
            "max_tokens":64
        })
        .to_string(),
    )
    .unwrap()
}
fn symbols(db: &ProjectDatabase) -> Vec<String> {
    db.connection()
        .prepare("SELECT qualname FROM ci_symbols ORDER BY qualname")
        .unwrap()
        .query_map([], |row| row.get(0))
        .unwrap()
        .collect::<rusqlite::Result<_>>()
        .unwrap()
}
fn assert_current_vectors(db: &ProjectDatabase, profile: &RetrievalProfile) {
    let mut passages = load_passage_map(db.connection(), None).unwrap();
    passages.sort_by_key(|(id, _)| *id);
    assert!(!passages.is_empty());
    for view in View::ALL {
        let revision = profile.vector_revision(view.as_str(), &runtime()).unwrap();
        let vectors = load_vectors(db.connection(), view.as_str(), &revision).unwrap();
        assert_eq!(
            vectors.ids,
            passages.iter().map(|(id, _)| *id).collect::<Vec<_>>()
        );
        let encoder = TinyEncoder {
            calls: Arc::new(Calls::default()),
            behavior: view == View::Behavior,
        };
        for ((_, passage), actual) in passages.iter().zip(vectors.matrix) {
            let text = bounded_passage_text(passage, view, profile, &encoder).unwrap();
            let raw = encoder.vector(&text);
            let norm = raw.iter().map(|n| n * n).sum::<f32>().sqrt();
            assert_eq!(actual.len(), raw.len());
            for (actual, expected) in actual.iter().zip(raw) {
                assert!((actual - expected / norm).abs() < 1e-6, "{view:?}: {text}");
            }
        }
    }
}

#[test]
fn active_profile_survives_watcher_edit_unchanged_and_delete() {
    let root = tempfile::tempdir().unwrap();
    let paths = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            home: Some(root.path().into()),
            forced_root: None,
        },
    )
    .unwrap();
    fs::create_dir_all(paths.db().parent().unwrap()).unwrap();
    let mut db = ProjectDatabase::open(&paths.db()).unwrap();
    db.initialize().unwrap();
    let grammar_manifest = PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("explicit prepared grammars"),
    );
    let parsers = ParserRegistry::new(GrammarCatalog::prepared(&grammar_manifest).unwrap());
    let calls = Arc::new(Calls::default());
    let legacy_calls = Arc::new(Calls::default());
    let legacy = Arc::new(TinyEncoder {
        calls: legacy_calls.clone(),
        behavior: false,
    });
    let profile = profile();
    fs::write(
        root.path().join("client.py"),
        "def before(value):\n    return value\n",
    )
    .unwrap();
    Indexer::new(&parsers)
        .index_files(
            &mut db,
            &paths,
            &[PathBuf::from("client.py")],
            &IndexOptions {
                vector_storage: VectorStorage::Inline,
                workers: Some(0),
                legacy_encoder: Some(legacy.as_ref()),
                legacy_model: Some("provided/legacy"),
                retrieval_profile: Some(profile.clone()),
                retrieval_loader: Some(Rc::new(TinyLoader(calls.clone()))),
                legacy_runtime: Some(runtime()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )
        .unwrap();
    // This is the real publication used when foreground retrieval activates a profile.
    index_embeddings(
        &mut db,
        profile.clone(),
        runtime(),
        Rc::new(TinyLoader(calls.clone())),
    )
    .unwrap();
    assert_eq!(symbols(&db), ["before"]);
    let active = stored_profile(db.connection()).unwrap();
    assert_eq!(
        active.fingerprint.as_deref(),
        Some(profile.fingerprint(&runtime()).unwrap().as_str())
    );
    assert_current_vectors(&db, &profile);
    let before = load_passage_map(db.connection(), None).unwrap();
    let loader_calls = calls.clone();
    let maintenance = IndexResources {
        grammar_manifest,
        model: "provided/legacy".into(),
        encoder: legacy,
        retrieval: Some(IndexRetrieval {
            runtime: runtime(),
            encoder_loader: Box::new(move || Rc::new(TinyLoader(loader_calls))),
        }),
    }
    .maintenance(root.path());
    let mut worker = (maintenance.factory)().unwrap();
    let edited = "def after(value):\n    return value + 1\n\ndef added():\n    return 2\n";
    fs::write(root.path().join("client.py"), edited).unwrap();
    let reindex = Batch {
        resync: false,
        events: vec![("client.py".into(), Action::Reindex)],
    };
    let prior_loads = calls.loads.load(Ordering::SeqCst);
    worker.apply(&reindex).unwrap();
    assert!(calls.loads.load(Ordering::SeqCst) > prior_loads);
    assert_eq!(symbols(&db), ["added", "after"]);
    let stored_hash: Vec<u8> = db
        .connection()
        .query_row(
            "SELECT content_hash FROM ci_files WHERE path='client.py'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(stored_hash, content_hash(edited.as_bytes()));
    let passages = load_passage_map(db.connection(), None).unwrap();
    assert!(
        passages
            .iter()
            .all(|(_, passage)| passage.source_hash != before[0].1.source_hash)
    );
    assert_eq!(stored_profile(db.connection()).unwrap(), active);
    assert_current_vectors(&db, &profile);

    let unchanged_vectors = View::ALL.map(|view| {
        load_vectors(
            db.connection(),
            view.as_str(),
            &profile.vector_revision(view.as_str(), &runtime()).unwrap(),
        )
        .unwrap()
    });
    let counts = (
        calls.loads.load(Ordering::SeqCst),
        calls.encodes.load(Ordering::SeqCst),
        legacy_calls.encodes.load(Ordering::SeqCst),
    );
    calls.reject_loads.store(true, Ordering::SeqCst);
    worker.apply(&reindex).unwrap();
    assert_eq!(
        counts,
        (
            calls.loads.load(Ordering::SeqCst),
            calls.encodes.load(Ordering::SeqCst),
            legacy_calls.encodes.load(Ordering::SeqCst),
        )
    );
    for (view, expected) in View::ALL.into_iter().zip(unchanged_vectors) {
        assert_eq!(
            load_vectors(db.connection(), view.as_str(), &expected.model_revision).unwrap(),
            expected
        );
    }
    assert_eq!(stored_profile(db.connection()).unwrap(), active);

    fs::remove_file(root.path().join("client.py")).unwrap();
    worker
        .apply(&Batch {
            resync: false,
            events: vec![("client.py".into(), Action::Delete)],
        })
        .unwrap();
    for table in [
        "ci_files",
        "ci_symbols",
        "ci_passages",
        "ci_passage_vectors",
        "ci_retrieval_files",
    ] {
        let count: i64 = db
            .connection()
            .query_row(&format!("SELECT count(*) FROM {table}"), [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, 0, "deleted source retained {table}");
    }
    assert_eq!(calls.loads.load(Ordering::SeqCst), counts.0);
    assert_eq!(stored_profile(db.connection()).unwrap(), active);
}
