use ken_structural::application::sessions::{QueryApplication, QueryOptions, SessionOptions};
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};
#[test]
fn delivered_query_diagnostics_keep_the_original_entry_source_label() {
    let root = tempfile::tempdir().unwrap();
    std::fs::write(root.path().join("one.py"), "class Example: pass\n").unwrap();
    let grammar = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let app = QueryApplication::new(
        root.path(),
        Arc::new(ken_syntax::GrammarCatalog::prepared(&grammar).unwrap()),
        BTreeMap::new(),
    )
    .unwrap();
    let mut session = app.open_transient(SessionOptions::default()).unwrap();
    let result=session.search(Some("language \"kql/2\";module source_label;query q{node $a {} node $b {} select $a.name;}"),QueryOptions::default()).unwrap();
    let diagnostics = result.diagnostics.unwrap();
    assert!(!diagnostics.is_empty());
    assert!(diagnostics.iter().all(|d| d["span"]["source"] == "<query>"));
}
