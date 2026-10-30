//! Per-invocation coordination, counters and snapshot services.
use super::{
    evidence::{Proof, Row, project},
    plan::{Kind, Op, Plan},
    terms::{Bindings, Comparisons, bind, resolve},
    *,
};
use crate::relational::{RelationalEdge, RelationalQuery, Term};
use ken_program::{Fact, value::GraphValue as V};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Debug, thiserror::Error)]
pub enum ExecutionError {
    #[error("{0}")]
    Invalid(String),
    #[error("unsupported capability: {0}")]
    Unsupported(String),
    #[error("query budget exhausted: {0}")]
    Exhausted(&'static str),
    #[error("graph storage: {0}")]
    Storage(String),
    #[error(transparent)]
    Program(#[from] ken_program::ProgramError),
}
pub(super) type CacheKey = (String, Option<String>, Bindings);
pub(super) struct Engine<'a> {
    pub graph: &'a dyn GraphRead,
    pub plan: Plan,
    pub run: Execution,
    pub states: u64,
    pub examined: u64,
    pub scope: Option<String>,
    pub depth: usize,
    pub comparisons: Comparisons,
    pub cache: BTreeMap<CacheKey, Arc<Vec<Row>>>,
    pub dependencies: BTreeSet<String>,
    owned: BTreeMap<String, Arc<BTreeSet<String>>>,
    closure_cache: BTreeMap<(usize, Bindings, Option<String>), bool>,
    closure_bytes: usize,
    pub pruned: BTreeMap<(usize, Vec<String>), Arc<Vec<Op>>>,
    pub sizes: BTreeMap<(usize, usize, Option<String>, Option<String>), u64>,
    pub source: super::source::SourceCache,
}
impl Execution {
    pub fn execute(self, graph: &dyn GraphRead, query: &RelationalQuery) -> Result<QueryOutcome> {
        let mut comparisons = Comparisons::new(self.interruption.clone());
        let plan = match Plan::new(query, graph.relations(), &mut comparisons) {
            Ok(plan) => plan,
            Err(ExecutionError::Exhausted(reason)) => {
                return Ok(QueryOutcome {
                    usage_metadata: Default::default(),
                    matches: vec![],
                    complete: false,
                    unknown: vec![format!("budget:{reason}")],
                    stats: QueryStats {
                        states: 0,
                        rows_examined: 0,
                        elapsed_ms: (self.started.elapsed().as_secs_f64() * 1_000_000.).round()
                            / 1000.,
                        dependencies: vec![],
                    },
                });
            }
            Err(e) => return Err(e),
        };
        let mut engine = Engine {
            graph,
            plan,
            run: self,
            states: 0,
            examined: 0,
            scope: None,
            depth: 0,
            comparisons,
            cache: BTreeMap::new(),
            dependencies: BTreeSet::new(),
            owned: BTreeMap::new(),
            closure_cache: BTreeMap::new(),
            closure_bytes: 0,
            sizes: BTreeMap::new(),
            pruned: BTreeMap::new(),
            source: Default::default(),
        };
        let root = engine.plan.root.clone();
        let result = engine
            .check()
            .and_then(|_| engine.nodes(&root.nodes, vec![Row::seed(Bindings::new())]));
        let mut complete = true;
        let mut reasons = BTreeSet::new();
        let rows = match result {
            Ok(rows) => rows,
            Err(ExecutionError::Exhausted(r)) => {
                complete = false;
                reasons.insert(format!("budget:{r}"));
                vec![]
            }
            Err(e) => return Err(e),
        };
        let matches = match project(
            rows,
            &root.exports,
            engine.run.options.evidence_mode,
            engine.run.options.budget.max_matches,
            || engine.check(),
        ) {
            Ok(projection) => {
                complete &= projection.complete;
                reasons.extend(projection.unknown);
                projection.matches
            }
            Err(ExecutionError::Exhausted(r)) => {
                complete = false;
                reasons.insert(format!("budget:{r}"));
                vec![]
            }
            Err(e) => return Err(e),
        };
        let elapsed = (engine.run.started.elapsed().as_secs_f64() * 1_000_000.).round() / 1000.;
        Ok(QueryOutcome {
            usage_metadata: engine.source.usage_metadata,
            matches,
            complete,
            unknown: reasons.into_iter().collect(),
            stats: QueryStats {
                states: engine.states,
                rows_examined: engine.examined,
                elapsed_ms: elapsed,
                dependencies: engine.dependencies.into_iter().collect(),
            },
        })
    }
}
impl Engine<'_> {
    pub fn check(&self) -> Result<()> {
        self.run.interruption.check()
    }
    pub fn tick(&mut self) -> Result<()> {
        self.check()?;
        self.states = self.states.saturating_add(1);
        if self
            .run
            .options
            .budget
            .max_states
            .is_some_and(|n| self.states > n)
        {
            return Err(ExecutionError::Exhausted("max_states"));
        }
        Ok(())
    }
    pub fn examine(&mut self) -> Result<()> {
        self.examined = self.examined.saturating_add(1);
        if self
            .run
            .options
            .budget
            .max_rows
            .is_some_and(|n| self.examined > n)
        {
            return Err(ExecutionError::Exhausted("max_rows"));
        }
        Ok(())
    }
    pub fn nodes(&mut self, nodes: &Arc<Vec<Op>>, mut rows: Vec<Row>) -> Result<Vec<Row>> {
        crate::with_stack(|| {
            if self.depth >= 512 {
                return Err(ExecutionError::Invalid(
                    "runtime execution depth limit exceeded".into(),
                ));
            }
            self.depth += 1;
            let result = (|| {
                self.check()?;
                if self.run.options.planning == Planning::Selective && !rows.is_empty() {
                    for n in nodes.iter() {
                        if let Kind::Fact(c) = &n.kind {
                            self.check()?;
                            if self.graph.count(&FactProbe::relation(&c.relation))? == 0 {
                                return Ok(vec![]);
                            }
                        }
                    }
                }
                let planned =
                    if self.run.options.planning == Planning::Selective && !rows.is_empty() {
                        self.positive_plan(nodes, &rows[0].bindings)
                    } else {
                        nodes.clone()
                    };
                let mut pending: Vec<_> = planned.iter().collect();
                while !pending.is_empty() && !rows.is_empty() {
                    self.check()?;
                    let index = self.choose(&pending, &rows[0].bindings)?;
                    let node = pending.remove(index);
                    let mut next = vec![];
                    for row in rows {
                        self.tick()?;
                        self.apply(node, row, &mut next)?;
                    }
                    rows = next;
                }
                Ok(rows)
            })();
            self.depth -= 1;
            result
        })
    }
    pub fn probes(&self, c: &RelationalEdge, b: &Bindings) -> Result<Vec<FactProbe>> {
        let s = resolve(&c.subject, b);
        let o = resolve(&c.object, b);
        let mut best = vec![FactProbe::relation(&c.relation)];
        if let Some(subject) = &s {
            best[0].subject = Some(subject.clone());
        }
        if let Some(object) = &o {
            let mut p = FactProbe::relation(&c.relation);
            p.object = Some(object.clone());
            if s.is_none() || self.graph.count(&p)? < self.graph.count(&best[0])? {
                best = vec![p];
            }
        }
        let mut size = best
            .iter()
            .map(|p| self.graph.count(p))
            .collect::<Result<Vec<_>>>()?
            .iter()
            .sum::<u64>();
        for (t, resolved, subject) in [(&c.subject, &s, true), (&c.object, &o, false)] {
            if resolved.is_none()
                && matches!(t,Term::Text(v)if !v.starts_with('$')&&v.contains('|'))
            {
                let mut seen = BTreeSet::new();
                let mut alternative = vec![];
                for v in t.token().split('|') {
                    if !seen.insert(v) {
                        continue;
                    }
                    let mut p = FactProbe::relation(&c.relation);
                    if subject {
                        p.subject = Some(v.into());
                    } else {
                        p.object = Some(v.into());
                    }
                    alternative.push(p);
                }
                let total = alternative
                    .iter()
                    .map(|p| self.graph.count(p))
                    .collect::<Result<Vec<_>>>()?
                    .iter()
                    .sum::<u64>();
                if total < size {
                    size = total;
                    best = alternative;
                }
            }
        }
        for (k, op, v) in &c.attrs {
            if !matches!(op.as_str(), "=" | "literal") || v.is_empty() {
                continue;
            }
            let values = if op == "literal" {
                vec![v.as_str()]
            } else {
                v.split('|').collect()
            };
            let alternative: Vec<_> = values
                .into_iter()
                .map(|v| {
                    let mut p = FactProbe::relation(&c.relation);
                    p.attribute = Some((k.clone(), v.into()));
                    p
                })
                .collect();
            let total = alternative
                .iter()
                .map(|p| self.graph.count(p))
                .collect::<Result<Vec<_>>>()?
                .iter()
                .sum::<u64>();
            if total < size {
                size = total;
                best = alternative;
            }
        }
        Ok(best)
    }
    pub fn facts(&mut self, c: &RelationalEdge, row: Row, out: &mut Vec<Row>) -> Result<()> {
        let probes = self.probes(c, &row.bindings)?;
        let owned = self
            .scope
            .clone()
            .map(|s| self.owned_subjects(&s))
            .transpose()?;
        let graph = self.graph;
        for p in probes {
            self.check()?;
            graph.facts(&p, &mut |fact| {
                self.tick()?;
                self.examine()?;
                if let Some(scope) = &self.scope
                    && !matches!(c.relation.as_str(), "ENTITY" | "TYPE" | "INSTANCE_OF")
                    && fact.subject != *scope
                    && !owned.as_ref().unwrap().contains(&fact.subject)
                {
                    return Ok(());
                }
                let mut bindings = row.bindings.clone();
                if !bind(&c.subject, &fact.subject, &mut bindings)
                    || !bind(&c.object, &fact.object, &mut bindings)
                {
                    return Ok(());
                }
                for (k, op, value) in &c.attrs {
                    self.check()?;
                    let actual = attribute(&fact, k)?;
                    if !self.comparisons.compare(&actual, op, value)? {
                        return Ok(());
                    }
                }
                let mut unknown = row.unknown.clone();
                if attribute(&fact, "modality")?.string().as_deref() == Some("may")
                    && !c
                        .attrs
                        .iter()
                        .any(|(k, _, v)| k == "modality" && v == "may")
                {
                    unknown.insert(format!("possible:{}", c.relation));
                }
                out.push(Row {
                    bindings,
                    evidence: row.append(Proof::Fact(fact)),
                    unknown,
                });
                Ok(())
            })?;
        }
        Ok(())
    }
    fn owned_subjects(&mut self, scope: &str) -> Result<Arc<BTreeSet<String>>> {
        if let Some(set) = self.owned.get(scope) {
            return Ok(set.clone());
        }
        let mut set = BTreeSet::new();
        for r in [
            "HAS_OPERATION",
            "HAS_PARAMETER",
            "HAS_CALL",
            "HAS_METHOD",
            "DECLARES",
        ] {
            let mut p = FactProbe::relation(r);
            p.subject = Some(scope.into());
            self.graph.facts(&p, &mut |f| {
                self.check()?;
                set.insert(f.object.clone());
                Ok(())
            })?;
        }
        let set = Arc::new(set);
        self.owned.insert(scope.into(), set.clone());
        Ok(set)
    }
    pub fn operand(&self, text: &str, row: &Row) -> Result<V> {
        if text.starts_with('$') {
            let (role, attr) = text
                .split_once('.')
                .map_or((text, None), |(r, a)| (r, Some(a)));
            let id = row
                .bindings
                .get(role)
                .ok_or_else(|| ExecutionError::Invalid(format!("unbound operand {role}")))?;
            let Some(attr) = attr else {
                return Ok(V::String(id.as_str().into()));
            };
            if let Some(metadata) = self.source.usage_metadata.get(id) {
                return Ok(metadata.get(attr).cloned().unwrap_or(V::Null));
            }
            if let Some(entity) = self.graph.entity(id)? {
                if attr == "name" {
                    return Ok(V::String(entity.name.as_str().into()));
                }
                if let Some(raw) = entity.attrs.get(attr) {
                    return Ok(V::parse(raw)?);
                }
            }
            for relation in ["ENTITY", "OPERATION"] {
                let mut p = FactProbe::relation(relation);
                p.subject = Some(id.clone());
                if let Some(f) = self.graph.first(&p)? {
                    return attribute(&f, attr);
                }
            }
            Ok(V::Null)
        } else if text.starts_with('"') {
            let raw = serde_json::value::RawValue::from_string(text.into())
                .map_err(|e| ExecutionError::Invalid(e.to_string()))?;
            Ok(V::parse(&raw)?)
        } else {
            Ok(V::String(text.into()))
        }
    }
    pub fn closed(&mut self, nodes: &Arc<Vec<Op>>, row: &Row, owner: Option<&str>) -> Result<bool> {
        self.check()?;
        let key = (
            Arc::as_ptr(nodes) as usize,
            row.bindings.clone(),
            owner.map(str::to_owned),
        );
        if let Some(closed) = self.closure_cache.get(&key) {
            return Ok(*closed);
        }
        let closed = self.closed_uncached(nodes, row, owner)?;
        let bytes = 256
            + row
                .bindings
                .iter()
                .map(|(a, b)| 128 + a.len() + b.len())
                .sum::<usize>()
            + owner.map_or(0, str::len);
        if bytes <= 2_000_000 {
            if self.closure_bytes.saturating_add(bytes) > 2_000_000 {
                self.closure_cache.clear();
                self.closure_bytes = 0;
            }
            self.closure_bytes += bytes;
            self.closure_cache.insert(key, closed);
        }
        Ok(closed)
    }
    fn closed_uncached(
        &mut self,
        nodes: &Arc<Vec<Op>>,
        row: &Row,
        owner: Option<&str>,
    ) -> Result<bool> {
        crate::with_stack(|| {
            if !self.preserves(nodes, &mut BTreeSet::new())? {
                return Ok(false);
            }
            let mut domains = BTreeSet::new();
            for node in nodes.iter() {
                if let Kind::Fact(c) = &node.kind
                    && matches!(c.relation.as_str(), "HAS_CALL" | "HAS_PARAMETER")
                    && resolve(&c.subject, &row.bindings).is_some_and(|s| {
                        self.graph
                            .capabilities()
                            .contains(&format!("complete:{s}:{}", c.relation))
                    })
                {
                    domains.insert(c.object.token().to_owned());
                }
            }
            for node in nodes.iter() {
                self.check()?;
                match &node.kind {
                    Kind::Fact(c) => {
                        if c.relation == "ENTITY" && domains.contains(c.subject.token()) {
                            continue;
                        }
                        let subject = owner
                            .map(str::to_owned)
                            .or_else(|| resolve(&c.subject, &row.bindings));
                        if subject.is_none_or(|s| {
                            !self
                                .graph
                                .capabilities()
                                .contains(&format!("complete:{s}:{}", c.relation))
                        }) {
                            return Ok(false);
                        }
                    }
                    Kind::Union(clauses) => {
                        for c in clauses {
                            let subject = owner
                                .map(str::to_owned)
                                .or_else(|| resolve(&c.subject, &row.bindings));
                            if subject.is_none_or(|s| {
                                !self
                                    .graph
                                    .capabilities()
                                    .contains(&format!("complete:{s}:{}", c.relation))
                            }) {
                                return Ok(false);
                            }
                        }
                    }
                    Kind::Path {
                        start,
                        relation,
                        max,
                        ..
                    } if !self.closed_path(start, relation, *max, row)? => return Ok(false),
                    Kind::Match {
                        query, bindings, ..
                    } => {
                        let child = self.plan.queries[query].clone();
                        let seed = bindings
                            .iter()
                            .filter_map(|(public, local)| {
                                row.bindings.get(local).map(|v| {
                                    (
                                        child
                                            .exports
                                            .iter()
                                            .find(|(k, _)| k == public)
                                            .unwrap()
                                            .1
                                            .clone(),
                                        v.clone(),
                                    )
                                })
                            })
                            .collect();
                        if !self.closed(&child.nodes, &Row::seed(seed), owner)? {
                            return Ok(false);
                        }
                    }
                    Kind::Any(b) => {
                        for branch in b {
                            if !self.closed(branch, row, owner)? {
                                return Ok(false);
                            }
                        }
                    }
                    Kind::Optional(b)
                    | Kind::Not { nodes: b, .. }
                    | Kind::Count { nodes: b, .. }
                        if !self.closed(b, row, owner)? =>
                    {
                        return Ok(false);
                    }
                    _ => (),
                }
            }
            Ok(true)
        })
    }
    fn closed_path(&mut self, start: &Term, relation: &str, max: usize, row: &Row) -> Result<bool> {
        let Some(start) = resolve(start, &row.bindings) else {
            return Ok(false);
        };
        let mut seen = BTreeSet::from([start.clone()]);
        let mut pending = std::collections::VecDeque::from([(start, 0usize)]);
        while let Some((subject, depth)) = pending.pop_front() {
            self.check()?;
            if depth >= max {
                continue;
            }
            self.tick()?;
            if !self
                .graph
                .capabilities()
                .contains(&format!("complete:{subject}:{relation}"))
            {
                return Ok(false);
            }
            let mut probe = FactProbe::relation(relation);
            probe.subject = Some(subject);
            let graph = self.graph;
            graph.facts(&probe, &mut |fact| {
                self.check()?;
                self.examine()?;
                if seen.insert(fact.object.clone()) {
                    pending.push_back((fact.object.clone(), depth + 1));
                }
                Ok(())
            })?;
        }
        Ok(true)
    }
    fn preserves(&self, nodes: &Arc<Vec<Op>>, seen: &mut BTreeSet<usize>) -> Result<bool> {
        crate::with_stack(|| {
            let id = Arc::as_ptr(nodes) as usize;
            if !seen.insert(id) {
                return Ok(true);
            }
            for node in nodes.iter() {
                self.check()?;
                match &node.kind {
                    Kind::Receiver(..) | Kind::Source(_) | Kind::Body(_) => return Ok(false),
                    Kind::Match { query, .. } => {
                        if !self.preserves(&self.plan.queries[query].nodes, seen)? {
                            return Ok(false);
                        }
                    }
                    Kind::Any(branches) => {
                        for b in branches {
                            if !self.preserves(b, seen)? {
                                return Ok(false);
                            }
                        }
                    }
                    Kind::Optional(b)
                    | Kind::Not { nodes: b, .. }
                    | Kind::Count { nodes: b, .. } => {
                        if !self.preserves(b, seen)? {
                            return Ok(false);
                        }
                    }
                    Kind::Fact(_)
                    | Kind::Union(_)
                    | Kind::Where(..)
                    | Kind::Different(..)
                    | Kind::Path { .. } => (),
                }
            }
            Ok(true)
        })
    }
}
pub(super) fn attribute(fact: &Fact, key: &str) -> Result<V> {
    fact.attrs
        .get(key)
        .map(|v| V::parse(v))
        .transpose()
        .map(|v| v.unwrap_or(V::Null))
        .map_err(Into::into)
}
