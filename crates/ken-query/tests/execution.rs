use flate2::read::GzDecoder;
use ken_program::StructuralIr;
use ken_query::execution::{Execution, ExecutionOptions, MemoryGraph, Planning};
use serde_json::Value;
use std::{collections::BTreeMap, io::Read};
#[path = "support/execution_fixture.rs"]
mod fixture;
use fixture::query;
#[test]
fn original_graph_execution_evidence_unknown_budgets_and_counters_match() {
    let bytes = include_bytes!("fixtures/execution-reference.json.gz");
    use sha2::Digest;
    assert_eq!(bytes.len(), 11079);
    let safety = include_bytes!("fixtures/execution-safety-expectations.json");
    assert_eq!(safety.len(), 15184);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(safety)),
        "df142d63787ad40069ef2e5c37a319a46d0bfede004f90391120000293560e81"
    );
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "8fb6020a819aa0c0bc570ef0792930feb490c5e0a7de10754cc0fc19e88f3f61"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let f: Value = serde_json::from_str(&text).unwrap();
    let mut errors = vec![];
    for c in f["cases"].as_array().unwrap() {
        let ir = StructuralIr::from_json(&c["graph"].to_string()).unwrap();
        let graph = MemoryGraph::new(&ir).unwrap();
        let mut options: ExecutionOptions = serde_json::from_value(c["options"].clone()).unwrap();
        options.planning = Planning::AuthorOrder;
        let result = Execution::new(options)
            .unwrap()
            .execute(&graph, &query(&c["query"]));
        match result {
            Ok(result) => {
                let mut got = serde_json::to_value(result).unwrap();
                got["stats"].as_object_mut().unwrap().remove("elapsed_ms");
                let want = fixture::expected(c);
                if got != want {
                    errors.push(format!("{}: {got} != {want}", c["name"]));
                }
            }
            Err(e) => errors.push(format!("{}: {e}", c["name"])),
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn compiled_graph_plan_executes_against_immutable_snapshot() {
    let tree = ken_query::parse(
        "language \"kql/2\";module live;query q{edge ENTITY($x,\"CLASS\");select $x;}",
        "live",
        Default::default(),
    )
    .unwrap();
    let compiled = ken_query::compile_relational(&tree, None).unwrap();
    let ir=StructuralIr::from_json(r#"{"path":"test","language":"python","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"C","relation":"ENTITY","object":"CLASS","attrs":{},"evidence":[]}],"capabilities":[],"diagnostics":[],"relations":["ENTITY"]}"#).unwrap();
    let graph = MemoryGraph::new(&ir).unwrap();
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, compiled.relational.as_ref().unwrap())
        .unwrap();
    assert!(result.complete);
    assert_eq!(result.matches.len(), 1);
    assert_eq!(result.matches[0].bindings.get("$x").unwrap(), "C");
}

fn empty_graph() -> MemoryGraph {
    let ir=StructuralIr::from_json(r#"{"path":"empty","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap();
    MemoryGraph::new(&ir).unwrap()
}
#[test]
fn invalid_unreached_operators_dependencies_and_domains_are_rejected() {
    use serde_json::json;
    for raw in [
        json!({"name":"bad","nodes":[{"kind":"source_body","value":null,"children":[]}],"exports":{},"definitions":{}}),
        json!({"name":"bad","nodes":[{"kind":"fact","value":null,"children":[]}],"exports":{},"definitions":{}}),
        json!({"name":"bad","nodes":[{"kind":"match","value":["missing",{},""],"children":[]}],"exports":{},"definitions":{}}),
        json!({"name":"bad","nodes":[{"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":{"literal":"CLASS"},"attrs":[]},"children":[]},{"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":{"literal":"CALL"},"attrs":[]},"children":[]}],"exports":{},"definitions":{}}),
    ] {
        assert!(
            Execution::new(Default::default())
                .unwrap()
                .execute(&empty_graph(), &query(&raw))
                .is_err()
        );
    }
}
#[test]
fn caller_built_deep_wide_and_recursive_plans_return_controlled_errors() {
    use ken_query::relational::{PlanValue, RelationalNode, RelationalQuery};
    use std::sync::Arc;
    let mut node = RelationalNode {
        kind: "any".into(),
        value: PlanValue::None,
        children: vec![],
    };
    for _ in 0..600 {
        node = RelationalNode {
            kind: "optional".into(),
            value: PlanValue::None,
            children: vec![vec![node]],
        };
    }
    let q = RelationalQuery {
        name: "deep".into(),
        nodes: Arc::new(vec![node]),
        exports: Default::default(),
        definitions: Default::default(),
    };
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&empty_graph(), &q)
            .is_err()
    );
    let mut q = query(
        &serde_json::json!({"name":"wide","nodes":[{"kind":"different","value":["$x","$x"],"children":[]}],"exports":{},"definitions":{}}),
    );
    q.nodes = Arc::new(vec![q.nodes[0].clone(); 66000]);
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&empty_graph(), &q)
            .is_err()
    );
    let q = query(
        &serde_json::json!({"name":"root","nodes":[{"kind":"match","value":["self",{},""],"children":[]}],"exports":{},"definitions":{"self":{"name":"self","nodes":[{"kind":"match","value":["self",{},""],"children":[]}],"exports":{},"definitions":{}}}}),
    );
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&empty_graph(), &q)
            .is_err()
    );
}
#[test]
fn execution_options_reject_zero_and_pre_cancelled_runs_are_incomplete() {
    let mut options = ExecutionOptions::default();
    options.budget.max_states = Some(0);
    assert!(Execution::new(options).is_err());
    let token = ken_query::execution::Cancellation::default();
    token.cancel();
    let options = ExecutionOptions {
        cancellation: token,
        ..Default::default()
    };
    let q = query(&serde_json::json!({"name":"empty","nodes":[],"exports":{},"definitions":{}}));
    let result = Execution::new(options)
        .unwrap()
        .execute(&empty_graph(), &q)
        .unwrap();
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:cancelled"]);
}

