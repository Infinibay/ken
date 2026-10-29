//! Frozen original producer-stage evidence, independent of the later semantic linker.
use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    control::{structured_control, syntax_contexts},
    normalize_syntax,
};
use ken_store::structural::{NodeFilter, StructuralStore};
use ken_syntax::{
    GrammarCatalog, Language,
    structural::{LoweringError, lower_operations},
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::{io::Read, path::PathBuf};
#[derive(Deserialize)]
struct Case {
    name: String,
    language: Language,
    path: String,
    source: Vec<u8>,
    result: Box<RawValue>,
    control: Box<RawValue>,
}
fn catalog() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar manifest"),
    ))
    .unwrap()
}
fn cases() -> Vec<Case> {
    let bytes = include_bytes!("fixtures/source-operations-reference.json.gz");
    assert_eq!(bytes.len(), 72907);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "ad1ff86907c7ab717fe00c2d7e2db8996aa2ba9691da076f7512efd48e51cfbc"
    );
    let vocab = include_bytes!("../src/structural/vocabulary.json");
    assert_eq!(vocab.len(), 3460);
    assert_eq!(
        format!("{:x}", Sha256::digest(vocab)),
        "c6c73c28ae52496baf2f118e149c817703b90975ea38d073accdf0ea39d89ab0"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    let corpus: Corpus = serde_json::from_str(&text).unwrap();
    assert_eq!(corpus.cases.len(), 42);
    corpus.cases
}
fn mismatch(a: &Value, b: &Value, path: &str) -> Option<String> {
    if a == b {
        return None;
    }
    match (a, b) {
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => a
            .iter()
            .zip(b)
            .enumerate()
            .find_map(|(i, (a, b))| mismatch(a, b, &format!("{path}/{i}"))),
        (Value::Object(a), Value::Object(b)) if a.keys().eq(b.keys()) => a
            .iter()
            .find_map(|(k, a)| mismatch(a, &b[k], &format!("{path}/{k}"))),
        _ => Some(format!("{path}: actual={a}, expected={b}")),
    }
}
fn compare(ir: &StructuralIr, expected: &RawValue, name: &str) {
    let actual = serde_json::to_value(ir).unwrap();
    let expected = serde_json::from_str(expected.get()).unwrap();
    if let Some(diff) = mismatch(&actual, &expected, "") {
        panic!("{name}: {diff}");
    }
}
#[test]
fn every_original_source_operation_owner_operator_role_and_recovery_matches() {
    let catalog = catalog();
    for case in cases() {
        let ir = lower_operations(&catalog, case.language, &case.source, &case.path).unwrap();
        compare(&ir, &case.result, &case.name);
        assert_eq!(ir.capabilities, ["syntax".into()].into_iter().collect());
    }
}
#[test]
fn original_source_to_native_control_pipeline_matches_without_semantic_claims() {
    let catalog = catalog();
    for case in cases() {
        let mut ir = lower_operations(&catalog, case.language, &case.source, &case.path).unwrap();
        structured_control(&mut ir, None).unwrap();
        syntax_contexts(&mut ir).unwrap();
        compare(&ir, &case.control, &case.name);
        let program = normalize_syntax(&ir).unwrap();
        program.validate().unwrap();
    }
}
#[test]
fn produced_ir_and_derived_control_publish_reopen_and_keep_every_syntax_node() {
    let catalog = catalog();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("source.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let mut units = Vec::new();
    let mut expected = Vec::new();
    for case in cases() {
        let mut ir = lower_operations(&catalog, case.language, &case.source, &case.path).unwrap();
        structured_control(&mut ir, None).unwrap();
        syntax_contexts(&mut ir).unwrap();
        let unit = store
            .put_unit(&case.name, &ir, "source-hash", "source-operations/1", false)
            .unwrap();
        units.push(unit);
        expected.push((unit, ir));
    }
    let snapshot = store
        .publish(&units, None, "source-operations/1", false)
        .unwrap();
    store.close().unwrap();
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    assert_eq!(store.current().unwrap(), Some(snapshot));
    for (unit, ir) in expected {
        assert_eq!(
            serde_json::to_value(store.load_unit(unit).unwrap()).unwrap(),
            serde_json::to_value(&ir).unwrap()
        );
        assert_eq!(
            store.operations(unit, None).unwrap().operations.len(),
            ir.operations.len()
        );
    }
    let mut scan = store.prepare_scan(snapshot, NodeFilter::default()).unwrap();
    assert!(scan.rows().unwrap().next().unwrap().is_ok());
}
#[test]
fn producer_rejects_unsupported_structural_languages_and_owns_each_parser_call() {
    let catalog = catalog();
    for language in [Language::C, Language::Kotlin, Language::Dart, Language::Sql] {
        assert!(matches!(
            lower_operations(&catalog, language, b"", "empty"),
            Err(LoweringError::UnsupportedLanguage(_))
        ));
    }
    let first = lower_operations(
        &catalog,
        Language::Python,
        b"def kept_ops(): return 8\n",
        "first.py",
    )
    .unwrap();
    let copy = serde_json::to_string(&first).unwrap();
    let second =
        lower_operations(&catalog, Language::Rust, b"fn second_ops(){}", "second.rs").unwrap();
    assert!(
        second
            .operations
            .iter()
            .all(|o| o.id.starts_with("second.rs::op:"))
    );
    assert_eq!(serde_json::to_string(&first).unwrap(), copy);
}

#[test]
fn parameter_binding_is_preserved_when_it_becomes_a_rust_impl_owner() {
    let bytes = include_bytes!("fixtures/source-operations-review.json.gz");
    assert_eq!(bytes.len(), 1909);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "f72b663a53a4faf339f2939530a4c9b56af84a556aa810a55a6433d3f373d63a"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    let corpus: Corpus = serde_json::from_str(&text).unwrap();
    let catalog = catalog();
    for case in corpus.cases {
        let mut ir = lower_operations(&catalog, case.language, &case.source, &case.path).unwrap();
        compare(&ir, &case.result, &case.name);
        structured_control(&mut ir, None).unwrap();
        syntax_contexts(&mut ir).unwrap();
        compare(&ir, &case.control, &case.name);
    }
}

#[test]
fn wide_source_projection_preserves_roles_within_a_generous_process_budget() {
    const CHILD: &str = "KEN_SOURCE_OPERATIONS_WIDE_CHILD";
    if std::env::var_os(CHILD).is_some() {
        let source = format!(
            "{}def final_wide_ops(value):\n return value + 5\n",
            "pass\n".repeat(20000)
        );
        let ir = lower_operations(
            &catalog(),
            Language::Python,
            source.as_bytes(),
            "wide_ops.py",
        )
        .unwrap();
        assert_eq!(
            ir.operations
                .iter()
                .filter(|o| o.native_kind == "pass_statement")
                .count(),
            20000
        );
        assert!(
            ir.operations
                .iter()
                .any(|o| o.role == "body" && o.owner.contains("/CALLABLE:final_wide_ops@"))
        );
        return;
    }
    let mut child = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "wide_source_projection_preserves_roles_within_a_generous_process_budget",
            "--nocapture",
        ])
        .env(CHILD, "1")
        .stdout(std::process::Stdio::null())
        .spawn()
        .unwrap();
    let start = std::time::Instant::now();
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        if start.elapsed() > std::time::Duration::from_secs(10) {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!(
                "wide source exceeded10s: parent siblings must not be rebuilt for every operation"
            );
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
}
