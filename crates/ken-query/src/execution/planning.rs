//! Positive join selection stops at semantic and unavailable-filter boundaries.
use super::{
    Planning, Result,
    engine::Engine,
    plan::{Kind, Op},
    terms::{Bindings, bind, resolve, variable},
};
use crate::relational::{RelationalEdge, Term};
impl Engine<'_> {
    pub fn choose(&mut self, pending: &[&Op], bindings: &Bindings) -> Result<usize> {
        if self.run.options.planning == Planning::AuthorOrder {
            return Ok(0);
        }
        let boundary = pending
            .iter()
            .position(|n| match &n.kind {
                Kind::Fact(_) | Kind::Union(_) | Kind::Different(..) => false,
                Kind::Where(a, _, b) => !ready(a, bindings) || !ready(b, bindings),
                _ => true,
            })
            .unwrap_or(pending.len());
        for (i, n) in pending[..boundary].iter().enumerate() {
            match &n.kind {
                Kind::Different(a, b) if bindings.contains_key(a) && bindings.contains_key(b) => {
                    return Ok(i);
                }
                Kind::Where(a, _, b) if ready(a, bindings) && ready(b, bindings) => return Ok(i),
                _ => (),
            }
        }
        let joins: Vec<_> = pending[..boundary]
            .iter()
            .enumerate()
            .filter(|(_, n)| matches!(n.kind, Kind::Fact(_) | Kind::Union(_)))
            .collect();
        if joins.len() == 1 {
            return Ok(joins[0].0);
        }
        let mut best = None;
        for (i, node) in joins {
            let clauses = match &node.kind {
                Kind::Fact(c) => std::slice::from_ref(c),
                Kind::Union(c) => c,
                _ => unreachable!(),
            };
            let mut size = 0u64;
            for (j, c) in clauses.iter().enumerate() {
                size = size.saturating_add(self.clause_size(node.id, j, c, bindings)?);
            }
            let disconnected = !bindings.is_empty()
                && clauses.first().is_some_and(|c| {
                    let roles: Vec<_> = [&c.subject, &c.object]
                        .into_iter()
                        .filter(|t| variable(t))
                        .map(Term::token)
                        .collect();
                    !roles.is_empty() && roles.iter().all(|r| !bindings.contains_key(*r))
                });
            let cost = (size, disconnected, i);
            if best.is_none_or(|old| cost < old) {
                best = Some(cost);
            }
        }
        Ok(best.map_or(0, |(_, _, i)| i))
    }
    fn clause_size(
        &mut self,
        id: usize,
        index: usize,
        c: &RelationalEdge,
        b: &Bindings,
    ) -> Result<u64> {
        let s = resolve(&c.subject, b);
        let o = resolve(&c.object, b);
        let key = (id, index, s.clone(), o.clone());
        if let Some(size) = self.sizes.get(&key) {
            return Ok(*size);
        }
        let sf = s.is_some() || !variable(&c.subject) && c.subject.token() != "_";
        let of = o.is_some() || !variable(&c.object) && c.object.token() != "_";
        let mut size = 0;
        for p in self.probes(c, b)? {
            let graph = self.graph;
            graph.facts(&p, &mut |f| {
                self.check()?;
                if s.as_ref().is_some_and(|s| s != &f.subject)
                    || o.as_ref().is_some_and(|o| o != &f.object)
                {
                    return Ok(());
                }
                let mut probe = Bindings::new();
                if sf && s.is_none() && !bind(&c.subject, &f.subject, &mut probe)
                    || of && o.is_none() && !bind(&c.object, &f.object, &mut probe)
                {
                    return Ok(());
                }
                for (k, op, v) in &c.attrs {
                    let value = super::engine::attribute(&f, k)?;
                    if !self.comparisons.compare(&value, op, v)? {
                        return Ok(());
                    }
                }
                size += 1;
                Ok(())
            })?;
        }
        self.sizes.insert(key, size);
        Ok(size)
    }
}
fn ready(term: &str, b: &Bindings) -> bool {
    !term.starts_with('$') || b.contains_key(term.split('.').next().unwrap())
}

