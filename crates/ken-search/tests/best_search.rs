use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{IndexOptions, Indexer};
use ken_retrieval::{PassagePolicy, query::SearchRequest};
use ken_search::{BestSearch, Result, SearchResourceProvider, SearchResources};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use std::{path::PathBuf, rc::Rc, sync::Arc};
#[path = "support/search_response.rs"]
mod response;
use response::real_response;
struct NoResources;
impl SearchResourceProvider for NoResources {
    fn build(&self) -> Result<SearchResources> {
        panic!("cold path must not construct resources")
    }
}
fn grammars() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar manifest"),
    ))
    .unwrap()
}
#[test]
fn empty_and_exact_source_paths_do_not_construct_resources() {
    let root = tempfile::tempdir().unwrap();
    let context = DiscoveryContext {
        cwd: root.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(root.path(), &context).unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("main.db")).unwrap();
    db.initialize().unwrap();
    let mut engine = BestSearch::new(Arc::new(grammars()), Rc::new(NoResources));
    let query = SearchRequest::new("convert").unwrap();
    let empty = engine.search(&mut db, &paths, &query).unwrap();
    assert!(empty.results.is_empty());
    assert_eq!(empty.profile_version, "best-empty-source-v1");
    std::fs::write(
        root.path().join("source.py"),
        "def convert(value):\n    return str(value)\n",
    )
    .unwrap();
    let registry = ParserRegistry::new(grammars());
    Indexer::new(&registry)
        .index_files(
            &mut db,
            &paths,
            &["source.py".into()],
            &IndexOptions {
                retrieval_policy: Some(PassagePolicy::default()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )
        .unwrap();
    let exact = engine.search(&mut db, &paths, &query).unwrap();
    assert_eq!(exact.profile_version, "best-exact-source-v1");
    let source = exact.results[0].source();
    assert_eq!(source.path, "source.py");
    assert_eq!(source.entity.qualname.as_deref(), Some("convert"));
    assert!(
        source
            .evidence
            .iter()
            .any(|e| e.content.contains("return str(value)"))
    );
    let vectors: i64 = db
        .connection()
        .query_row("SELECT COUNT(*) FROM ci_passage_vectors", [], |r| r.get(0))
        .unwrap();
    assert_eq!(vectors, 0);
}

#[path = "../examples/support/best_search.rs"]
mod histories;
#[test]
fn complete_controlled_endpoint_histories_match_original() {
    use std::io::Read;
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        &include_bytes!("../../ken-retrieval/tests/fixtures/best-search-reference.json.gz")[..],
    )
    .read_to_string(&mut raw)
    .unwrap();
    let fixture: serde_json::Value = serde_json::from_str(&raw).unwrap();
    let grammar = Arc::new(grammars());
    for row in fixture["cases"].as_array().unwrap() {
        if row["input"]["models"]["kind"] != "controlled" {
            continue;
        }
        let input = serde_json::from_str(&row["input"].to_string()).unwrap();
        let actual = histories::observe(input, grammar.clone(), None).unwrap();
        assert_eq!(actual, row["events"], "{}", row["id"]);
    }
}

fn corpus() -> serde_json::Value {
    use std::io::Read;
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        &include_bytes!("../../ken-retrieval/tests/fixtures/best-search-reference.json.gz")[..],
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn registered(
    root: &std::path::Path,
    legacy: ken_models::LegacyRuntimeIdentity,
    with_sources: bool,
) -> Rc<ken_search::RegisteredSearchResources> {
    use ken_models::{
        AcquisitionPolicy, ArtifactCache, ModelCatalog, ModelFactory, NativeOnnxRuntime,
        PreparedModelResources,
    };
    let mut resources =
        PreparedModelResources::new(&root.join("owned"), &root.join("unused.npz")).unwrap();
    resources.onnx = Some(
        NativeOnnxRuntime::from_json(
            include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
            &PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()),
        )
        .unwrap(),
    );
    if with_sources {
        for (name, env) in [
            ("minishlab/potion-code-16M-v2", "KEN_POTION_SOURCE"),
            ("mrsladoje/CodeRankEmbed-onnx-int8", "KEN_CONTEXT_SNAPSHOT"),
            ("cross-encoder/ettin-reranker-68m-v1", "KEN_ETTIN_SOURCE"),
        ] {
            resources.source_overrides.insert(
                name.into(),
                PathBuf::from(std::env::var_os(env).expect(env)),
            );
        }
    }
    let factory = Arc::new(ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    ));
    let models = Arc::new(
        ken_retrieval::rank_models::ProductionRankModels::open(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("../ken-retrieval/resources/ranking"),
        )
        .unwrap(),
    );
    Rc::new(ken_search::RegisteredSearchResources::new(
        factory, models, legacy,
    ))
}
#[test]
fn registered_assembly_preserves_original_static_feature_identity() {
    let fixture = corpus();
    let models = &fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "registered-symbol")
        .unwrap()["input"]["models"];
    let legacy = serde_json::from_value(models["legacy_runtime"].clone()).unwrap();
    let root = tempfile::tempdir().unwrap();
    let provider = registered(root.path(), legacy, true);
    let inputs = provider.inputs().unwrap();
    assert_eq!(
        serde_json::to_value(&inputs.base_profile).unwrap(),
        models["base_profile"]
    );
    assert_eq!(
        inputs.profile.fingerprint(&inputs.legacy).unwrap(),
        fixture["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == "registered-symbol")
            .unwrap()["events"][0]["result"]["profile_version"]
            .as_str()
            .unwrap()
    );
    let resources = SearchResources::new(inputs).unwrap();
    assert_eq!(
        resources
            .profile()
            .evidence
            .as_ref()
            .unwrap()
            .feature_version,
        3
    );
    assert!(
        !root.path().join("owned").exists(),
        "context, neural and translation sources stay lazy"
    );
}

