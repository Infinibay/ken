//! Original indexed runtime observations. Graph identity is supplied explicitly.
use flate2::read::GzDecoder;
use ken_program::{StructuralIr, value::GraphValue};
use ken_query::execution::{
    MemoryGraph,
    indexed_runtime::{IndexedExecution, IndexedOptions},
    values::SourceNode,
};
use serde_json::Value;
use std::{io::Read, sync::Arc};
fn fixture() -> Value {
    let bytes = include_bytes!("fixtures/indexed-runtime-reference.json.gz");
    use sha2::Digest;
    assert_eq!(bytes.len(), 42767);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "589f1b73eaf2788c72492a81095dad6fea6bab22d9da8ffe0732ff8cc145f00a"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let mut corpus: Value = serde_json::from_str(&text).unwrap();
    let extra = include_bytes!("fixtures/indexed-runtime-extra-reference.json.gz");
    assert_eq!(extra.len(), 43797);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(extra)),
        "cb7e2bde272e7e32cc571f72fcacbaaafaef221834532c97f81a9ac0fb19127b"
    );
    let mut extra_text = String::new();
    GzDecoder::new(&extra[..])
        .read_to_string(&mut extra_text)
        .unwrap();
    let extra: Value = serde_json::from_str(&extra_text).unwrap();
    corpus["cases"]
        .as_array_mut()
        .unwrap()
        .extend(extra["cases"].as_array().unwrap().iter().cloned());
    let bytes = include_bytes!("fixtures/indexed-runtime-types-reference.json.gz");
    assert_eq!(bytes.len(), 21624);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "8ecb25ee28894bbba3e611f5d6a6da5ec53fc13ef3f1a09433f8bc47e5d41d8c"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let more: Value = serde_json::from_str(&text).unwrap();
    corpus["cases"]
        .as_array_mut()
        .unwrap()
        .extend(more["cases"].as_array().unwrap().iter().cloned());
    let bytes = include_bytes!("fixtures/indexed-runtime-repr-reference.json.gz");
    assert_eq!(bytes.len(), 13873);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "5e8b76fd7cab1b2d3163871d5f06088c7ec4343faf4b339378f504467ee16d26"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let more: Value = serde_json::from_str(&text).unwrap();
    corpus["cases"]
        .as_array_mut()
        .unwrap()
        .extend(more["cases"].as_array().unwrap().iter().cloned());
    corpus
}
fn source_node(v: &Value) -> SourceNode {
    SourceNode {
        id: v["id"].as_i64().unwrap(),
        unit: v["unit"].as_i64().unwrap(),
        local_id: v["local_id"].as_str().unwrap().into(),
        kind: v["kind"].as_str().unwrap().into(),
        name: v["name"].as_str().map(Into::into),
        owner: v["owner"].as_str().map(Into::into),
        line: v["line"].as_i64().unwrap(),
        end_line: v["end_line"].as_i64().unwrap(),
        path: v["path"].as_str().unwrap().into(),
        language: v["language"].as_str().unwrap().into(),
    }
}
fn graph(case: &Value) -> MemoryGraph {
    let ir = StructuralIr::from_json(&case["graph"].to_string()).unwrap();
    let nodes = case["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .map(source_node)
        .collect();
    let properties = case["properties"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(id, props)| {
            (
                id.clone(),
                props
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(key, value)| {
                        let raw =
                            serde_json::value::RawValue::from_string(value.to_string()).unwrap();
                        (key.clone(), GraphValue::parse(&raw).unwrap())
                    })
                    .collect(),
            )
        })
        .collect();
    let programs = case["programs"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(unit, program)| {
            (
                unit.parse().unwrap(),
                Arc::new(ken_program::Program::from_json(&program.to_string()).unwrap()),
            )
        })
        .collect();
    MemoryGraph::new(&ir).unwrap().with_source_nodes(
        nodes,
        properties,
        programs,
        case["complete"].as_bool().unwrap_or(true),
    )
}
#[test]
fn original_indexed_runtime_rows_unknowns_plans_and_boundaries() {
    let corpus = fixture();
    let mut errors = vec![];
    let mut compared = 0;
    for case in corpus["cases"].as_array().unwrap() {
        if case.get("compile_error").is_some() {
            continue;
        }
        let tree = ken_query::parse(
            case["source"].as_str().unwrap(),
            case["name"].as_str().unwrap(),
            Default::default(),
        )
        .unwrap();
        let program = ken_query::compile_indexed_branches(&tree, None).unwrap();
        for reference in [false, true] {
            let mut options = IndexedOptions {
                reference,
                profile: true,
                ..Default::default()
            };
            options.timeout_ms = case["options"]["timeout_ms"].as_f64();
            options.max_rows = case["options"]["max_rows"].as_u64();
            options.max_states = case["options"]["max_states"].as_u64();
            if case["options"]["cancelled"] == true {
                options.cancellation.cancel();
            }
            let expected = &case["results"][if reference { "True" } else { "False" }];
            let result = IndexedExecution::new(options)
                .unwrap()
                .execute(&graph(case), &program);
            if expected.get("error").is_some() {
                match result {
                    Ok(_) => {
                        errors.push(format!("{}: expected {}", case["name"], expected["error"]))
                    }
                    Err(error) => {
                        if error.to_string() != expected["error"].as_str().unwrap() {
                            errors.push(format!(
                                "{} diagnostic: {error} != {}",
                                case["name"], expected["error"]
                            ));
                        }
                    }
                }
                continue;
            }
            let mut got = match result {
                Ok(value) => serde_json::to_value(value).unwrap(),
                Err(e) => {
                    errors.push(format!("{}: {e}", case["name"]));
                    continue;
                }
            };
            let mut want = expected.clone();
            // Physical source adapters poll storage cancellation independently;
            // logical result and planning parity remain exact. Timing is observed,
            // never an oracle. Counters remain public and checked independently.
            for value in [&mut got, &mut want] {
                value.as_object_mut().unwrap().remove("elapsed_ms");
                value.as_object_mut().unwrap().remove("states");
                value.as_object_mut().unwrap().remove("scanned_nodes");
                for entry in value["profile"].as_array_mut().unwrap() {
                    entry.as_object_mut().unwrap().remove("elapsed_ms");
                }
            }
            if got != want {
                errors.push(format!(
                    "{} reference={reference}:\n got {got}\nwant {want}",
                    case["name"]
                ));
            }
            compared += 1;
        }
    }
    assert!(
        compared >= 200,
        "runtime observation inventory shrank: {compared}"
    );
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn immediate_cancellation_and_zero_timeout_are_incomplete_not_absence() {
    let case = &fixture()["cases"][0];
    let tree = ken_query::parse(
        "language \"kql/2\";module t;query q{select 1;}",
        "budget",
        Default::default(),
    )
    .unwrap();
    let p = ken_query::compile_indexed(&tree, None).unwrap();
    let out = IndexedExecution::new(IndexedOptions {
        timeout_ms: Some(0.0),
        ..Default::default()
    })
    .unwrap()
    .execute(&graph(case), &p)
    .unwrap();
    assert!(!out.complete);
    assert_eq!(out.reason.as_deref(), Some("timeout"));
    assert!(out.rows.is_empty());
    assert!(out.states > 0);
    for timeout in [-1.0, f64::INFINITY, f64::NAN] {
        assert!(
            IndexedExecution::new(IndexedOptions {
                timeout_ms: Some(timeout),
                ..Default::default()
            })
            .is_err()
        );
    }
    assert!(
        IndexedExecution::new(IndexedOptions {
            max_rows: Some(0),
            ..Default::default()
        })
        .is_err()
    );
}
#[test]
fn physical_profiling_preserves_results_and_does_not_consume_states() {
    let case = &fixture()["cases"][0];
    let tree=ken_query::parse("language \"kql/2\";module t;query q{class $c{} bind $name=$c.name;where true;select $name;}","profile",Default::default()).unwrap();
    let p = ken_query::compile_indexed(&tree, None).unwrap();
    let plain = IndexedExecution::new(Default::default())
        .unwrap()
        .execute(&graph(case), &p)
        .unwrap();
    let profiled = IndexedExecution::new(IndexedOptions {
        profile: true,
        ..Default::default()
    })
    .unwrap()
    .execute(&graph(case), &p)
    .unwrap();
    assert_eq!(plain.rows, profiled.rows);
    assert_eq!(plain.states, profiled.states);
    assert_eq!(plain.scanned_nodes, profiled.scanned_nodes);
    assert_eq!(profiled.profile.len(), 3);
    assert_eq!(profiled.profile[0]["input_rows"], 1);
    assert_eq!(profiled.profile[0]["output_rows"], 2);
    assert_eq!(profiled.profile[1]["input_rows"], 2);
    assert_eq!(profiled.profile[1]["output_rows"], 2);
    assert_eq!(profiled.profile[2]["input_rows"], 2);
    assert_eq!(profiled.profile[2]["output_rows"], 2);
    assert!(plain.profile.is_empty());
}
#[test]
fn name_prefilter_preserves_unavailable_names_and_unknown_absence() {
    let mut case = fixture()["cases"][0].clone();
    case["nodes"][0]["name"] = Value::Null;
    case["properties"]["A"]["name"] = Value::Null;
    for source in [
        "class $c{name:\"A\";}select $c;",
        "not exists{class $c{name:\"A\";}}select 1;",
    ] {
        let text = format!("language \"kql/2\";module t;query q{{{source}}}");
        let tree = ken_query::parse(&text, "unknown-name", Default::default()).unwrap();
        let p = ken_query::compile_indexed(&tree, None).unwrap();
        let out = IndexedExecution::new(Default::default())
            .unwrap()
            .execute(&graph(&case), &p)
            .unwrap();
        assert!(out.complete);
        assert!(out.rows.is_empty());
        assert_eq!(out.unknown_candidates, 1);
    }
}
#[test]
fn materialization_budget_counts_distinct_rows_instead_of_matching_frames() {
    let case = &fixture()["cases"][0];
    for body in [
        "class $c{}select 1;",
        "{class $c{name:\"A\";}}or{class $c{name:\"A\";}}select $c.name;",
    ] {
        let text = format!("language \"kql/2\";module t;query q{{{body}}}");
        let tree = ken_query::parse(&text, "distinct-budget", Default::default()).unwrap();
        let p = ken_query::compile_indexed_branches(&tree, None).unwrap();
        let out = IndexedExecution::new(IndexedOptions {
            max_rows: Some(1),
            ..Default::default()
        })
        .unwrap()
        .execute(&graph(case), &p)
        .unwrap();
        assert!(out.complete);
        assert_eq!(out.rows.len(), 1);
        assert!(out.scanned_nodes >= 2);
    }
}
#[test]
fn aggregate_propagates_the_inner_arithmetic_source_location_once() {
    let case = &fixture()["cases"][0];
    let tree = ken_query::parse(
        "language \"kql/2\";module t;query q{select sum(TypeDecl $c|true|1/0);}",
        "nested",
        Default::default(),
    )
    .unwrap();
    let p = ken_query::compile_indexed(&tree, None).unwrap();
    let division = &p.projection[0].args[0].args[1];
    let error = IndexedExecution::new(Default::default())
        .unwrap()
        .execute(&graph(case), &p)
        .unwrap_err();
    assert_eq!(
        error.to_string(),
        format!("nested:{}: division by zero", division.span.start)
    );
}

#[test]
fn cancellation_after_source_scan_and_before_finalization_is_incomplete() {
    use ken_program::{Entity, Fact, value::GraphValue};
    use ken_query::execution::{
        Cancellation, FactProbe, GraphRead, Result, SourceProbe, values::SourceNode,
    };
    use std::{
        collections::{BTreeMap, BTreeSet},
        sync::Arc,
    };
    struct LastScan {
        inner: MemoryGraph,
        cancel: Cancellation,
    }
    impl GraphRead for LastScan {
        fn facts(
            &self,
            p: &FactProbe,
            visit: &mut dyn FnMut(Arc<Fact>) -> Result<()>,
        ) -> Result<()> {
            self.inner.facts(p, visit)
        }
        fn count(&self, p: &FactProbe) -> Result<u64> {
            self.inner.count(p)
        }
        fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
            self.inner.entity(id)
        }
        fn entity_ids(&self, visit: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
            self.inner.entity_ids(visit)
        }
        fn capabilities(&self) -> &BTreeSet<String> {
            self.inner.capabilities()
        }
        fn relations(&self) -> &BTreeSet<String> {
            self.inner.relations()
        }
        fn source_coverage(&self) -> Result<bool> {
            self.inner.source_coverage()
        }
        fn source_node(&self, id: &str) -> Result<Option<Arc<SourceNode>>> {
            self.inner.source_node(id)
        }
        fn source_properties(&self, node: &SourceNode) -> Result<BTreeMap<String, GraphValue>> {
            self.inner.source_properties(node)
        }
        fn source_scan(
            &self,
            p: &SourceProbe,
            check: &mut dyn FnMut() -> Result<()>,
            visit: &mut dyn FnMut(Arc<SourceNode>) -> Result<()>,
        ) -> Result<u64> {
            let result = self.inner.source_scan(p, check, visit);
            self.cancel.cancel();
            result
        }
    }
    let c = &fixture()["cases"][0];
    let tree=ken_query::parse("language \"kql/2\";module finalization;query q{class $c{}select $c.name;order by $c.name;}","finalization",Default::default()).unwrap();
    let program = ken_query::compile_indexed(&tree, None).unwrap();
    let baseline = IndexedExecution::new(Default::default())
        .unwrap()
        .execute(&graph(c), &program)
        .unwrap();
    assert!(baseline.complete);
    assert!(!baseline.rows.is_empty());
    for max_states in [None, Some(baseline.states - 1)] {
        let cancel = Cancellation::default();
        let source = LastScan {
            inner: graph(c),
            cancel: cancel.clone(),
        };
        let outcome = IndexedExecution::new(IndexedOptions {
            cancellation: cancel,
            max_states,
            ..Default::default()
        })
        .unwrap()
        .execute(&source, &program)
        .unwrap();
        assert!(!outcome.complete);
        assert_eq!(
            outcome.reason.as_deref(),
            Some(if max_states.is_some() {
                "max_states"
            } else {
                "cancelled"
            })
        );
    }
}
