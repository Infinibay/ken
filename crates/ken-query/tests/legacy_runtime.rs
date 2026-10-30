use flate2::read::GzDecoder;
use ken_program::StructuralIr;
use ken_query::{
    execution::{ExecutionOptions, MemoryGraph},
    legacy::{execute, parse_pattern},
};
use serde_json::Value;
use sha2::Digest;
use std::io::Read;

#[test]
fn frozen_legacy_parser_and_runtime_contracts() {
    let bytes = include_bytes!("fixtures/legacy-reference.json.gz");
    assert_eq!(bytes.len(), 4449);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "f6db32729d3c44d90e3d171319b9adc87907c3572882e78e809eb93038f2fbe6"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let fixture: Value = serde_json::from_str(&text).unwrap();
    let mut errors = vec![];
    for case in fixture["cases"].as_array().unwrap() {
        let result = parse_pattern(
            case["source"].as_str().unwrap(),
            case["validate_roles"].as_bool().unwrap(),
        );
        let pattern = match result {
            Ok(pattern) => pattern,
            Err(error) => {
                if case.get("parsed").is_some()
                    || case["error"].as_str() != Some(&error.to_string())
                {
                    errors.push(format!("{} parse: {error}", case["name"]));
                }
                continue;
            }
        };
        let parsed = serde_json::to_value(&pattern).unwrap();
        if parsed != case["parsed"] {
            errors.push(format!(
                "{} AST: {parsed} != {}",
                case["name"], case["parsed"]
            ));
        }
        if case["parse_only"].as_bool() == Some(true) {
            continue;
        }
        let ir = StructuralIr::from_json(&case["graph"].to_string()).unwrap();
        let graph = MemoryGraph::new(&ir).unwrap();
        let options: ExecutionOptions = serde_json::from_value(case["options"].clone()).unwrap();
        match execute(&graph, &pattern, options) {
            Ok(result) => {
                let mut got = serde_json::to_value(result).unwrap();
                got["stats"].as_object_mut().unwrap().remove("elapsed_ms");
                if got != case["result"] {
                    errors.push(format!(
                        "{} runtime: {got} != {}",
                        case["name"], case["result"]
                    ));
                }
            }
            Err(error) => {
                if case["error"].as_str() != Some(&error.to_string()) {
                    errors.push(format!("{} runtime: {error}", case["name"]));
                }
            }
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}

#[test]
fn legacy_snapshot_scope_probe_supersets_and_interruption_are_checked() {
    use ken_program::{Entity, Fact};
    use ken_query::execution::{ExecutionError, FactProbe, GraphRead, Result};
    use std::{collections::BTreeSet, sync::Arc};
    struct Superset {
        graph: MemoryGraph,
        facts: Vec<Arc<Fact>>,
    }
    impl GraphRead for Superset {
        fn facts(
            &self,
            _: &FactProbe,
            visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>,
        ) -> Result<()> {
            for fact in &self.facts {
                visit(fact.clone())?;
            }
            Ok(())
        }
        fn count(&self, _: &FactProbe) -> Result<u64> {
            Ok(999)
        }
        fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
            self.graph.entity(id)
        }
        fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
            self.graph.entity_ids(visit)
        }
        fn capabilities(&self) -> &BTreeSet<String> {
            self.graph.capabilities()
        }
        fn relations(&self) -> &BTreeSet<String> {
            self.graph.relations()
        }
    }
    let ir=StructuralIr::from_json(r#"{"path":"test","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"a","relation":"LINK","object":"b","attrs":{"n":1},"evidence":["good"]},{"subject":"a","relation":"OTHER","object":"b","attrs":{"n":3},"evidence":["wrong relation"]},{"subject":"x","relation":"LINK","object":"b","attrs":{"n":3},"evidence":["wrong subject"]},{"subject":"a","relation":"LINK","object":"c","attrs":{"n":3},"evidence":["wrong object"]}],"capabilities":[],"diagnostics":[],"relations":["LINK","OTHER"]}"#).unwrap();
    let baseline = MemoryGraph::new(&ir).unwrap();
    let graph = Superset {
        graph: MemoryGraph::new(&ir).unwrap(),
        facts: ir.facts.iter().cloned().map(Arc::new).collect(),
    };
    for source in [
        "require a LINK b n>=2",
        "require a LINK b n=1",
        "require a LINK+ $target",
        "require $start LINK{2,3} b",
    ] {
        let pattern = parse_pattern(source, true).unwrap();
        let mut want =
            serde_json::to_value(execute(&baseline, &pattern, Default::default()).unwrap())
                .unwrap();
        let mut got =
            serde_json::to_value(execute(&graph, &pattern, Default::default()).unwrap()).unwrap();
        want["stats"].as_object_mut().unwrap().remove("elapsed_ms");
        got["stats"].as_object_mut().unwrap().remove("elapsed_ms");
        assert_eq!(got, want, "{source}");
    }
    let pattern = parse_pattern("require $s LINK $o", true).unwrap();
    let options = ExecutionOptions::default();
    options.cancellation.cancel();
    let outcome = execute(&graph, &pattern, options).unwrap();
    assert!(!outcome.complete);
    assert_eq!(outcome.unknown, vec!["budget:cancelled"]);
    let mut options = ExecutionOptions::default();
    options.budget.max_rows = Some(0);
    assert!(matches!(
        execute(&graph, &pattern, options),
        Err(ExecutionError::Invalid(_))
    ));
}

#[test]
fn legacy_natural_counts_and_unicode_decimal_bounds_are_lossless() {
    let huge = "9".repeat(200);
    let pattern = parse_pattern(
        &format!("require $s LINK{{١,٢}} $o\ncount <={huge} $s LINK _"),
        true,
    )
    .unwrap();
    assert_eq!(pattern.clauses[0].minimum, 1);
    assert_eq!(pattern.clauses[0].maximum, 2);
    assert_eq!(pattern.clauses[1].count.to_string(), huge);
    let text = serde_json::to_string(&pattern).unwrap();
    assert!(text.contains(&format!("\"count\":{huge},")));
    let restored: ken_query::legacy::Pattern = serde_json::from_str(&text).unwrap();
    assert_eq!(pattern, restored);
    let ir=StructuralIr::from_json(r#"{"path":"count","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"a","relation":"LINK","object":"b","attrs":{},"evidence":[]}],"capabilities":[],"diagnostics":[],"relations":["LINK"]}"#).unwrap();
    let graph = MemoryGraph::new(&ir).unwrap();
    assert_eq!(
        execute(&graph, &pattern, Default::default())
            .unwrap()
            .matches
            .len(),
        1
    );
}

#[test]
fn serialized_patterns_preserve_authored_variant_order() {
    let pattern = parse_pattern(
        "variant z\nrequire a LINK b\nend\nvariant a\nrequire a LINK b\nend",
        true,
    )
    .unwrap();
    let text = serde_json::to_string(&pattern).unwrap();
    let restored: ken_query::legacy::Pattern = serde_json::from_str(&text).unwrap();
    assert_eq!(pattern, restored);
    assert!(text.find("\"z\":").unwrap() < text.find("\"a\":").unwrap());
}
