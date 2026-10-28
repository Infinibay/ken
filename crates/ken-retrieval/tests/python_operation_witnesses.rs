#[path = "../examples/support/python_witnesses.rs"]
mod support;
use ken_retrieval::{
    operation_witnesses::OperationWitnesses, python_operation_witnesses::PythonOperationWitnesses,
};
use ken_syntax::GrammarCatalog;
use serde::Deserialize;
use serde_json::Value;
use std::{fs, io::Read, sync::Arc};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Value,
    result: Value,
}
fn corpus() -> Corpus {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/python-witnesses-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}
#[test]
fn all_frozen_python_observations_match_on_immutable_catalog_snapshots() {
    let mut failures = Vec::new();
    let mut cases = corpus().cases;
    let mut compat = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/python-witnesses-compat.json.gz").as_slice(),
    )
    .read_to_string(&mut compat)
    .unwrap();
    cases.extend(serde_json::from_str::<Corpus>(&compat).unwrap().cases);
    for case in cases {
        let (directory, catalog) =
            support::catalog(support::physical(case.input).unwrap()).unwrap();
        let catalog = Arc::new(catalog);
        for path in catalog.snapshots().keys() {
            fs::write(directory.path().join(path), b"changed after snapshot\n").unwrap();
        }
        let mut observer = PythonOperationWitnesses::new(catalog.clone());
        let mut actual = Vec::new();
        for (key, _) in catalog.owners() {
            let cold = observer.for_owner(key).unwrap();
            let mut independent = cold.clone();
            independent.insert("foreign".into());
            let warm = observer.for_owner(key).unwrap();
            actual.push(serde_json::json!({"key":key,"cold":cold,"warm":warm}));
        }
        let actual = Value::Array(actual);
        if actual != case.result {
            failures.push(format!(
                "{} expected {} got {}",
                case.id, case.result, actual
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "Python AST parity failures: {failures:?}"
    );
}
#[test]
fn router_composes_python_and_existing_cst_backends() {
    let source = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "function-refresh")
        .unwrap();
    let (_directory, catalog) = support::catalog(support::physical(source.input).unwrap()).unwrap();
    let catalog = Arc::new(catalog);
    let grammar = Arc::new(
        GrammarCatalog::prepared(&std::path::PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    assert_eq!(
        support::observe(
            support::physical(
                corpus()
                    .cases
                    .into_iter()
                    .find(|c| c.id == "function-refresh")
                    .unwrap()
                    .input
            )
            .unwrap(),
            grammar.clone()
        )
        .unwrap(),
        source.result
    );
    let mut router = OperationWitnesses::new(catalog.clone(), grammar);
    for (key, _) in catalog.owners() {
        assert!(
            router
                .for_owner(key)
                .unwrap()
                .contains("returned_flag_refresh")
        );
        let mut unknown = key.clone();
        unknown.qualname = Some("missing".into());
        assert!(router.for_owner(&unknown).is_err());
    }
    let mut raw = String::new();
    flate2::read::GzDecoder::new(
        include_bytes!("fixtures/syntax-witnesses-reference.json.gz").as_slice(),
    )
    .read_to_string(&mut raw)
    .unwrap();
    let cst: Value = serde_json::from_str(&raw).unwrap();
    for case in cst["cases"].as_array().unwrap() {
        let (_dir, catalog) =
            support::catalog(support::physical(case["input"].clone()).unwrap()).unwrap();
        let catalog = Arc::new(catalog);
        let mut router = OperationWitnesses::new(
            catalog.clone(),
            Arc::new(
                GrammarCatalog::prepared(&std::path::PathBuf::from(
                    std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
                ))
                .unwrap(),
            ),
        );
        let actual = catalog
            .owners()
            .iter()
            .map(|(key, _)| {
                let cold = router.for_owner(key).unwrap();
                let warm = router.for_owner(key).unwrap();
                serde_json::json!({"key":key,"cold":cold,"warm":warm})
            })
            .collect::<Vec<_>>();
        assert_eq!(
            Value::Array(actual),
            case["result"],
            "router CST {}",
            case["id"]
        );
    }
    assert!(PythonOperationWitnesses::supports("stub.pyi"));
    assert!(!PythonOperationWitnesses::supports("source.js"));
}
#[test]
fn canonical_dispatch_and_preferences_use_native_observations() {
    use ken_retrieval::symbol_preferences::apply_symbol_preferences;
    use ken_retrieval::symbol_requirements::SymbolRequirements;
    let case = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "function-refresh")
        .unwrap();
    let mut input = case.input;
    let files = input["files"].as_object_mut().unwrap();
    let content = files.remove("sample.py").unwrap();
    files.insert("sample.txt".into(), content);
    for owner in input["owners"].as_array_mut().unwrap() {
        owner["key"]["path"] = "sample.txt".into();
        for passage in owner["passages"].as_array_mut().unwrap() {
            passage["entity"]["path"] = "sample.txt".into();
        }
    }
    let (_dir, catalog) = support::catalog(support::physical(input).unwrap()).unwrap();
    let catalog = Arc::new(catalog);
    let key = &catalog.owners()[0].0;
    let grammar = Arc::new(
        GrammarCatalog::prepared(&std::path::PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
        ))
        .unwrap(),
    );
    assert!(
        PythonOperationWitnesses::new(catalog.clone())
            .for_owner(key)
            .is_err()
    );
    assert!(
        OperationWitnesses::new(catalog.clone(), grammar)
            .for_owner(key)
            .unwrap()
            .is_empty()
    );
    let case = corpus()
        .cases
        .into_iter()
        .find(|c| c.id == "function-refresh")
        .unwrap();
    let (_dir, catalog) = support::catalog(support::physical(case.input).unwrap()).unwrap();
    let catalog = Arc::new(catalog);
    let tags = PythonOperationWitnesses::new(catalog.clone())
        .for_owner(&catalog.owners()[0].0)
        .unwrap();
    let required = SymbolRequirements {
        operations: ["returned_flag_refresh".into()].into(),
        operators: Default::default(),
        test_case: false,
    };
    assert_eq!(
        apply_symbol_preferences(
            &required,
            &[Default::default(), tags],
            &[false, false],
            &["".into(), "".into()],
            &[0, 1]
        )
        .unwrap(),
        vec![1, 0]
    );
}