#[test]
fn production_best_search_matches_three_original_model_histories() {
    let fixture = corpus();
    let rows = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|r| r["input"]["models"]["kind"] == "registered")
        .collect::<Vec<_>>();
    assert_eq!(rows.len(), 3);
    let legacy =
        serde_json::from_value(rows[0]["input"]["models"]["legacy_runtime"].clone()).unwrap();
    let root = tempfile::tempdir().unwrap();
    let provider = registered(root.path(), legacy, true);
    let grammar = Arc::new(grammars());
    for row in rows {
        let provider = provider.clone();
        let input = serde_json::from_str(&row["input"].to_string()).unwrap();
        let actual = histories::observe(
            input,
            grammar.clone(),
            Some(Rc::new(move || provider.inputs())),
        )
        .unwrap();
        real_response(&actual, &row["events"], &row["id"].to_string());
    }
}
#[test]
fn independent_unnamed_databases_never_share_a_prepared_catalog() {
    let root = tempfile::tempdir().unwrap();
    let paths = ProjectPaths::at(
        root.path(),
        &DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let grammar = Arc::new(grammars());
    let registry = ParserRegistry::with_shared_catalog(grammar.clone());
    let input = serde_json::from_str(&corpus()["cases"][0]["input"].to_string()).unwrap();
    let mut engine = BestSearch::new(grammar, histories::controlled_provider(input));
    let mut databases = Vec::new();
    for (path, text) in [
        ("a.py", "def store(key,value):\n    mapping[key]=value\n"),
        ("b.py", "def read(key):\n    return mapping[key]\n"),
    ] {
        std::fs::write(root.path().join(path), text).unwrap();
        let mut db = ProjectDatabase::open(std::path::Path::new(":memory:")).unwrap();
        db.initialize().unwrap();
        Indexer::new(&registry)
            .index_files(
                &mut db,
                &paths,
                &[path.into()],
                &IndexOptions {
                    retrieval_policy: Some(PassagePolicy::default()),
                    ..Default::default()
                },
                &mut |_: &str, _: &str| {},
            )
            .unwrap();
        databases.push(db);
    }
    let request = SearchRequest::new("Where is a mapping changed?").unwrap();
    for (i, path) in [(0, "a.py"), (1, "b.py"), (0, "a.py")] {
        let response = engine.search(&mut databases[i], &paths, &request).unwrap();
        assert_eq!(response.results.len(), 1);
        assert_eq!(response.results[0].source().path, path);
    }
    assert!(
        engine.cached_projects().is_empty(),
        "unnamed databases have no stable cache identity"
    );
}
#[test]
fn incoherent_context_or_word_policies_are_rejected_before_source_preparation() {
    let fixture = corpus();
    let row = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "registered-symbol")
        .unwrap();
    let legacy = serde_json::from_value(row["input"]["models"]["legacy_runtime"].clone()).unwrap();
    let root = tempfile::tempdir().unwrap();
    let provider = registered(root.path(), legacy, true);
    let mut inputs = provider.inputs().unwrap();
    inputs.profile.contextual.as_mut().unwrap().view_model = None;
    assert!(SearchResources::new(inputs).is_err());
    let mut inputs = provider.inputs().unwrap();
    inputs.profile.evidence.as_mut().unwrap().word_model = inputs.base_profile.identity.clone();
    assert!(SearchResources::new(inputs).is_err());
    assert!(!root.path().join("owned").exists());
}
