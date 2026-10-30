use ken_application::embedding::{FindingVectorMath, IntentVectorAdapter, finding_embedding};
use ken_history::intent::IntentVectors;
use ken_knowledge::findings::VectorMath;
use ken_models::model_policy::{ModelPolicy, POTION_MODEL};
use ken_models::{AcquisitionPolicy, ArtifactCache, EncoderFamily, ModelCatalog, ModelFactory};
use ken_retrieval::{
    DocumentEncoder,
    project_embeddings::{
        ProjectEmbeddings, TransformerOverrides, configure_project, resolve_project,
    },
    query_encoder::QueryEncoder,
};
use ken_text::PythonText;
use rusqlite::Connection;
use serde_json::json;
use std::{cell::RefCell, path::Path, rc::Rc, sync::Arc};
fn factory(root: &Path) -> Arc<ModelFactory> {
    Arc::new(ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.join("cache")).unwrap(),
        ken_models::PreparedModelResources::new(&root.join("private"), &root.join("absent.npz"))
            .unwrap(),
        AcquisitionPolicy::Offline,
    ))
}
fn database() -> Connection {
    let db = Connection::open_in_memory().unwrap();
    db.execute_batch("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE ci_files(id INTEGER PRIMARY KEY,embedding BLOB,vec_slot INTEGER);").unwrap();
    db
}
#[test]
fn selected_embedding_owner_is_lazy_and_parses_only_selected_transformer_overrides() {
    let temp = tempfile::tempdir().unwrap();
    let factory = factory(temp.path());
    let overrides = TransformerOverrides {
        sequence_length: Some("not an integer".into()),
        batch_size: Some("also invalid".into()),
    };
    let potion = ProjectEmbeddings::new(factory.clone(), POTION_MODEL, overrides.clone());
    assert_eq!(potion.model(), POTION_MODEL);
    assert!(potion.embed_passages(&[]).unwrap().is_empty());
    let owner = potion.managed().unwrap();
    assert_eq!(owner.family(), EncoderFamily::Potion);
    assert!(!owner.is_prepared().unwrap());
    assert!(!temp.path().join("private").exists());
    let transformer =
        ProjectEmbeddings::new(factory.clone(), "Qwen/Qwen3-Embedding-0.6B", overrides);
    assert!(transformer.managed().is_err());
    let valid = ProjectEmbeddings::new(
        factory.clone(),
        "Qwen/Qwen3-Embedding-0.6B",
        TransformerOverrides {
            sequence_length: Some(" 256 ".into()),
            batch_size: Some("4".into()),
        },
    );
    let a = valid.managed().unwrap();
    let b = valid.managed().unwrap();
    assert!(Arc::ptr_eq(&a, &b));
    assert_eq!(a.family(), EncoderFamily::SentenceTransformer);
    assert!(!a.is_prepared().unwrap());
    assert!(!Arc::ptr_eq(
        &a,
        &factory.legacy_encoder("Qwen/Qwen3-Embedding-0.6B").unwrap()
    ));
    let text = PythonText::from_codepoints(vec![0xd800]).unwrap();
    assert!(potion.embed_query(&text).is_err());
    assert!(!owner.is_prepared().unwrap());
    assert!(!temp.path().join("private").exists());
}
#[test]
fn project_selection_preserves_file_vector_inference_overrides_and_fresh_pins() {
    let db = database();
    let policy = ModelPolicy::new(Some("configured/new"));
    let selected = configure_project(&db, &policy, Some("explicit/model")).unwrap();
    assert_eq!(selected.model, "explicit/model");
    assert_eq!(
        db.query_row("SELECT value FROM meta WHERE key='embed_model'", [], |r| {
            r.get::<_, String>(0)
        })
        .unwrap(),
        "explicit/model"
    );
    assert_eq!(
        db.query_row(
            "SELECT value FROM meta WHERE key='embed_doc_space'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "2"
    );
    db.execute(
        "UPDATE meta SET value='stored/model' WHERE key='embed_model'",
        [],
    )
    .unwrap();
    assert_eq!(
        resolve_project(&db, &policy, None).unwrap().model,
        "stored/model"
    );
    assert_eq!(
        resolve_project(&db, &policy, Some("override/model"))
            .unwrap()
            .model,
        "override/model"
    );
    let old = database();
    old.execute("INSERT INTO ci_files(id,vec_slot)VALUES(1,0)", [])
        .unwrap();
    assert_eq!(
        configure_project(&old, &policy, None).unwrap().model,
        ken_models::model_policy::LEGACY_MODEL
    );
    assert_eq!(
        old.query_row("SELECT count(*)FROM meta", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
    let empty = database();
    empty
        .execute("INSERT INTO meta VALUES('embed_model','')", [])
        .unwrap();
    let selected = configure_project(&empty, &policy, None).unwrap();
    assert_eq!(selected.model, "configured/new");
    assert!(selected.initial_pin.is_none());
    assert_eq!(
        empty
            .query_row("SELECT count(*)FROM meta", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
    let findings_only = database();
    findings_only
        .execute_batch(
            "CREATE TABLE cr_findings(embedding BLOB);INSERT INTO cr_findings VALUES(X'0000803f');",
        )
        .unwrap();
    assert_eq!(
        resolve_project(&findings_only, &policy, None)
            .unwrap()
            .model,
        "configured/new"
    );
    let readonly = database();
    readonly.execute_batch("PRAGMA query_only=ON").unwrap();
    assert!(configure_project(&readonly, &policy, None).is_err());
    assert_eq!(
        readonly
            .query_row("SELECT count(*)FROM meta", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        0
    );
}
struct Query {
    seen: RefCell<Vec<String>>,
}
impl QueryEncoder for Query {
    fn embed_query(&self, text: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.seen.borrow_mut().push(text.to_utf8().unwrap());
        Ok(vec![1., 0.])
    }
}
#[test]
fn history_and_finding_adapters_delegate_to_shared_numeric_owner() {
    let query = Rc::new(Query {
        seen: RefCell::new(vec![]),
    });
    let mut intent = IntentVectorAdapter::new(query.clone());
    let q = intent.embed_query("question").unwrap();
    assert_eq!(&*query.seen.borrow(), &["question"]);
    let ranked = intent
        .rank(&q, &[vec![1., 0.], vec![0., 1.], vec![-1., 0.]])
        .unwrap();
    assert_eq!(ranked.scores, vec![1., 0., -1.]);
    assert_eq!(ranked.order, vec![0, 1, 2]);
    assert!(intent.rank(&q, &[vec![1.]]).is_err());
    let math = FindingVectorMath::default();
    assert_eq!(math.query_norm(&[3., 4.]).unwrap(), 5.);
    assert_eq!(math.row_norm(&[3., 4.]).unwrap(), 5.);
    assert_eq!(math.scores(&[1., 0., 0., 1.], 2, &q).unwrap(), vec![1., 0.]);
    assert_eq!(
        math.symmetric_product(&[1., 0., 0., 1.], 2, 2).unwrap(),
        vec![1., 0., 0., 1.]
    );
    assert!(math.scores(&[], 1, &q).is_err());
}
struct Documents {
    seen: RefCell<Vec<String>>,
    fail: bool,
}
impl DocumentEncoder for Documents {
    fn dim(&self) -> ken_retrieval::Result<usize> {
        Ok(2)
    }
    fn token_count(&self, text: &str) -> ken_retrieval::Result<usize> {
        Ok(text.chars().count())
    }
    fn embed_passages(&self, texts: &[&str]) -> ken_retrieval::Result<Vec<Vec<f32>>> {
        self.seen
            .borrow_mut()
            .extend(texts.iter().map(|s| s.to_string()));
        if self.fail {
            Err(ken_retrieval::RetrievalError::Invalid(
                "offline embedding unavailable".into(),
            ))
        } else {
            Ok(texts.iter().map(|_| vec![1., 0.]).collect())
        }
    }
}
#[test]
fn finding_documents_use_passage_text_and_failure_never_loses_the_conclusion() {
    let docs = Documents {
        seen: RefCell::new(vec![]),
        fail: false,
    };
    let content = "😀".repeat(1025);
    assert_eq!(
        finding_embedding(&docs, " topic ", &content).unwrap(),
        vec![1., 0.]
    );
    assert_eq!(
        docs.seen.borrow()[0],
        format!("topic\n\n{}", "😀".repeat(1024))
    );
    assert!(finding_embedding(&docs, " ", "bad").is_none());
    assert_eq!(docs.seen.borrow().len(), 1);
    let unavailable = Documents {
        seen: RefCell::new(vec![]),
        fail: true,
    };
    let embedding = finding_embedding(&unavailable, "saved", "durable");
    assert!(embedding.is_none());
    let db = Connection::open_in_memory().unwrap();
    ken_knowledge::findings::ensure_schema(&db).unwrap();
    let result = ken_knowledge::findings::remember(
        &db,
        &json!({"topic":"saved","content":"durable"}),
        embedding.as_deref(),
        1,
        None,
        &[],
        &FindingVectorMath::default(),
    )
    .unwrap();
    assert_eq!(result["ok"], true);
    assert_eq!(
        db.query_row(
            "SELECT content FROM cr_findings WHERE topic='saved'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "durable"
    );
}
#[test]
fn installation_factory_does_not_load_grammars_rankers_or_optional_search_roles() {
    let temp = tempfile::tempdir().unwrap();
    let legacy: serde_json::Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/linux.json"
    ))
    .unwrap();
    let path = temp.path().join("installation.json");
    std::fs::write(&path,serde_json::to_vec(&json!({"format":"ken-search-installation/1","grammar_manifest":"missing-grammars.json","ranking_directory":"missing-rankers","private_parent":"private","cache_parent":"cache","bundled_npz":"missing.npz","sources":{},"acquisition":"offline","legacy_runtime":legacy["legacy_runtime"]})).unwrap()).unwrap();
    let factory = ken_search::SearchInstallation::open_model_factory(&path).unwrap();
    let encoder = factory.legacy_encoder(POTION_MODEL).unwrap();
    assert!(!encoder.is_prepared().unwrap());
    assert!(!temp.path().join("private").exists());
    assert!(!temp.path().join("missing-rankers").exists());
    assert!(!temp.path().join("missing-grammars.json").exists());
}
