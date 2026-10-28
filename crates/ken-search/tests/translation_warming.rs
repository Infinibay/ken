//! Public preparation warms the registered translator on a real indexed project.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{IndexOptions, Indexer};
use ken_models::{
    AcquisitionPolicy, ArtifactCache, LegacyRuntimeIdentity, ModelCatalog, ModelFactory,
    NativeOnnxRuntime, NativeTranslationRuntime, PreparedModelResources,
};
use ken_retrieval::{PassagePolicy, rank_models::ProductionRankModels};
use ken_search::{BestSearch, RegisteredSearchResources};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::Value;
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};

#[test]
fn indexed_project_preparation_warms_the_registered_x86_translator() {
    let root = tempfile::tempdir().unwrap();
    let mut resources =
        PreparedModelResources::new(&root.path().join("owned"), &root.path().join("unused.npz"))
            .unwrap();
    let runtime: Value = serde_json::from_slice(
        &fs::read(std::env::var_os("KEN_CT2_PREPARATION").expect("prepare CT2 CPU module"))
            .unwrap(),
    )
    .unwrap();
    resources.translation = Some(
        NativeTranslationRuntime::from_json(
            &runtime["registration"].to_string(),
            Path::new(runtime["module_path"].as_str().unwrap()),
            Path::new(runtime["core_root"].as_str().unwrap()),
        )
        .unwrap(),
    );
    resources.onnx = Some(
        NativeOnnxRuntime::from_json(
            include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
            &PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()),
        )
        .unwrap(),
    );
    for (model, variable) in [
        ("minishlab/potion-code-16M-v2", "KEN_POTION_SOURCE"),
        ("mrsladoje/CodeRankEmbed-onnx-int8", "KEN_CONTEXT_SNAPSHOT"),
        ("cross-encoder/ettin-reranker-68m-v1", "KEN_ETTIN_SOURCE"),
        ("Prukario/opus-mt-es-en-ct2-int8", "KEN_TRANSLATION_SOURCE"),
    ] {
        resources.source_overrides.insert(
            model.into(),
            std::env::var_os(variable).expect(variable).into(),
        );
    }
    let factory = Arc::new(ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.path().join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    ));
    let expansion = factory.expansion().unwrap();
    assert!(!expansion.is_loaded());
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        &include_bytes!("../../ken-retrieval/tests/fixtures/best-search-reference.json.gz")[..],
    )
    .read_to_string(&mut raw)
    .unwrap();
    let fixture: Value = serde_json::from_str(&raw).unwrap();
    let original = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == "registered-symbol")
        .unwrap();
    let legacy: LegacyRuntimeIdentity =
        serde_json::from_value(original["input"]["models"]["legacy_runtime"].clone()).unwrap();
    let ranks = Arc::new(
        ProductionRankModels::open(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../ken-retrieval/resources/ranking"),
        )
        .unwrap(),
    );
    let provider = Rc::new(RegisteredSearchResources::new(factory, ranks, legacy));
    let grammars = GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepare grammars"),
    ))
    .unwrap();
    let context = DiscoveryContext {
        cwd: root.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(root.path(), &context).unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("main.db")).unwrap();
    db.initialize().unwrap();
    let mut engine = BestSearch::new(
        Arc::new(
            GrammarCatalog::prepared(&PathBuf::from(
                std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
            ))
            .unwrap(),
        ),
        provider,
    );
    assert_eq!(engine.prepare(&mut db, &paths).unwrap().indexed_files, 0);
    assert!(!expansion.is_loaded(), "an empty project stays cold");
    fs::write(
        root.path().join("source.py"),
        "def convert(value):\n    return str(value)\n",
    )
    .unwrap();
    let registry = ParserRegistry::new(grammars);
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
    let first = engine.prepare(&mut db, &paths).unwrap();
    assert_eq!(first.indexed_files, 1);
    assert!(first.owners > 0 && first.profile_version.is_some());
    assert!(expansion.is_loaded());
    let policy = expansion.runtime_identity().unwrap().unwrap();
    assert_eq!(policy.native_binding, Some("ken-translation/1"));
    assert_eq!(policy.observed_replicas, 1);
    let second = engine.prepare(&mut db, &paths).unwrap();
    assert_eq!(second.profile_version, first.profile_version);
    assert_eq!(second.owners, first.owners);
}
