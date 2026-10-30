//! Operator-specific bindings, witnesses and scope transitions.
use super::{
    ExecutionError, FactProbe, Result,
    engine::{Engine, attribute},
    evidence::{Proof, Proofs, Row, materialize, python_json},
    plan::{Kind, Op},
    terms::{Bindings, bind, resolve, spelling},
};
use ken_program::value::GraphValue as V;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
impl Engine<'_> {
    pub fn apply(&mut self, node: &Op, row: Row, out: &mut Vec<Row>) -> Result<()> {
        match &node.kind {
            Kind::Source(op) => self.source_apply(op, row, out)?,
            Kind::Body(pattern) => self.source_body(pattern.clone(), row, out)?,
            Kind::Fact(c) => self.facts(c, row, out)?,
            Kind::Union(clauses) => {
                for c in clauses {
                    self.facts(c, row.clone(), out)?;
                }
            }
            Kind::Where(a, op, b) => {
                let left = self.operand(a, &row)?;
                let right = self.operand(b, &row)?;
                if matches!(left, V::Null) || matches!(right, V::Null) {
                    let mut row = row;
                    row.unknown.insert("attribute:missing".into());
                    out.push(row);
                } else if self
                    .comparisons
                    .compare(&left, op, &spelling(&right, false))?
                {
                    out.push(row);
                }
            }
            Kind::Different(a, b) => {
                let a = row
                    .bindings
                    .get(a)
                    .ok_or_else(|| ExecutionError::Invalid("unbound different operand".into()))?;
                let b = row
                    .bindings
                    .get(b)
                    .ok_or_else(|| ExecutionError::Invalid("unbound different operand".into()))?;
                if a != b {
                    out.push(row);
                }
            }
            Kind::Any(branches) => {
                for branch in branches {
                    out.extend(self.nodes(branch, vec![row.clone()])?);
                }
            }
            Kind::Match {
                query,
                bindings,
                proof,
            } => {
                let child = self.plan.queries[query].clone();
                let mut seed = Bindings::new();
                for (public, local) in bindings {
                    if let Some(v) = row.bindings.get(local) {
                        let role = &child.exports.iter().find(|(p, _)| p == public).unwrap().1;
                        seed.insert(role.clone(), v.clone());
                    }
                }
                let key = (query.clone(), self.scope.clone(), seed.clone());
                let hits = if let Some(hits) = self.cache.get(&key) {
                    hits.clone()
                } else {
                    let hits = Arc::new(self.nodes(&child.nodes, vec![Row::seed(seed)])?);
                    self.cache.insert(key, hits.clone());
                    hits
                };
                self.dependencies.insert(query.clone());
                let mut matches: Vec<Proofs> = vec![];
                let mut positions = BTreeMap::new();
                for hit in hits.iter() {
                    self.check()?;
                    let mut b = row.bindings.clone();
                    let mut accepted = true;
                    for (public, local) in bindings {
                        let role = &child.exports.iter().find(|(p, _)| p == public).unwrap().1;
                        let value = hit.bindings.get(role).ok_or_else(|| {
                            ExecutionError::Invalid(format!("unbound dependency export {role}"))
                        })?;
                        if b.get(local).is_some_and(|old| old != value) {
                            accepted = false;
                            break;
                        }
                        b.insert(local.clone(), value.clone());
                    }
                    if accepted {
                        let identity = b.clone();
                        if !proof.is_empty() {
                            b.insert(
                                proof.clone(),
                                python_json(&serde_json::Value::Array(materialize(
                                    &hit.evidence,
                                    &mut || self.check(),
                                )?)),
                            );
                        }
                        let mut unknown = row.unknown.clone();
                        unknown.extend(hit.unknown.iter().cloned());
                        let matched = Row {
                            bindings: b,
                            evidence: row.append(Proof::Dependency {
                                query: query.clone(),
                                proof: proof.clone(),
                                evidence: hit.evidence.clone(),
                            }),
                            unknown,
                        };
                        if let Some(&i) = positions.get(&identity) {
                            let group: &mut Proofs = &mut matches[i];
                            group.add(matched);
                        } else {
                            positions.insert(identity, matches.len());
                            matches.push(Proofs::new(matched));
                        }
                    }
                }
                out.extend(matches.into_iter().map(Proofs::finish));
            }
            Kind::Optional(nodes) => {
                let hits = self.nodes(nodes, vec![row.clone()])?;
                let mut evidence = (*row.evidence).clone();
                evidence.extend(hits.into_iter().map(|h| Proof::Optional(h.evidence)));
                out.push(Row {
                    evidence: Arc::new(evidence),
                    ..row
                });
            }
            Kind::Not {
                domain,
                owner,
                nodes,
            } => {
                let scope = row.bindings.get(owner).cloned().ok_or_else(|| {
                    ExecutionError::Invalid(format!("unbound absence owner {owner}"))
                })?;
                let previous = self.scope.replace(scope.clone());
                let hits = self.nodes(nodes, vec![row.clone()]);
                self.scope = previous;
                let hits = hits?;
                if !hits.iter().any(|h| h.unknown.is_subset(&row.unknown)) {
                    let mut unknown = row.unknown.clone();
                    if !hits.is_empty() || !self.closed(nodes, &row, Some(&scope))? {
                        unknown.insert(format!("absence:{domain}:{scope}"));
                    }
                    out.push(Row { unknown, ..row });
                }
            }
            Kind::Count {
                role,
                comparison,
                number,
                nodes,
            } => {
                let hits = self.nodes(nodes, vec![row.clone()])?;
                use super::cardinality::{Cardinality, Decision};
                let mut certain = BTreeSet::new();
                let mut possible = BTreeSet::new();
                for hit in &hits {
                    self.check()?;
                    let value = hit.bindings.get(role).ok_or_else(|| {
                        ExecutionError::Invalid(format!("unbound count witness {role}"))
                    })?;
                    possible.insert(value.clone());
                    if hit.unknown.is_subset(&row.unknown) {
                        certain.insert(value.clone());
                    }
                }
                let target = super::numbers::parse(number)
                    .ok_or_else(|| ExecutionError::Invalid("invalid count target".into()))?;
                let lower = Cardinality {
                    certain: certain.len(),
                    possible: None,
                };
                let mut decision = lower.compare(comparison, target);
                let mut closed = false;
                if decision == Decision::Unknown {
                    closed = self.closed(nodes, &row, None)?;
                    if closed {
                        decision = Cardinality {
                            certain: certain.len(),
                            possible: Some(possible.len()),
                        }
                        .compare(comparison, target);
                    }
                }
                match decision {
                    Decision::Satisfied => out.push(row),
                    Decision::Rejected => (),
                    Decision::Unknown => {
                        let mut row = row;
                        row.unknown.insert(
                            if closed {
                                "cardinality:uncertain"
                            } else {
                                "cardinality:open_world"
                            }
                            .into(),
                        );
                        out.push(row);
                    }
                }
            }

            Kind::Path {
                start,
                relation,
                end,
                min,
                max,
                proof,
            } => {
                let starts = if let Some(v) = resolve(start, &row.bindings) {
                    vec![v]
                } else {
                    let mut starts = BTreeSet::new();
                    self.graph.entity_ids(&mut |s| {
                        self.check()?;
                        starts.insert(s.into());
                        Ok(())
                    })?;
                    self.graph.facts(&FactProbe::relation(relation), &mut |f| {
                        self.check()?;
                        starts.insert(f.subject.clone());
                        starts.insert(f.object.clone());
                        Ok(())
                    })?;
                    starts.into_iter().collect()
                };
                for start_id in starts {
                    let mut frontier = vec![(
                        start_id.clone(),
                        Vec::<String>::new(),
                        BTreeSet::<String>::new(),
                    )];
                    let mut seen = BTreeSet::new();
                    for depth in 0..=*max {
                        let mut next = vec![];
                        let mut next_seen = BTreeSet::new();
                        for (target, witness, unknown) in frontier {
                            self.tick()?;
                            if depth >= *min && seen.insert((target.clone(), !unknown.is_empty())) {
                                // Original path checks the raw endpoint token before _bind;
                                // literal unions remain handled by the actual typed binder.
                                let mut bindings = row.bindings.clone();
                                if bind(start, &start_id, &mut bindings)
                                    && bind(end, &target, &mut bindings)
                                {
                                    let mut nodes = vec![start_id.clone()];
                                    nodes.extend(witness.iter().cloned());
                                    bindings.insert(
                                        proof.clone(),
                                        python_json(&serde_json::json!(nodes)),
                                    );
                                    let mut missing = row.unknown.clone();
                                    missing.extend(unknown.iter().cloned());
                                    out.push(Row {
                                        bindings,
                                        evidence: row.append(Proof::Path {
                                            relation: relation.clone(),
                                            nodes,
                                        }),
                                        unknown: missing,
                                    });
                                }
                            }
                            if depth < *max {
                                let mut p = FactProbe::relation(relation);
                                p.subject = Some(target);
                                let graph = self.graph;
                                graph.facts(&p, &mut |f| {
                                    self.check()?;
                                    self.examine()?;
                                    let mut uncertainty = unknown.clone();
                                    if attribute(&f, "modality")?.string().as_deref() == Some("may")
                                    {
                                        uncertainty.insert(format!("possible:{relation}"));
                                    }
                                    if next_seen.insert((f.object.clone(), !uncertainty.is_empty()))
                                    {
                                        let mut path = witness.clone();
                                        path.push(f.object.clone());
                                        next.push((f.object.clone(), path, uncertainty));
                                    }
                                    Ok(())
                                })?;
                            }
                        }
                        frontier = next;
                    }
                }
            }
            Kind::Receiver(owner, receiver) => {
                let owner_id = row.bindings.get(owner).ok_or_else(|| {
                    ExecutionError::Invalid(format!("unbound receiver owner {owner}"))
                })?;
                let mut method = FactProbe::relation("HAS_METHOD");
                method.object = Some(owner_id.clone());
                let graph = self.graph;
                graph.facts(&method, &mut |member| {
                    self.tick()?;
                    if member.object != *owner_id {
                        return Ok(());
                    }
                    if let Some(entity) = graph.entity(owner_id)?
                        && entity
                            .attrs
                            .get("static")
                            .map(|v| V::parse(v))
                            .transpose()?
                            .is_some_and(|v| v.truthy())
                    {
                        return Ok(());
                    }
                    let mut p = FactProbe::relation("INSTANCE_RECEIVER");
                    p.subject = Some(member.subject.clone());
                    graph.facts(&p, &mut |r| {
                        self.tick()?;
                        if r.subject != member.subject
                            || row.bindings.get(receiver).is_some_and(|v| v != &r.object)
                        {
                            return Ok(());
                        }
                        let mut bindings = row.bindings.clone();
                        bindings.insert(receiver.clone(), r.object.clone());
                        out.push(Row {
                            bindings,
                            evidence: row.evidence.clone(),
                            unknown: row.unknown.clone(),
                        });
                        Ok(())
                    })
                })?;
            }
        }
        Ok(())
    }
}