#[test]
fn original_scope_cache_proof_boundaries_and_selective_plans_match() {
    let bytes = include_bytes!("fixtures/execution-boundaries-reference.json.gz");
    use sha2::Digest;
    assert_eq!(bytes.len(), 5151);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "3aeca8a0312d96f5d59e95dbf9c4ad5ac50e20f25fdc1699d664147ec3769304"
    );
    let mut s = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
    let f: Value = serde_json::from_str(&s).unwrap();
    let mut failures = vec![];
    for c in f["cases"].as_array().unwrap() {
        let graph =
            MemoryGraph::new(&StructuralIr::from_json(&c["graph"].to_string()).unwrap()).unwrap();
        let mut options: ExecutionOptions = serde_json::from_value(c["options"].clone()).unwrap();
        if c["options"].get("planning").is_none() {
            options.planning = Planning::AuthorOrder;
        }
        let got = Execution::new(options)
            .unwrap()
            .execute(&graph, &query(&c["query"]));
        match got {
            Ok(outcome) => {
                let mut got = serde_json::to_value(outcome).unwrap();
                let mut want = fixture::expected(c);
                got["stats"].as_object_mut().unwrap().remove("elapsed_ms");
                if c["options"]["planning"] == "selective" {
                    for name in ["states", "rows_examined"] {
                        got["stats"].as_object_mut().unwrap().remove(name);
                        want["stats"].as_object_mut().unwrap().remove(name);
                    }
                }
                if got != want {
                    failures.push(format!("{}: {got} != {want}", c["name"]));
                }
            }
            Err(e) => failures.push(format!("{}: {e}", c["name"])),
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn shared_dependency_dag_cannot_expand_unbounded_evidence() {
    use serde_json::json;
    use std::sync::Arc;
    let base = json!({"name":"leaf","nodes":[{"kind":"fact","value":{"subject":"x","relation":"ENTITY","object":{"literal":"CLASS"},"attrs":[]},"children":[]}],"exports":{},"definitions":{}});
    let mut leaf = query(&base);
    let mut definitions = BTreeMap::new();
    definitions.insert("p0".to_owned(), Arc::new(leaf.clone()));
    for i in 1..=15 {
        let name = format!("p{}", i - 1);
        leaf = query(
            &json!({"name":format!("p{i}"),"nodes":[{"kind":"match","value":[name.clone(),{},""],"children":[]},{"kind":"match","value":[name,{},""],"children":[]}],"exports":{},"definitions":{}}),
        );
        definitions.insert(format!("p{i}"), Arc::new(leaf.clone()));
    }
    let mut root = query(
        &json!({"name":"root","nodes":[{"kind":"match","value":["p15",{},""],"children":[]}],"exports":{},"definitions":{}}),
    );
    root.definitions = definitions.into_iter().collect();
    let ir=StructuralIr::from_json(r#"{"path":"dag","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"x","relation":"ENTITY","object":"CLASS","attrs":{},"evidence":[]}],"capabilities":[],"diagnostics":[],"relations":["ENTITY"]}"#).unwrap();
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&MemoryGraph::new(&ir).unwrap(), &root)
        .unwrap();
    assert!(!result.complete);
    assert!(result.matches.is_empty());
    assert_eq!(result.unknown, ["budget:evidence"]);
}

#[test]
fn closure_of_shared_dependency_dags_does_not_repeat_capability_probes() {
    use ken_program::{Entity, Fact};
    use ken_query::execution::{FactProbe, GraphRead, Result};
    use serde_json::json;
    use std::{cell::Cell, collections::BTreeSet, sync::Arc};
    struct Graph {
        inner: MemoryGraph,
        reads: Cell<usize>,
    }
    impl GraphRead for Graph {
        fn facts(&self, p: &FactProbe, v: &mut dyn FnMut(Arc<Fact>) -> Result<()>) -> Result<()> {
            self.inner.facts(p, v)
        }
        fn count(&self, p: &FactProbe) -> Result<u64> {
            self.inner.count(p)
        }
        fn entity(&self, id: &str) -> Result<Option<Arc<Entity>>> {
            self.inner.entity(id)
        }
        fn entity_ids(&self, v: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
            self.inner.entity_ids(v)
        }
        fn capabilities(&self) -> &BTreeSet<String> {
            self.reads.set(self.reads.get() + 1);
            self.inner.capabilities()
        }
        fn relations(&self) -> &BTreeSet<String> {
            self.inner.relations()
        }
    }
    let ir=StructuralIr::from_json(r#"{"path":"closed","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":["complete:f:HAS_CALL"],"diagnostics":[],"relations":["HAS_CALL"]}"#).unwrap();
    let graph = Graph {
        inner: MemoryGraph::new(&ir).unwrap(),
        reads: Cell::new(0),
    };
    let mut child = query(
        &json!({"name":"leaf","nodes":[{"kind":"fact","value":{"subject":"f","relation":"HAS_CALL","object":"_","attrs":[]},"children":[]}],"exports":{},"definitions":{}}),
    );
    let mut defs = BTreeMap::from([("p0".into(), Arc::new(child.clone()))]);
    for i in 1..=10 {
        let name = format!("p{}", i - 1);
        child = query(
            &json!({"name":format!("p{i}"),"nodes":[{"kind":"match","value":[name.clone(),{},""],"children":[]},{"kind":"match","value":[name,{},""],"children":[]}],"exports":{},"definitions":{}}),
        );
        defs.insert(format!("p{i}"), Arc::new(child.clone()));
    }
    let mut root = query(
        &json!({"name":"count","nodes":[{"kind":"count","value":["$w","=",0],"children":[[{"kind":"match","value":["p10",{},""],"children":[]}]]}],"exports":{},"definitions":{}}),
    );
    root.definitions = defs.into_iter().collect();
    let result = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, &root)
        .unwrap();
    assert_eq!(result.matches.len(), 1);
    assert!(result.unknown.is_empty());
    assert!(graph.reads.get() < 64, "{}", graph.reads.get());
}

#[test]
fn deadlines_snapshot_membership_and_explicit_regex_capabilities_are_preserved() {
    use serde_json::json;
    use std::time::Duration;
    let q = query(&json!({"name":"empty","nodes":[],"exports":{},"definitions":{}}));
    let mut options = ExecutionOptions::default();
    options.budget.timeout_ms = Some(1);
    let run = Execution::new(options).unwrap();
    std::thread::sleep(Duration::from_millis(5));
    let result = run.execute(&empty_graph(), &q).unwrap();
    assert!(!result.complete);
    assert_eq!(result.unknown, ["budget:timeout_ms"]);
    let q = query(
        &json!({"name":"regex","nodes":[{"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":"_","attrs":[["name","regex","(?r)foo"]]},"children":[]}],"exports":{},"definitions":{}}),
    );
    let regex = Execution::new(Default::default())
        .unwrap()
        .execute(&empty_graph(), &q)
        .unwrap();
    assert!(regex.complete);
    assert!(regex.matches.is_empty());
    let mut ir=StructuralIr::from_json(r#"{"path":"snapshot","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":["ENTITY"]}"#).unwrap();
    let graph = MemoryGraph::new(&ir).unwrap();
    ir.facts.push(ken_program::Fact {
        subject: "new".into(),
        relation: "ENTITY".into(),
        object: "CLASS".into(),
        attrs: Default::default(),
        evidence: vec![],
    });
    let q = query(
        &json!({"name":"class","nodes":[{"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":{"literal":"CLASS"},"attrs":[]},"children":[]}],"exports":{"x":"$x"},"definitions":{}}),
    );
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&graph, &q)
            .unwrap()
            .matches
            .is_empty()
    );
    assert_eq!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&MemoryGraph::new(&ir).unwrap(), &q)
            .unwrap()
            .matches
            .len(),
        1
    );
}

