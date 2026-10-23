use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{
    DocumentEncoder, IndexOptions, Indexer, VectorStorage,
    changes::{content_hash, is_unchanged},
    delete_file, delete_path,
    parse_batch::worker_count,
};
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    LexicalCounter, PassagePolicy, Result, TokenCounter, encoder::EncoderLoader,
    projections::index_embeddings, storage::load_passage_map,
};
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    fs,
    path::{Path, PathBuf},
    rc::Rc,
};
fn registry() -> ParserRegistry {
    ParserRegistry::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammars"),
        ))
        .unwrap(),
    )
}
fn project() -> (tempfile::TempDir, ProjectPaths, ProjectDatabase) {
    let root = tempfile::tempdir().unwrap();
    let context = DiscoveryContext {
        cwd: root.path().into(),
        home: Some(root.path().into()),
        forced_root: None,
    };
    let paths = ProjectPaths::at(root.path(), &context).unwrap();
    fs::create_dir_all(paths.db().parent().unwrap()).unwrap();
    let mut db = ProjectDatabase::open(&paths.db()).unwrap();
    db.initialize().unwrap();
    (root, paths, db)
}
fn write(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, text).unwrap();
}
fn files(names: &[&str]) -> Vec<PathBuf> {
    names.iter().map(PathBuf::from).collect()
}
fn quiet(_: &str, _: &str) {}
fn count(db: &ProjectDatabase, table: &str) -> i64 {
    db.connection()
        .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))
        .unwrap()
}
#[derive(Default)]
struct Encoder {
    calls: RefCell<Vec<Vec<String>>>,
    loads: Cell<usize>,
    fail_load: Cell<bool>,
    action: RefCell<Option<Box<dyn Fn()>>>,
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> Result<usize> {
        Ok(3)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        LexicalCounter.count(text)
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        self.calls
            .borrow_mut()
            .push(texts.iter().map(|s| s.to_string()).collect());
        if let Some(action) = self.action.borrow_mut().take() {
            action()
        }
        Ok(texts
            .iter()
            .map(|s| {
                if s.contains("cookie") {
                    vec![1., 0., 0.]
                } else {
                    vec![0., 1., 0.]
                }
            })
            .collect())
    }
}
struct Loader(Rc<Encoder>);
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        self.0.loads.set(self.0.loads.get() + 1);
        if self.0.fail_load.get() {
            return Err(ken_retrieval::RetrievalError::Invalid(
                "unexpected model load".into(),
            ));
        }
        Ok(self.0.clone())
    }
}
fn profile() -> RetrievalProfile {
    RetrievalProfile::from_json(&json!({"identity":{"model_id":"provided","revision":"a".repeat(40),"backend":"provided"},"behavior":{"model_id":"provided","revision":"a".repeat(40),"backend":"provided"},"max_tokens":64}).to_string()).unwrap()
}
fn runtime() -> LegacyRuntimeIdentity {
    let v: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/macos.json"
    ))
    .unwrap();
    LegacyRuntimeIdentity::from_json(&v["legacy_runtime"].to_string()).unwrap()
}
#[test]
fn initial_edit_delete_and_unchanged_match_original() {
    let (root, paths, mut db) = project();
    write(root.path(), "pkg/util.py", "def helper():\n    return 1\n");
    write(
        root.path(),
        "app.py",
        "import pkg.util\ndef outer():\n    def inner(): return 1\n    return inner\n",
    );
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let options = IndexOptions {
        vector_storage: VectorStorage::Inline,
        workers: Some(0),
        ..Default::default()
    };
    let rels = files(&["pkg/util.py", "app.py"]);
    let first = index
        .index_files(&mut db, &paths, &rels, &options, &mut quiet)
        .unwrap();
    assert_eq!(
        (first.visited, first.parsed, first.symbols, first.imports),
        (2, 2, 3, 1)
    );
    assert_eq!(count(&db, "ci_files"), 2);
    assert_eq!(
        db.connection()
            .query_row("SELECT resolution FROM ci_imports", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "internal"
    );
    let again = index
        .index_files(&mut db, &paths, &rels, &options, &mut quiet)
        .unwrap();
    assert_eq!((again.unchanged, again.parsed), (2, 0));
    write(
        root.path(),
        "app.py",
        "import pkg.util\ndef changed():\n    return 'cookie'\n",
    );
    assert_eq!(
        index
            .index_files(&mut db, &paths, &files(&["app.py"]), &options, &mut quiet)
            .unwrap()
            .parsed,
        1
    );
    assert!(
        !load_passage_map(db.connection(), None)
            .unwrap()
            .iter()
            .any(|(_, p)| p.entity.qualname.as_deref() == Some("outer.inner"))
    );
    assert!(delete_file(db.connection(), "pkg/util.py").unwrap());
    index
        .index_files(&mut db, &paths, &[], &options, &mut quiet)
        .unwrap();
    assert_eq!(
        db.connection()
            .query_row("SELECT resolution FROM ci_imports", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "external"
    );
    assert_eq!(delete_path(db.connection(), "app.py").unwrap(), 1);
    assert_eq!(count(&db, "ci_passages"), 0);
    let expected = [
        0xbd, 0xdd, 0x81, 0x3c, 0x63, 0x42, 0x39, 0x72, 0x31, 0x71, 0xef, 0x3f, 0xee, 0x98, 0x57,
        0x9b, 0x94, 0x96, 0x4e, 0x3b, 0xb1, 0xcb, 0x3e, 0x42, 0x72, 0x62, 0xc8, 0xc0, 0x68, 0xd5,
        0x23, 0x19,
    ];
    assert_eq!(content_hash(b"abc"), expected);
}
#[test]
fn plain_rows_publish_first_progress_stays_ordered() {
    let (root, paths, mut db) = project();
    write(root.path(), "first.py", "def first():pass\n");
    write(root.path(), "README.md", "# Purpose\nA document.\n");
    write(root.path(), "big.py", &"x=1\n".repeat(40));
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let options = IndexOptions {
        vector_storage: VectorStorage::Inline,
        max_file_bytes: 40,
        workers: Some(0),
        ..Default::default()
    };
    let mut events = Vec::new();
    let stats = index
        .index_files(
            &mut db,
            &paths,
            &files(&["first.py", "README.md", "missing.py", "big.py"]),
            &options,
            &mut |p: &str, s: &str| events.push((p.to_string(), s.to_string())),
        )
        .unwrap();
    assert_eq!(
        (
            stats.visited,
            stats.parsed,
            stats.skipped_no_lang,
            stats.skipped_io_error,
            stats.skipped_too_large
        ),
        (4, 1, 1, 1, 1)
    );
    assert_eq!(
        events,
        vec![
            ("first.py".into(), "indexed".into()),
            ("README.md".into(), "indexed:noparse".into()),
            ("missing.py".into(), "skipped:io_error".into()),
            ("big.py".into(), "skipped:too_large".into())
        ]
    );
    let first: String = db
        .connection()
        .query_row("SELECT path FROM ci_files ORDER BY id LIMIT 1", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(first, "README.md");
}
#[test]
fn worker_counts_and_parse_failures() {
    assert_eq!(worker_count(1, 16, None), 0);
    assert_eq!(worker_count(64, 16, None), 2);
    assert_eq!(worker_count(10000, 16, None), 8);
    assert_eq!(worker_count(10000, 1, None), 0);
    assert_eq!(worker_count(10000, 16, Some("-3")), 0);
    assert_eq!(worker_count(1, 16, Some("3")), 3);
    assert_eq!(worker_count(1, 16, Some("garbage")), 0);
    assert_eq!(worker_count(1, 16, Some(" +٣_٢ ")), 32);
    assert_eq!(worker_count(1, 16, Some("1__2")), 0);
    let (root, paths, mut db) = project();
    let errors: Value = serde_json::from_str(include_str!(
        "../../ken-syntax/tests/fixtures/parser-errors.json"
    ))
    .unwrap();
    let c = &errors["cases"][0];
    let hex = c["source_hex"].as_str().unwrap();
    let source: Vec<_> = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
        .collect();
    fs::write(root.path().join("broken.ts"), source).unwrap();
    write(root.path(), "valid.py", "def valid():pass\n");
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let options = IndexOptions {
        workers: Some(4),
        ..Default::default()
    };
    let mut events = Vec::new();
    let stats = index
        .index_files(
            &mut db,
            &paths,
            &files(&["broken.ts", "valid.py"]),
            &options,
            &mut |p: &str, s: &str| events.push((p.to_string(), s.to_string())),
        )
        .unwrap();
    assert_eq!((stats.parsed, stats.skipped_io_error), (1, 1));
    assert_eq!(events[0].1, "skipped:parse_error");
}
#[test]
fn stale_parser_policy_and_name_tokens() {
    let (root, paths, mut db) = project();
    write(root.path(), "scheduler.py", "def parse_cache():return 1\n");
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let rels = files(&["scheduler.py"]);
    let options = IndexOptions::default();
    index
        .index_files(&mut db, &paths, &rels, &options, &mut quiet)
        .unwrap();
    let before = count(&db, "ci_name_tokens");
    assert!(before > 0);
    db.connection()
        .execute("DELETE FROM ci_name_tokens", [])
        .unwrap();
    db.set_meta("name_token_version", "0").unwrap();
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .unchanged,
        1
    );
    assert_eq!(count(&db, "ci_name_tokens"), before);
    db.connection()
        .execute("UPDATE ci_files SET parser_version=0", [])
        .unwrap();
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .parsed,
        1
    );
    let options = IndexOptions {
        retrieval_policy: Some(PassagePolicy::new(8, "custom-policy").unwrap()),
        ..Default::default()
    };
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .parsed,
        1
    );
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .unchanged,
        1
    );
    assert!(
        !is_unchanged(
            db.connection(),
            "scheduler.py",
            &content_hash(&fs::read(root.path().join("scheduler.py")).unwrap()),
            true,
            10,
            options.retrieval_policy.as_ref().unwrap()
        )
        .unwrap()
    );
}
#[test]
fn chunk_boundary_and_import_target_deletion() {
    let (root, paths, mut db) = project();
    for i in 0..5 {
        write(
            root.path(),
            &format!("m{i}.py"),
            &format!("def f{i}():return {i}\n"),
        );
    }
    let rels: Vec<_> = (0..5).map(|i| PathBuf::from(format!("m{i}.py"))).collect();
    let encoder = Encoder::default();
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let options = IndexOptions {
        chunk_files: 2,
        workers: Some(4),
        legacy_encoder: Some(&encoder),
        vector_storage: VectorStorage::Inline,
        ..Default::default()
    };
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .parsed,
        5
    );
    assert_eq!(
        encoder
            .calls
            .borrow()
            .iter()
            .map(Vec::len)
            .collect::<Vec<_>>(),
        vec![4, 4, 2]
    );
    assert_eq!(count(&db, "ci_files"), 5);
    let before = encoder.calls.borrow().len();
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .unchanged,
        5
    );
    assert_eq!(encoder.calls.borrow().len(), before);
    assert_eq!(delete_path(db.connection(), "m0.py").unwrap(), 1);
}
#[test]
fn all_languages_use_accepted_native_parsers() {
    let (root, paths, mut db) = project();
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/publication-reference.json")).unwrap();
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let mut languages = std::collections::BTreeSet::new();
    for c in fixture["cases"].as_array().unwrap() {
        let i = &c["input"];
        let Some(lang) = i["language"].as_str() else {
            continue;
        };
        languages.insert(lang);
        let path = i["path"].as_str().unwrap();
        let file = root.path().join(path);
        fs::create_dir_all(file.parent().unwrap()).unwrap();
        let hex = i["source_hex"].as_str().unwrap();
        fs::write(
            file,
            (0..hex.len())
                .step_by(2)
                .map(|j| u8::from_str_radix(&hex[j..j + 2], 16).unwrap())
                .collect::<Vec<_>>(),
        )
        .unwrap();
        let stats = index
            .index_files(
                &mut db,
                &paths,
                &files(&[path]),
                &IndexOptions {
                    workers: Some(0),
                    ..Default::default()
                },
                &mut quiet,
            )
            .unwrap();
        assert_eq!(stats.parsed, 1, "{path}");
        assert_eq!(
            stats.symbols,
            i["parsed"]["symbols"].as_array().unwrap().len(),
            "{path}"
        );
        let actual: String = db
            .connection()
            .query_row("SELECT language FROM ci_files WHERE path=?1", [path], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(actual, lang);
    }
    assert_eq!(languages.len(), 19);
}
#[test]
fn active_profile_is_lazy_and_file_source_races_reject() {
    let (root, paths, mut db) = project();
    write(root.path(), "client.py", "def save(jar):\n    return jar\n");
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let encoder = Rc::new(Encoder::default());
    let loader = Rc::new(Loader(encoder.clone()));
    let options = IndexOptions {
        retrieval_profile: Some(profile()),
        retrieval_loader: Some(loader.clone()),
        legacy_runtime: Some(runtime()),
        ..Default::default()
    };
    let rels = files(&["client.py"]);
    index
        .index_files(&mut db, &paths, &rels, &options, &mut quiet)
        .unwrap();
    index_embeddings(&mut db, profile(), runtime(), loader.clone()).unwrap();
    let options = IndexOptions {
        retrieval_loader: Some(loader),
        legacy_runtime: Some(runtime()),
        ..Default::default()
    };
    let old = load_passage_map(db.connection(), None).unwrap();
    let calls = encoder.calls.borrow().len();
    let loads = encoder.loads.get();
    encoder.fail_load.set(true);
    assert_eq!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap()
            .unchanged,
        1
    );
    assert_eq!(encoder.calls.borrow().len(), calls);
    assert_eq!(encoder.loads.get(), loads);
    encoder.fail_load.set(false);
    write(
        root.path(),
        "client.py",
        "def save(jar):\n    return 'cookie'\n",
    );
    let path = root.path().join("client.py");
    *encoder.action.borrow_mut() = Some(Box::new(move || {
        fs::write(&path, "def newer():return 2\n").unwrap()
    }));
    assert!(
        index
            .index_files(&mut db, &paths, &rels, &options, &mut quiet)
            .unwrap_err()
            .to_string()
            .contains("source changed")
    );
    assert_eq!(load_passage_map(db.connection(), None).unwrap(), old);
}

