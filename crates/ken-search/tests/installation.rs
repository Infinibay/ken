//! Deployment resources feed the same production engine used by native callers.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{IndexOptions, Indexer};
use ken_retrieval::{PassagePolicy, query::SearchRequest};
use ken_search::SearchInstallation;
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::{Value, json};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
};
#[path = "support/search_response.rs"]
mod response;
use response::real_response;

fn original() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        &include_bytes!("../../ken-retrieval/tests/fixtures/best-search-reference.json.gz")[..],
    )
    .read_to_string(&mut raw)
    .unwrap();
    let fixture: Value = serde_json::from_str(&raw).unwrap();
    fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == "registered-symbol")
        .unwrap()
        .clone()
}
fn manifest(directory: &Path) -> Value {
    fs::create_dir_all(directory.join("grammars")).unwrap();
    fs::copy(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        directory.join("grammars/manifest.json"),
    )
    .unwrap();
    json!({
        "format":"ken-search-installation/1",
        "grammar_manifest":"grammars/manifest.json", "ranking_directory":"ranks",
        "private_parent":"owned", "cache_parent":"cache", "bundled_npz":"unused.npz",
        "sources":{}, "acquisition":"offline",
        "legacy_runtime":original()["input"]["models"]["legacy_runtime"],
        "onnx_library":null, "translation":null,
    })
}
fn save(directory: &Path, manifest: &Value) -> PathBuf {
    let path = directory.join("installation.json");
    fs::write(&path, serde_json::to_vec(manifest).unwrap()).unwrap();
    path
}
fn project(root: &Path) -> (ProjectPaths, ProjectDatabase) {
    let paths = ProjectPaths::at(
        root,
        &DiscoveryContext {
            cwd: root.into(),
            forced_root: None,
            home: None,
        },
    )
    .unwrap();
    let mut db = ProjectDatabase::open(&root.join("project.db")).unwrap();
    db.initialize().unwrap();
    (paths, db)
}
fn index(db: &mut ProjectDatabase, paths: &ProjectPaths, files: &[PathBuf]) {
    let parsers = ParserRegistry::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    Indexer::new(&parsers)
        .index_files(
            db,
            paths,
            files,
            &IndexOptions {
                retrieval_policy: Some(PassagePolicy::default()),
                ..Default::default()
            },
            &mut |_: &str, _: &str| {},
        )
        .unwrap();
}

#[test]
fn relocated_installation_keeps_empty_and_exact_queries_cold_without_optional_files() {
    let root = tempfile::tempdir().unwrap();
    let before = root.path().join("before");
    let mut config = manifest(&before);
    config["onnx_library"] = json!("optional/missing-onnx.so");
    let runtime: Value = serde_json::from_slice(
        &fs::read(std::env::var_os("KEN_CT2_PREPARATION").unwrap()).unwrap(),
    )
    .unwrap();
    config["translation"] = json!({"registration":runtime["registration"],"module_path":"optional/missing-ct2.so","core_root":"optional"});
    save(&before, &config);
    let installed = root.path().join("relocated");
    fs::rename(&before, &installed).unwrap();
    // Only the grammar manifest exists: no grammar library, rank forest, model,
    // ONNX core or translation module may be needed for these cold paths.
    let mut engine = SearchInstallation::open(&installed.join("installation.json"))
        .unwrap()
        .into_search();
    let (paths, mut db) = project(root.path());
    let empty = engine
        .search(
            &mut db,
            &paths,
            &SearchRequest::new("find the code").unwrap(),
        )
        .unwrap();
    assert!(empty.results.is_empty());
    assert_eq!(empty.profile_version, "best-empty-source-v1");
    fs::write(
        root.path().join("source.py"),
        "def public_transport_unique(value):\n    return value + 3\n",
    )
    .unwrap();
    index(&mut db, &paths, &["source.py".into()]);
    let exact = engine
        .search(
            &mut db,
            &paths,
            &SearchRequest::new("public_transport_unique").unwrap(),
        )
        .unwrap();
    assert_eq!(exact.profile_version, "best-exact-source-v1");
    assert_eq!(exact.results.len(), 1);
    assert_eq!(
        exact.results[0].source().entity.qualname.as_deref(),
        Some("public_transport_unique")
    );
    assert!(
        exact.results[0]
            .source()
            .evidence
            .iter()
            .any(|e| e.content.contains("return value + 3"))
    );
    assert!(!installed.join("cache").exists());
    assert!(!installed.join("owned").exists());
}