use std::{collections::BTreeSet, sync::Arc};
impl Engine<'_> {
    pub fn positive_plan(&mut self, nodes: &Arc<Vec<Op>>, initial: &Bindings) -> Arc<Vec<Op>> {
        let key = (
            Arc::as_ptr(nodes) as usize,
            initial.keys().cloned().collect::<Vec<_>>(),
        );
        if let Some(plan) = self.pruned.get(&key) {
            return plan.clone();
        }
        let mut plan = (**nodes).clone();
        for n in &mut plan {
            if let Kind::Any(branches) = &n.kind
                && branches.len() >= 2
                && branches
                    .iter()
                    .all(|b| b.len() == 1 && matches!(b[0].kind, Kind::Fact(_)))
            {
                let facts: Vec<_> = branches
                    .iter()
                    .map(|b| {
                        if let Kind::Fact(c) = &b[0].kind {
                            c.clone()
                        } else {
                            unreachable!()
                        }
                    })
                    .collect();
                if facts
                    .iter()
                    .all(|c| c.subject == facts[0].subject && c.object == facts[0].object)
                    && facts.iter().any(|c| c.relation != facts[0].relation)
                {
                    n.kind = Kind::Union(facts);
                }
            }
        }
        let mut position = 0;
        while position < plan.len() {
            if let Kind::Match {
                query,
                bindings,
                proof,
            } = &plan[position].kind
            {
                let child = &self.plan.queries[query];
                if proof.is_empty()
                    && bindings.len() == child.exports.len()
                    && child
                        .exports
                        .iter()
                        .all(|(p, _)| bindings.iter().any(|(k, _)| k == p))
                    && positive(&child.nodes)
                {
                    let mut end = position + 1;
                    while end < plan.len()
                        && matches!(plan[end].kind, Kind::Fact(_) | Kind::Union(_))
                    {
                        end += 1;
                    }
                    let produced: BTreeSet<_> =
                        plan[position + 1..end].iter().flat_map(roles).collect();
                    if bindings.iter().any(|(_, v)| produced.contains(v)) {
                        plan[position..end].rotate_left(1);
                        position = end;
                        continue;
                    }
                }
            }
            position += 1;
        }
        if plan.len() >= 2
            && matches!(plan[0].kind, Kind::Fact(_))
            && matches!(plan[1].kind, Kind::Any(_))
        {
            let factor = roles(&plan[0]);
            if let Some(dependencies) = union_roles(&plan[1])
                && !factor.is_empty()
                && factor.is_disjoint(&dependencies)
                && factor.iter().all(|r| !initial.contains_key(r))
            {
                plan.swap(0, 1);
            }
        }
        let mut bound: BTreeSet<_> = initial.keys().cloned().collect();
        let mut position = 0;
        while position < plan.len() {
            let matcher = plan[position].clone();
            if matches!(matcher.kind, Kind::Receiver(..)) {
                let mut crossed = outputs(&matcher);
                let mut selected = vec![];
                let mut end = position + 1;
                while end < plan.len() {
                    let candidate = &plan[end];
                    if matches!(candidate.kind, Kind::Receiver(..)) {
                        crossed.extend(outputs(candidate));
                    } else if matches!(
                        candidate.kind,
                        Kind::Fact(_) | Kind::Union(_) | Kind::Where(..) | Kind::Different(..)
                    ) {
                        let r = roles(candidate);
                        if r.is_subset(&bound) && r.is_disjoint(&crossed) {
                            selected.push(candidate.id);
                        }
                    } else {
                        break;
                    }
                    end += 1;
                }
                if !selected.is_empty() {
                    let mut segment = plan[position..end].to_vec();
                    segment.sort_by_key(|n| !selected.contains(&n.id));
                    plan.splice(position..end, segment);
                    position += selected.len();
                }
            }
            bound.extend(outputs(&matcher));
            position += 1;
        }
        let result = Arc::new(plan);
        if self.pruned.len() >= 8 {
            self.pruned.clear();
        }
        self.pruned.insert(key, result.clone());
        result
    }
}
fn positive(nodes: &[Op]) -> bool {
    crate::with_stack(|| {
        nodes.iter().all(|n| match &n.kind {
            Kind::Fact(_) | Kind::Where(..) | Kind::Different(..) => true,
            Kind::Any(b) => b.iter().all(|b| positive(b)),
            _ => false,
        })
    })
}
fn roles(node: &Op) -> BTreeSet<String> {
    let terms: Vec<&str> = match &node.kind {
        Kind::Fact(c) => vec![
            if variable(&c.subject) {
                c.subject.token()
            } else {
                ""
            },
            if variable(&c.object) {
                c.object.token()
            } else {
                ""
            },
        ],
        Kind::Union(c) => c
            .first()
            .map(|c| {
                vec![
                    if variable(&c.subject) {
                        c.subject.token()
                    } else {
                        ""
                    },
                    if variable(&c.object) {
                        c.object.token()
                    } else {
                        ""
                    },
                ]
            })
            .unwrap_or_default(),
        Kind::Where(a, _, b) | Kind::Different(a, b) => vec![a, b],
        _ => vec![],
    };
    terms
        .into_iter()
        .filter(|t| t.starts_with('$'))
        .map(|t| t.split('.').next().unwrap().into())
        .collect()
}
fn outputs(node: &Op) -> BTreeSet<String> {
    match &node.kind {
        Kind::Receiver(_, r) => BTreeSet::from([r.clone()]),
        Kind::Fact(_) | Kind::Union(_) => roles(node),
        Kind::Match {
            bindings, proof, ..
        } => bindings
            .iter()
            .map(|(_, v)| v.clone())
            .chain((!proof.is_empty()).then(|| proof.clone()))
            .collect(),
        _ => BTreeSet::new(),
    }
}
fn union_roles(node: &Op) -> Option<BTreeSet<String>> {
    crate::with_stack(|| match &node.kind {
        Kind::Any(branches) => {
            let mut all = BTreeSet::new();
            for b in branches {
                for n in b.iter() {
                    all.extend(union_roles(n)?);
                }
            }
            Some(all)
        }
        Kind::Fact(_) | Kind::Where(..) | Kind::Different(..) => Some(roles(node)),
        _ => None,
    })
}