#[test]
fn later_invalid_projection_aborts_before_any_chunk_publication() {
    struct InvalidEncoder;
    impl DocumentEncoder for InvalidEncoder {
        fn dim(&self) -> Result<usize> {
            Ok(3)
        }
        fn token_count(&self, text: &str) -> Result<usize> {
            LexicalCounter.count(text)
        }
        fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
            Ok(vec![vec![f32::NAN, 0., 1.]; texts.len()])
        }
    }
    struct InvalidLoader;
    impl EncoderLoader for InvalidLoader {
        fn load(&self, _: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
            Ok(Rc::new(InvalidEncoder))
        }
    }
    let (root, paths, mut db) = project();
    write(root.path(), "a.txt", "");
    write(root.path(), "b.txt", "later source owns a passage");
    let parsers = registry();
    let index = Indexer::new(&parsers);
    let options = IndexOptions {
        retrieval_profile: Some(profile()),
        retrieval_loader: Some(Rc::new(InvalidLoader)),
        legacy_runtime: Some(runtime()),
        ..Default::default()
    };
    assert!(
        index
            .index_files(
                &mut db,
                &paths,
                &files(&["a.txt", "b.txt"]),
                &options,
                &mut quiet
            )
            .is_err()
    );
    assert_eq!(
        count(&db, "ci_files"),
        0,
        "even the empty earlier file must remain unpublished"
    );
    assert_eq!(count(&db, "ci_passages"), 0);
    assert_eq!(count(&db, "ci_retrieval_embeddings"), 0);
}