#[test]
fn invalid_installation_is_rejected_before_creating_cache_or_model_directories() {
    let root = tempfile::tempdir().unwrap();
    let good = manifest(root.path());
    for change in [
        json!({"format":"ken-search-installation/2"}),
        json!({"unknown":true}),
        json!({"private_parent":""}),
        json!({"sources":{"minishlab/potion-code-16M-v2":""}}),
        json!({"acquisition":"floating"}),
        json!({"legacy_runtime":{}}),
        json!({"translation":{"registration":{},"module_path":"module.so","core_root":"core","unknown":true}}),
    ] {
        let mut config = good.clone();
        for (key, value) in change.as_object().unwrap() {
            config[key] = value.clone();
        }
        let path = save(root.path(), &config);
        assert!(SearchInstallation::open(&path).is_err(), "{change}");
        assert!(!root.path().join("cache").exists());
        assert!(!root.path().join("owned").exists());
    }
    let path = root.path().join("oversized.json");
    fs::write(&path, vec![b' '; 1024 * 1024 + 1]).unwrap();
    assert!(SearchInstallation::open(&path).is_err());
}

#[test]
fn installed_registered_models_retry_after_source_repair_and_match_original_search() {
    let root = tempfile::tempdir().unwrap();
    let mut config = manifest(root.path());
    let reference = original();
    config["ranking_directory"] =
        json!(Path::new(env!("CARGO_MANIFEST_DIR")).join("../ken-retrieval/resources/ranking"));
    config["onnx_library"] = json!(PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()));
    let runtime: Value = serde_json::from_slice(
        &fs::read(std::env::var_os("KEN_CT2_PREPARATION").unwrap()).unwrap(),
    )
    .unwrap();
    config["translation"] = json!({"registration":runtime["registration"],"module_path":runtime["module_path"],"core_root":runtime["core_root"]});
    for (model, variable) in [
        ("minishlab/potion-code-16M-v2", "KEN_POTION_SOURCE"),
        ("mrsladoje/CodeRankEmbed-onnx-int8", "KEN_CONTEXT_SNAPSHOT"),
        ("cross-encoder/ettin-reranker-68m-v1", "KEN_ETTIN_SOURCE"),
        ("Prukario/opus-mt-es-en-ct2-int8", "KEN_TRANSLATION_SOURCE"),
    ] {
        config["sources"][model] = json!(PathBuf::from(std::env::var_os(variable).unwrap()));
    }
    let source = PathBuf::from(std::env::var_os("KEN_POTION_SOURCE").unwrap());
    let repair = root
        .path()
        .join("initially-missing")
        .join(source.file_name().unwrap());
    config["sources"]["minishlab/potion-code-16M-v2"] = json!(repair);
    let mut engine = SearchInstallation::open(&save(root.path(), &config))
        .unwrap()
        .into_search();
    let (paths, mut db) = project(root.path());
    let files = reference["input"]["projects"][0]["files"]
        .as_object()
        .unwrap();
    let mut names = Vec::new();
    for (name, text) in files {
        let path = root.path().join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text.as_str().unwrap()).unwrap();
        names.push(name.into());
    }
    index(&mut db, &paths, &names);
    let request: SearchRequest =
        serde_json::from_value(reference["input"]["actions"][0]["request"].clone()).unwrap();
    assert!(engine.search(&mut db, &paths, &request).is_err());
    fs::create_dir_all(&repair).unwrap();
    for item in fs::read_dir(&source).unwrap() {
        let item = item.unwrap();
        if item.path().is_file() {
            fs::hard_link(
                fs::canonicalize(item.path()).unwrap(),
                repair.join(item.file_name()),
            )
            .unwrap();
        }
    }
    let response = engine.search(&mut db, &paths, &request).unwrap();
    real_response(
        &serde_json::to_value(&response).unwrap(),
        &reference["events"][0]["result"],
        "installed original",
    );
    let repeated = engine.search(&mut db, &paths, &request).unwrap();
    real_response(
        &serde_json::to_value(repeated).unwrap(),
        &serde_json::to_value(response).unwrap(),
        "repeated",
    );
}
