#[path = "../examples/support/syntax_witnesses.rs"]
mod support;
use ken_retrieval::{
    query::SearchRequest, symbol_preferences::apply_symbol_preferences,
    symbol_requirements::requirements, syntax_operation_witnesses::SyntaxOperationWitnesses,
};
use ken_syntax::GrammarCatalog;
use serde::Deserialize;
use serde_json::Value;
use std::{collections::BTreeMap, fs, io::Read, path::PathBuf, sync::Arc};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: support::Physical,
    result: Value,
}
fn corpus() -> Corpus {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/syntax-witnesses-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}
fn grammars() -> Arc<GrammarCatalog> {
    Arc::new(
        GrammarCatalog::prepared(&PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar manifest required"),
        ))
        .unwrap(),
    )
}
#[test]
fn frozen_cst_body_witnesses_preserve_original_selection_recovery_and_cache() {
    let data = corpus();
    assert_eq!(data.cases.len(), 120);
    let grammars = grammars();
    let mut owners = 0;
    for case in data.cases {
        owners += case.input.owners.len();
        assert_eq!(
            support::observe(case.input, grammars.clone()).unwrap(),
            case.result,
            "{}",
            case.id
        );
    }
    assert_eq!(owners, 144);
    // Supplemental source-derived contract check, not a new frozen observation.
    // The original whole-module extent misses the callable's ending line.
    let mut case = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "js-recovery")
        .unwrap();
    let bytes = case.input.files.values().next().unwrap();
    assert!(
        grammars
            .syntax(ken_syntax::Language::JavaScript, bytes, "sample.js")
            .unwrap()
            .root()
            .has_error()
    );
    for owner in &mut case.input.owners {
        for passage in &mut owner.passages {
            passage.span = ken_retrieval::Span::new(1, 3).unwrap();
            passage.entity_span = passage.span;
        }
    }
    let (_directory, catalog) = support::catalog(case.input).unwrap();
    let key = catalog.owners()[0].0.clone();
    assert_eq!(catalog.extent(&key).unwrap(), [1, 3]);
    let mut observer = SyntaxOperationWitnesses::new(Arc::new(catalog), grammars);
    assert_eq!(
        observer.for_owner(&key).unwrap(),
        ["invocation".to_owned()].into()
    );
}
#[test]
fn returned_witnesses_and_late_disk_changes_do_not_mutate_cached_source() {
    let case = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "js-refresh")
        .unwrap();
    let (directory, catalog) = support::catalog(case.input).unwrap();
    let catalog = Arc::new(catalog);
    let key = catalog.owners()[0].0.clone();
    let grammars = grammars();
    let mut observer = SyntaxOperationWitnesses::new(catalog.clone(), grammars.clone());
    let expected = observer.for_owner(&key).unwrap();
    assert!(expected.contains("returned_flag_refresh"));
    let mut changed = expected.clone();
    changed.clear();
    changed.insert("caller mutation".into());
    fs::remove_file(directory.path().join(&key.path)).unwrap();
    assert_eq!(observer.for_owner(&key).unwrap(), expected);
    let mut fresh = SyntaxOperationWitnesses::new(catalog, grammars);
    assert_eq!(fresh.for_owner(&key).unwrap(), expected);
}
#[test]
fn backend_admission_is_explicit_for_python_jsx_and_unknown_owners() {
    for path in ["a.java", "a.js", "a.mjs", "a.cjs", "a.ts", "a.tsx"] {
        assert!(SyntaxOperationWitnesses::supports(path));
    }
    for path in ["a.py", "a.pyi", "a.jsx", "a.rs", "a.JAVA", ".js", ""] {
        assert!(!SyntaxOperationWitnesses::supports(path));
    }
    let case = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "js-refresh")
        .unwrap();
    let (_directory, catalog) = support::catalog(case.input).unwrap();
    let catalog = Arc::new(catalog);
    let mut key = catalog.owners()[0].0.clone();
    let mut observer = SyntaxOperationWitnesses::new(catalog, grammars());
    key.qualname = Some("missing".into());
    assert!(observer.for_owner(&key).is_err());
    key.path = "missing.py".into();
    assert!(observer.for_owner(&key).is_err());
    // Canonical catalog admission succeeds before the backend rejects either suffix.
    for path in ["canonical.py", "canonical.jsx"] {
        let mut case = corpus()
            .cases
            .into_iter()
            .find(|c| c.id == "js-stored")
            .unwrap();
        let bytes = case.input.files.remove("sample.js").unwrap();
        case.input.files.insert(path.into(), bytes);
        for owner in &mut case.input.owners {
            owner.key.path = path.into();
            for passage in &mut owner.passages {
                passage.entity.path = path.into();
            }
        }
        let (_directory, catalog) = support::catalog(case.input).unwrap();
        let key = catalog.owners()[0].0.clone();
        assert!(!catalog.passages(&key).unwrap().is_empty());
        let mut observer = SyntaxOperationWitnesses::new(Arc::new(catalog), grammars());
        match observer.for_owner(&key) {
            Err(ken_retrieval::source_snapshot::SourceError::Invalid(message)) => {
                assert!(message.contains("syntax witness backend requires"))
            }
            other => panic!("expected explicit backend rejection for {path}, got {other:?}"),
        }
    }
}
#[test]
fn real_source_witnesses_supply_the_explicit_preference_policy() {
    let mut files = BTreeMap::new();
    let mut owners = Vec::new();
    for (id, path) in [("js-stored", "stored.js"), ("js-refresh", "refresh.js")] {
        let case = corpus().cases.into_iter().find(|c| c.id == id).unwrap();
        let bytes = case.input.files.into_values().next().unwrap();
        files.insert(path.to_owned(), bytes);
        for mut owner in case.input.owners {
            owner.key.path = path.into();
            for p in &mut owner.passages {
                p.entity.path = path.into();
            }
            owners.push(owner);
        }
    }
    let (_directory, catalog) = support::catalog(support::Physical { files, owners }).unwrap();
    let catalog = Arc::new(catalog);
    assert_eq!(catalog.owners().len(), 2);
    let mut observer = SyntaxOperationWitnesses::new(catalog.clone(), grammars());
    let witnesses = catalog
        .owners()
        .iter()
        .map(|(key, _)| observer.for_owner(key).unwrap())
        .collect::<Vec<_>>();
    let required =
        requirements(&SearchRequest::new("Find code that returns a flag or updates it").unwrap());
    let order = apply_symbol_preferences(
        &required,
        &witnesses,
        &[false, false],
        &["".into(), "".into()],
        &[0, 1],
    )
    .unwrap();
    assert_eq!(order, [1, 0]);
}