#[test]
fn numeric_coercion_matches_original_typed_values_in_facts_and_where() {
    #[derive(serde::Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    #[derive(serde::Deserialize)]
    struct Case {
        actual: Box<serde_json::value::RawValue>,
        operation: String,
        expected: String,
        result: Option<bool>,
        error: Option<Value>,
    }
    let bytes = include_bytes!("fixtures/execution-numeric-reference.json.gz");
    use sha2::Digest;
    assert_eq!(bytes.len(), 2157);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "f52021c33cef343056c05deceb90b742669398ab8547aefc3919397a64c27713"
    );
    assert_eq!(
        format!(
            "{:x}",
            sha2::Sha256::digest(include_bytes!("../resources/float-decimal-zeroes.json"))
        ),
        "59e141744100cd9812c75cf9e1355e18d829a5c12bc7b5234ba42ac734570012"
    );
    let mut s = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
    let data: Corpus = serde_json::from_str(&s).unwrap();
    assert_eq!(data.cases.len(), 528);
    let mut failures = vec![];
    for c in data.cases {
        let mut ir=StructuralIr::from_json(r#"{"path":"numeric","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":["ENTITY"]}"#).unwrap();
        ir.facts.push(ken_program::Fact {
            subject: "x".into(),
            relation: "ENTITY".into(),
            object: "CLASS".into(),
            attrs: BTreeMap::from([("value".into(), c.actual.clone())]),
            evidence: vec![],
        });
        let graph = MemoryGraph::new(&ir).unwrap();
        for is_where in [false, true] {
            let mut nodes = vec![
                serde_json::json!({"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":{"literal":"CLASS"},"attrs":if is_where{serde_json::json!([])}else{serde_json::json!([["value",c.operation,c.expected]])}},"children":[]}),
            ];
            if is_where {
                nodes.push(serde_json::json!({"kind":"where","value":["$x.value",c.operation,serde_json::to_string(&c.expected).unwrap()],"children":[]}));
            }
            let q = query(
                &serde_json::json!({"name":"numeric","nodes":nodes,"exports":{"x":"$x"},"definitions":{}}),
            );
            let got = Execution::new(Default::default())
                .unwrap()
                .execute(&graph, &q);
            let okay = if c.error.is_some() {
                got.is_err()
            } else {
                got.as_ref()
                    .is_ok_and(|r| r.matches.is_empty() != c.result.unwrap())
            };
            if !okay {
                failures.push(format!(
                    "{} {} {} where={is_where}: {got:?}",
                    c.actual.get(),
                    c.operation,
                    c.expected
                ));
            }
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
#[test]
fn review_empty_alternatives_are_bounded() {
    use std::sync::Arc;
    let mut q = query(
        &serde_json::json!({"name":"branches","nodes":[{"kind":"any","value":null,"children":[[]]}],"exports":{},"definitions":{}}),
    );
    Arc::make_mut(&mut q.nodes)[0].children = vec![vec![]; 66000];
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&empty_graph(), &q)
            .is_err()
    );
}
#[test]
fn review_leaf_children_are_rejected() {
    let q = query(
        &serde_json::json!({"name":"leaf","nodes":[{"kind":"fact","value":{"subject":"$x","relation":"ENTITY","object":"_","attrs":[]},"children":[[{"kind":"source_body","value":null,"children":[]}]]}],"exports":{},"definitions":{}}),
    );
    assert!(
        Execution::new(Default::default())
            .unwrap()
            .execute(&empty_graph(), &q)
            .is_err()
    );
}
#[test]
fn review_path_literals_are_validated() {
    use ken_query::relational::{PlanValue, QuotedTerm, Term};
    use std::sync::Arc;
    for literal in ["b".to_owned(), "b".repeat(5_000_000)] {
        let mut q = query(
            &serde_json::json!({"name":"path","nodes":[{"kind":"path","value":[{"literal":"a"},"HAS_CALL","$w",0,1,"$p"],"children":[]}],"exports":{},"definitions":{}}),
        );
        let PlanValue::Tuple(v) = &mut Arc::make_mut(&mut q.nodes)[0].value else {
            unreachable!()
        };
        v[0] = PlanValue::Term(Term::Literal(QuotedTerm {
            token: "\"a\"".into(),
            literal,
        }));
        assert!(
            Execution::new(Default::default())
                .unwrap()
                .execute(&empty_graph(), &q)
                .is_err()
        );
    }
}
#[test]
fn validation_respects_interruption_before_work_on_caller_built_plans() {
    let token = ken_query::execution::Cancellation::default();
    token.cancel();
    let q = query(&serde_json::json!({"name":"cancel","nodes":[],"exports":{},"definitions":{}}));
    let got = Execution::new(ExecutionOptions {
        cancellation: token,
        ..Default::default()
    })
    .unwrap()
    .execute(&empty_graph(), &q)
    .unwrap();
    assert!(!got.complete);
    assert_eq!(got.unknown, ["budget:cancelled"]);
}

