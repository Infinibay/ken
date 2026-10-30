//! Source facts and canonical lexical bindings answer different relations.
use super::super::{FactProbe, values::AstValue};
use super::*;
use ken_program::value::GraphValue as Scalar;
impl Runtime<'_, '_> {
    pub(super) fn facts(
        &mut self,
        relation: &str,
        subject: &str,
        target: Option<&str>,
    ) -> Result<Vec<Arc<ken_program::Fact>>> {
        self.check()?;
        let graph = self.graph;
        let mut rows = vec![];
        graph.facts(
            &FactProbe {
                relation: relation.into(),
                subject: Some(subject.into()),
                object: target.map(str::to_owned),
                attribute: None,
            },
            &mut |f| {
                self.check()?;
                if f.subject == subject && target.is_none_or(|t| f.object == t) {
                    rows.push(f);
                }
                Ok(())
            },
        )?;
        Ok(rows)
    }
    pub(super) fn relation(&mut self, name: &str, args: &[Value]) -> Result<Value> {
        let vocabulary = crate::capabilities::vocabulary();
        if let Some((relation, expected)) = vocabulary.statement_unary.get(name) {
            let Some(subject) = args.first().and_then(statement_id) else {
                return Ok(Value::unknown("capability_missing"));
            };
            return Ok(Value::boolean(
                self.facts(relation, &subject, None)?
                    .iter()
                    .any(|f| f.object == *expected),
            ));
        }
        if let Some(relation) = vocabulary.statement_relations.get(name) {
            if args.len() != 2 {
                return Err(invalid("statement relation arity differs"));
            }
            let (Some(mut subject), Some(mut target)) =
                (statement_id(&args[0]), statement_id(&args[1]))
            else {
                return Ok(Value::unknown("capability_missing"));
            };
            if name == "returns_operand" {
                std::mem::swap(&mut subject, &mut target);
                let mut frontier = vec![subject.clone()];
                let mut seen = BTreeSet::from([subject]);
                for _ in 0..4 {
                    let mut next = vec![];
                    for current in frontier {
                        for row in self.facts(relation, &current, None)? {
                            if row.object == target {
                                return Ok(Value::boolean(true));
                            }
                            if seen.insert(row.object.clone()) {
                                next.push(row.object.clone());
                            }
                        }
                    }
                    frontier = next;
                }
                return Ok(Value::boolean(false));
            }
            return Ok(Value::boolean(
                !self.facts(relation, &subject, Some(&target))?.is_empty(),
            ));
        }
        if matches!(
            name,
            "contains" | "contains_direct" | "same_symbol" | "visible_at" | "initialized_at"
        ) {
            if let [Value::Ast(a), Value::Ast(b)] = args {
                return self.ast_relation(name, a, b);
            }
            return Ok(Value::unknown("ast_node_unknown"));
        }
        if let Some((relation, _, _)) = vocabulary.relations.get(name) {
            if args.len() != 2 {
                return Err(invalid("semantic relation arity differs"));
            }
            let (Some(subject), Some(target)) =
                (source::local_id(&args[0]), source::local_id(&args[1]))
            else {
                return Ok(Value::unknown("semantic_argument_unknown"));
            };
            let facts = self.facts(relation, &subject, Some(&target))?;
            if facts.is_empty() {
                return Ok(Value::unknown("open_semantic_relation"));
            }
            for f in facts {
                let execution = f
                    .attrs
                    .get("execution")
                    .map(|v| Scalar::parse(v))
                    .transpose()?
                    .and_then(|v| v.string())
                    .unwrap_or("possible".into());
                if execution == "possible" {
                    return Ok(Value::boolean(true));
                }
            }
            return Ok(Value::boolean(false));
        }
        if let Some((relation, expected)) = vocabulary.unary_relations.get(name) {
            let Some(Value::Node(node)) = args.first() else {
                return Ok(Value::unknown("semantic_argument_unknown"));
            };
            let facts = self.facts(relation, &node.local_id, None)?;
            return Ok(if facts.is_empty() {
                Value::unknown("analysis_status_missing")
            } else {
                Value::boolean(facts.iter().any(|f| f.object == *expected))
            });
        }
        if name == "owns" {
            return match args {
                [Value::Ast(a), Value::Ast(b)] => self.ast_relation("contains_direct", a, b),
                [Value::Node(a), Value::Operation(b)] => Ok(Value::boolean(a.local_id == b.owner)),
                [Value::Node(a), Value::Node(b)] => Ok(Value::boolean(
                    a.unit == b.unit && b.owner.as_ref() == Some(&a.local_id),
                )),
                _ => Ok(Value::unknown("capability_missing")),
            };
        }
        if name == "kind_is" {
            let Some(kind) = args.get(1).and_then(Value::text) else {
                return Ok(Value::unknown("capability_missing"));
            };
            match args.first() {
                Some(Value::Ast(node)) => {
                    return Ok(Value::boolean(
                        matches!(kind.as_str(), "node" | "expression" | "statement")
                            && (kind == "node" || node.node.category == kind),
                    ));
                }
                Some(Value::Node(node)) => {
                    let Some(kinds) = vocabulary.kinds.get(&kind) else {
                        return Ok(Value::unknown("capability_missing"));
                    };
                    if !kinds.contains(&node.kind) {
                        return Ok(Value::boolean(false));
                    }
                    if kind == "constructor" {
                        return self.property(&Value::Node(node.clone()), "constructor");
                    }
                    if matches!(kind.as_str(), "param" | "receiver") {
                        let value = self.property(&Value::Node(node.clone()), "receiver")?;
                        return Ok(if value.is_unknown() {
                            value
                        } else {
                            Value::boolean(
                                matches!(value,Value::Scalar(ref v)if v.truthy())
                                    == (kind == "receiver"),
                            )
                        });
                    }
                    return Ok(Value::boolean(true));
                }
                _ => return Ok(Value::unknown("capability_missing")),
            }
        }
        self.predicate(name, args)
    }
    fn ast_relation(&mut self, name: &str, a: &AstValue, b: &AstValue) -> Result<Value> {
        self.check()?;
        if a.snapshot != b.snapshot || a.unit != b.unit {
            return Ok(Value::boolean(false));
        }
        if name == "contains_direct" {
            return Ok(Value::boolean(b.node.parent == Some(a.node.id)));
        }
        if name == "contains" {
            return Ok(Value::boolean(
                a.node.id < b.node.id && b.node.id < a.node.subtree_end,
            ));
        }
        let Some(program) = self.ast_program(a.unit)? else {
            return Ok(Value::unknown("symbol_unresolved"));
        };
        let mut occurrences: BTreeMap<_, _> = program
            .symbols
            .iter()
            .map(|s| (s.declaration, s.id))
            .collect();
        occurrences.extend(
            program
                .references
                .iter()
                .filter(|r| r.status == "known")
                .filter_map(|r| r.symbol.map(|s| (r.node, s))),
        );
        let Some(left) = occurrences.get(&a.node.id) else {
            return Ok(Value::unknown("symbol_unresolved"));
        };
        if name == "same_symbol" {
            return Ok(occurrences.get(&b.node.id).map_or_else(
                || Value::unknown("symbol_unresolved"),
                |right| Value::boolean(left == right),
            ));
        }
        let symbol = program
            .symbols
            .get(*left)
            .ok_or_else(|| invalid("AST symbol identity missing"))?;
        let environment = ken_program::Environment::new(&program);
        let resolution = environment.resolve(&symbol.name, b.node.scope as i64, b.node.start)?;
        if resolution.status != "known" {
            return Ok(Value::unknown(resolution.reason));
        }
        if resolution.symbol != Some(*left) {
            return Ok(Value::boolean(false));
        }
        if name == "visible_at" {
            return Ok(Value::boolean(true));
        }
        Ok(if resolution.availability == "unknown" {
            Value::unknown(resolution.reason)
        } else {
            Value::boolean(resolution.availability == "available")
        })
    }
}
fn statement_id(value: &Value) -> Option<String> {
    value
        .text()
        .or_else(|| source::local_id(value))
        .filter(|s| !s.is_empty())
}
