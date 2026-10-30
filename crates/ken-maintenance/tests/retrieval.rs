use ken_maintenance::RetrievalApplication;
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{DocumentEncoder, encoder::EncoderLoader};
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
use std::{path::PathBuf, rc::Rc, sync::Arc};
struct Encoder;
impl DocumentEncoder for Encoder {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(2)
    }
    fn token_count(&self, s: &str) -> ken_retrieval::Result<usize> {
        Ok(s.split_whitespace().count())
    }
    fn embed_passages(&self, t: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        Ok(t.iter().map(|_| vec![1., 0.]).collect())
    }
}
struct Loader;
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> ken_retrieval::Result<Rc<dyn DocumentEncoder>> {
        Ok(Rc::new(Encoder))
    }
}
fn grammar() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    )
}
fn runtime() -> LegacyRuntimeIdentity {
    let v: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/macos.json"
    ))
    .unwrap();
    LegacyRuntimeIdentity::from_json(&v["legacy_runtime"].to_string()).unwrap()
}
fn profile() -> RetrievalProfile {
    let spec = json!({"model_id":"test/provided","revision":"dddddddddddddddddddddddddddddddddddddddd","backend":"provided"});
    RetrievalProfile::from_json(&json!({"identity":spec,"behavior":spec}).to_string()).unwrap()
}
#[test]
fn explicit_profile_index_publishes_native_sources_views_and_reuses_upgrade_profile() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(
        root.path().join("code.py"),
        "def normalize(value):\n    return value.lower()\n",
    )
    .unwrap();
    let app = RetrievalApplication::new(grammar());
    let first = app
        .index(root.path(), Some(profile()), runtime(), Rc::new(Loader))
        .unwrap();
    assert!(first["passages"].as_u64().unwrap() > 0);
    assert!(first["profile_version"].is_string());
    assert!(root.path().join(".ken/meta.json").is_file());
    let conn = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    let stored: String = conn
        .query_row(
            "SELECT value FROM meta WHERE key='retrieval_profile'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let mut old: Value = serde_json::from_str(&stored).unwrap();
    old["representation_version"] = json!(2);
    conn.execute(
        "UPDATE meta SET value=? WHERE key='retrieval_profile'",
        [old.to_string()],
    )
    .unwrap();
    drop(conn);
    let second = app
        .index(root.path(), None, runtime(), Rc::new(Loader))
        .unwrap();
    assert_eq!(second["profile"]["representation_version"], 3);
    assert_eq!(first["profile_version"], second["profile_version"]);
}
#[test]
fn prepare_composes_indexer_and_existing_best_search_without_loading_empty_models() {
    struct NoModels;
    impl ken_search::SearchResourceProvider for NoModels {
        fn build(&self) -> ken_search::Result<ken_search::SearchResources> {
            panic!("empty preparation must stay cold")
        }
    }
    let root = tempfile::tempdir().unwrap();
    let app = RetrievalApplication::new(grammar());
    let mut best = ken_search::BestSearch::new(grammar(), Rc::new(NoModels));
    let report = app.prepare(root.path(), &mut best).unwrap();
    assert_eq!(report["indexed_files"], 0);
    assert_eq!(report["owners"], 0);
    assert!(root.path().join(".ken/meta.json").is_file());
    assert!(
        app.index(
            &root.path().join("missing"),
            Some(profile()),
            runtime(),
            Rc::new(Loader)
        )
        .is_err()
    );
}