#[test]
fn review_path_and_union_absence_require_inventory_closure() {
    use serde_json::json;
    let graph = empty_graph();
    let start = json!({"literal":"f"});
    let path = json!({"kind":"path","value":[start,"HAS_CALL","$w",1,1,"$p"],"children":[]});
    let union = json!({"kind":"fact_union","value":[{"subject":"f","relation":"HAS_CALL","object":"$w","attrs":[]},{"subject":"f","relation":"HAS_PARAMETER","object":"$w","attrs":[]}],"children":[]});
    for child in [path, union] {
        let q = query(
            &json!({"name":"open","nodes":[{"kind":"count","value":["$w","=",0],"children":[[child]]}],"exports":{},"definitions":{}}),
        );
        let options = ExecutionOptions {
            evidence_mode: ken_query::execution::EvidenceMode::Possible,
            ..Default::default()
        };
        let outcome = Execution::new(options)
            .unwrap()
            .execute(&graph, &q)
            .unwrap();
        assert_eq!(outcome.matches[0].status, "unknown");
        assert_eq!(outcome.matches[0].unknown, ["cardinality:open_world"]);
    }
}
#[test]
fn review_cardinality_resolves_possible_witnesses() {
    use serde_json::json;
    let raw = serde_json::json!({"path":"uncertain","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"f","relation":"HAS_CALL","object":"one","attrs":{},"evidence":[]},{"subject":"f","relation":"HAS_CALL","object":"two","attrs":{"modality":"may"},"evidence":[]}],"capabilities":["complete:f:HAS_CALL"],"diagnostics":[],"relations":["HAS_CALL"]});
    let graph = MemoryGraph::new(&StructuralIr::from_json(&raw.to_string()).unwrap()).unwrap();
    for op in ["=", "==", "literal", "!="] {
        let n = if op == "!=" { 2 } else { 1 };
        let q = query(
            &json!({"name":"uncertain","nodes":[{"kind":"count","value":["$w",op,n],"children":[[{"kind":"fact","value":{"subject":"f","relation":"HAS_CALL","object":"$w","attrs":[]},"children":[]}]]}],"exports":{},"definitions":{}}),
        );
        let options = ExecutionOptions {
            evidence_mode: ken_query::execution::EvidenceMode::Possible,
            ..Default::default()
        };
        let result = Execution::new(options)
            .unwrap()
            .execute(&graph, &q)
            .unwrap();
        assert_eq!(result.matches[0].status, "unknown");
        assert_eq!(result.matches[0].unknown, ["cardinality:uncertain"]);
    }
}

#[test]
fn bounded_path_closure_checks_every_reachable_inventory_through_dependencies() {
    use serde_json::json;
    for complete in [false, true] {
        let ir=StructuralIr::from_json(&json!({"path":"closure","language":"mixed","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"f","relation":"HAS_CALL","object":"g","attrs":{},"evidence":[]}],"capabilities":if complete{json!(["complete:f:HAS_CALL","complete:g:HAS_CALL"])}else{json!(["complete:f:HAS_CALL"])},"diagnostics":[],"relations":["HAS_CALL"]}).to_string()).unwrap();
        let q = query(
            &json!({"name":"root","nodes":[{"kind":"count","value":["$w","=",0],"children":[[{"kind":"match","value":["walk",{"w":"$w"},""],"children":[]}]]}],"exports":{},"definitions":{"walk":{"name":"walk","nodes":[{"kind":"path","value":[{"literal":"f"},"HAS_CALL","$w",2,2,"$p"],"children":[]}],"exports":{"w":"$w"},"definitions":{}}}}),
        );
        let options = ExecutionOptions {
            evidence_mode: ken_query::execution::EvidenceMode::Possible,
            ..Default::default()
        };
        let result = Execution::new(options)
            .unwrap()
            .execute(&MemoryGraph::new(&ir).unwrap(), &q)
            .unwrap();
        assert_eq!(result.matches.len(), 1);
        assert_eq!(
            result.matches[0].status,
            if complete {
                "structural_match"
            } else {
                "unknown"
            }
        );
    }
}
