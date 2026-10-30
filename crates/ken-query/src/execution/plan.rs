//! Check loose compiler records once; execution sees typed operators only.
use super::{ExecutionError, Result, terms::Comparisons};
use crate::relational::{PlanValue, RelationalEdge, RelationalNode, RelationalQuery, Term};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Clone)]
pub(super) struct Op {
    pub id: usize,
    pub kind: Kind,
}
#[derive(Clone)]
pub(super) enum Kind {
    Fact(RelationalEdge),
    Union(Vec<RelationalEdge>),
    Where(String, String, String),
    Different(String, String),
    Any(Vec<Arc<Vec<Op>>>),
    Match {
        query: String,
        bindings: Vec<(String, String)>,
        proof: String,
    },
    Optional(Arc<Vec<Op>>),
    Not {
        domain: String,
        owner: String,
        nodes: Arc<Vec<Op>>,
    },
    Count {
        role: String,
        comparison: String,
        number: String,
        nodes: Arc<Vec<Op>>,
    },
    Path {
        start: Term,
        relation: String,
        end: Term,
        min: usize,
        max: usize,
        proof: String,
    },
    Receiver(String, String),
    Source(super::source_plan::SourceOp),
    Body(Arc<crate::BodyPattern>),
}
#[derive(Clone)]
pub(super) struct Query {
    pub name: String,
    pub nodes: Arc<Vec<Op>>,
    pub exports: Vec<(String, String)>,
}
pub(super) struct Plan {
    pub root: Arc<Query>,
    pub queries: BTreeMap<String, Arc<Query>>,
}
fn invalid(m: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(m.into())
}
struct Builder<'a> {
    work: usize,
    next: usize,
    relations: BTreeSet<String>,
    comparisons: &'a mut Comparisons,
}
impl Plan {
    pub fn new(
        root: &RelationalQuery,
        relations: &BTreeSet<String>,
        comparisons: &mut Comparisons,
    ) -> Result<Self> {
        comparisons.check()?;
        let mut initial_work = 0usize;
        let mut all_relations = crate::relational::vocabulary().relations.clone();
        for r in relations {
            comparisons.check()?;
            validation_work(&mut initial_work, 1 + r.len() / 64)?;
            all_relations.insert(r.clone());
        }
        let relations = all_relations;
        let mut builder = Builder {
            work: initial_work,
            next: 0,
            relations,
            comparisons,
        };
        let r = Arc::new(builder.query(root)?);
        let mut queries = BTreeMap::new();
        for (name, q) in root.definitions.items() {
            builder.charge(1 + name.len() / 64)?;
            queries.insert(name.clone(), Arc::new(builder.query(q)?));
        }
        let plan = Self { root: r, queries };
        let mut state = Inference {
            interruption: comparisons.interruption(),
            ..Default::default()
        };
        plan.infer(&plan.root, &mut state, 0)?;
        Ok(plan)
    }
    fn infer(&self, q: &Query, state: &mut Inference, depth: usize) -> Result<Kinds> {
        crate::with_stack(|| {
            if depth > 512 {
                return Err(invalid("runtime query dependency depth limit exceeded"));
            }
            let mut kinds = BTreeMap::new();
            self.infer_nodes(&q.nodes, &q.name, &mut kinds, state, depth)?;
            Ok(q.exports
                .iter()
                .map(|(public, role)| {
                    (public.clone(), kinds.get(role).cloned().unwrap_or_default())
                })
                .collect())
        })
    }
    fn infer_nodes(
        &self,
        nodes: &[Op],
        name: &str,
        kinds: &mut Kinds,
        state: &mut Inference,
        depth: usize,
    ) -> Result<()> {
        crate::with_stack(|| {
            if depth > 512 {
                return Err(invalid("runtime plan depth limit exceeded"));
            }
            for n in nodes {
                state.charge(1)?;
                match &n.kind {
                    Kind::Fact(c)
                        if matches!(c.relation.as_str(), "ENTITY" | "IS")
                            && !super::terms::variable(&c.object)
                            && c.object.token() != "_" =>
                    {
                        let allowed = match &c.object {
                            Term::Literal(v) => BTreeSet::from([v.literal.clone()]),
                            Term::Text(v) => v.split('|').map(str::to_owned).collect(),
                        };
                        constrain(kinds, c.subject.token(), allowed, name, state)?;
                    }
                    Kind::Match {
                        query, bindings, ..
                    } => {
                        let child = self
                            .queries
                            .get(query)
                            .ok_or_else(|| invalid(format!("unknown named query {query}")))?;
                        if state.stack.contains(query) {
                            let mut cycle = state.stack.clone();
                            cycle.push(query.clone());
                            return Err(invalid(format!(
                                "query dependency cycle: {}",
                                cycle.join(" -> ")
                            )));
                        }
                        for (public, _) in bindings {
                            if !child.exports.iter().any(|(p, _)| p == public) {
                                return Err(invalid(format!(
                                    "{query}: unknown export role {public}"
                                )));
                            }
                        }
                        if !state.visited.contains_key(query) {
                            state.stack.push(query.clone());
                            let inferred = self.infer(child, state, depth + 1)?;
                            state.stack.pop();
                            state.visited.insert(query.clone(), inferred);
                        }
                        for (public, local) in bindings {
                            constrain(
                                kinds,
                                local,
                                state.visited[query]
                                    .get(public)
                                    .cloned()
                                    .unwrap_or_default(),
                                name,
                                state,
                            )?;
                        }
                    }
                    Kind::Any(branches) => {
                        state.kinds_work(kinds)?;
                        let outer = kinds.clone();
                        let mut alternatives = vec![];
                        for b in branches {
                            state.kinds_work(&outer)?;
                            let mut local = outer.clone();
                            self.infer_nodes(b, name, &mut local, state, depth + 1)?;
                            state.kinds_work(&local)?;
                            alternatives.push(local);
                        }
                        *kinds = outer;
                        if let Some(first) = alternatives.first() {
                            for role in first.keys() {
                                if alternatives.iter().all(|a| a.contains_key(role)) {
                                    let allowed = alternatives
                                        .iter()
                                        .flat_map(|a| a[role].iter().cloned())
                                        .collect();
                                    kinds.insert(role.clone(), allowed);
                                }
                            }
                        }
                    }
                    Kind::Optional(b)
                    | Kind::Not { nodes: b, .. }
                    | Kind::Count { nodes: b, .. } => {
                        state.kinds_work(kinds)?;
                        let mut local = kinds.clone();
                        self.infer_nodes(b, name, &mut local, state, depth + 1)?;
                    }
                    _ => (),
                }
            }
            Ok(())
        })
    }
}
#[derive(Default)]
struct Inference {
    stack: Vec<String>,
    visited: BTreeMap<String, Kinds>,
    work: usize,
    interruption: super::Interruption,
}
type Kinds = BTreeMap<String, BTreeSet<String>>;
fn constrain(
    kinds: &mut Kinds,
    role: &str,
    mut allowed: BTreeSet<String>,
    query: &str,
    state: &mut Inference,
) -> Result<()> {
    for k in &allowed {
        state.charge(1 + k.len() / 64)?;
    }
    if !role.starts_with('$') || allowed.is_empty() {
        return Ok(());
    }
    if let Some(old) = kinds.get(role) {
        allowed.retain(|k| old.contains(k));
        if allowed.is_empty() {
            return Err(invalid(format!(
                "incompatible role kinds for {role} in {query}"
            )));
        }
    }
    kinds.insert(role.into(), allowed);
    Ok(())
}
impl Builder<'_> {
    fn charge(&mut self, n: usize) -> Result<()> {
        self.comparisons.check()?;
        self.work = self.work.saturating_add(n);
        if self.work > 65536 {
            Err(invalid("runtime plan validation work limit exceeded"))
        } else {
            Ok(())
        }
    }
    fn value_work(&mut self, value: &PlanValue) -> Result<()> {
        let mut pending = vec![value];
        while let Some(v) = pending.pop() {
            self.charge(1)?;
            match v {
                PlanValue::Term(v) => {
                    self.charge((v.token().len() + v.literal().map_or(0, str::len)) / 64)?
                }
                PlanValue::Integer(v) => self.charge(v.digits().len() / 64)?,
                PlanValue::Tuple(v) => {
                    self.charge(v.len())?;
                    pending.extend(v);
                }
                PlanValue::Map(v) => {
                    self.charge(v.items().len())?;
                    for (k, v) in v.items() {
                        self.charge(1 + k.len() / 64)?;
                        pending.push(v);
                    }
                }
                PlanValue::Expression(crate::ast::Expression::Query(e)) => {
                    let mut expressions = vec![(e, 0usize)];
                    while let Some((e, depth)) = expressions.pop() {
                        self.charge(1 + (e.kind.len() + e.value.len()) / 64 + e.args.len())?;
                        if depth > 128 {
                            return Err(invalid("source expression depth limit exceeded"));
                        }
                        expressions.extend(e.args.iter().map(|e| (e, depth + 1)));
                    }
                }
                _ => (),
            }
        }
        Ok(())
    }
    fn query(&mut self, q: &RelationalQuery) -> Result<Query> {
        self.charge(1 + q.name.len() / 64)?;
        let mut exports = vec![];
        for (k, v) in q.exports.items() {
            self.charge(1 + (k.len() + v.len()) / 64)?;
            exports.push((k.clone(), v.clone()));
        }
        Ok(Query {
            name: q.name.clone(),
            nodes: self.nodes(&q.nodes, 0)?,
            exports,
        })
    }
    fn edge(&mut self, c: &RelationalEdge) -> Result<RelationalEdge> {
        self.endpoint(&c.subject)?;
        self.endpoint(&c.object)?;
        self.charge(
            1 + (c.subject.token().len() + c.object.token().len() + c.relation.len()) / 64,
        )?;
        if !self.relations.contains(&c.relation) {
            return Err(invalid(format!("unknown graph relation {}", c.relation)));
        }
        for (k, op, v) in &c.attrs {
            self.charge(1 + (k.len() + op.len() + v.len()) / 64)?;
            comparison(op)?;
            if op == "regex" {
                self.comparisons.prepare(v)?;
            }
        }
        Ok(c.clone())
    }
    fn endpoint(&mut self, t: &Term) -> Result<()> {
        self.charge(1 + (t.token().len() + t.literal().map_or(0, str::len)) / 64)?;
        match t {
            Term::Text(v) => self.charge(v.matches('|').count())?,
            Term::Literal(v) => {
                if serde_json::from_str::<String>(&v.token).ok().as_ref() != Some(&v.literal) {
                    return Err(invalid("inconsistent literal endpoint"));
                }
            }
        }
        Ok(())
    }
    fn term(&mut self, v: &PlanValue) -> Result<Term> {
        if let PlanValue::Term(t) = v {
            self.endpoint(t)?;
            Ok(t.clone())
        } else {
            Err(invalid("operator requires an endpoint term"))
        }
    }
    fn nodes(&mut self, nodes: &[RelationalNode], depth: usize) -> Result<Arc<Vec<Op>>> {
        crate::with_stack(|| {
            if depth > 512 {
                return Err(invalid("runtime plan depth limit exceeded"));
            }
            self.charge(1 + nodes.len())?;
            let mut out = vec![];
            for n in nodes {
                self.charge(1 + n.kind.len() / 64 + n.children.len())?;
                match n.kind.as_str() {
                    "any" => {
                        if n.children.is_empty() {
                            return Err(invalid("alternative operator requires branches"));
                        }
                    }
                    "not" | "optional" | "count" => {
                        if n.children.len() != 1 {
                            return Err(invalid("scoped operator requires one branch"));
                        }
                    }
                    _ => {
                        if !n.children.is_empty() {
                            return Err(invalid("leaf operator cannot contain children"));
                        }
                    }
                }

                self.value_work(&n.value)?;
                self.next += 1;
                let id = self.next;
                let branch = |this: &mut Self| -> Result<Arc<Vec<Op>>> {
                    if n.children.len() != 1 {
                        return Err(invalid("scoped operator requires one branch"));
                    }
                    this.nodes(&n.children[0], depth + 1)
                };
                let kind = match n.kind.as_str() {
                    "fact" => {
                        if let PlanValue::Edge(c) = &n.value {
                            Kind::Fact(self.edge(c)?)
                        } else {
                            return Err(invalid("invalid fact record"));
                        }
                    }
                    "fact_union" => {
                        let mut clauses = vec![];
                        for v in tuple(&n.value, None)? {
                            if let PlanValue::Edge(c) = v {
                                clauses.push(self.edge(c)?);
                            } else {
                                return Err(invalid("invalid fact union record"));
                            }
                        }
                        Kind::Union(clauses)
                    }
                    "where" => {
                        let v = tuple(&n.value, Some(3))?;
                        comparison(text(&v[1])?)?;
                        Kind::Where(
                            text(&v[0])?.into(),
                            text(&v[1])?.into(),
                            text(&v[2])?.into(),
                        )
                    }
                    "different" => {
                        let v = tuple(&n.value, Some(2))?;
                        Kind::Different(text(&v[0])?.into(), text(&v[1])?.into())
                    }
                    "source_body" => {
                        let PlanValue::Body(body) = &n.value else {
                            return Err(invalid("invalid BODY pattern"));
                        };
                        super::body_runtime::validate(body, &mut || self.charge(1))?;
                        Kind::Body(Arc::new(body.clone()))
                    }
                    "source_receiver" => {
                        let v = tuple(&n.value, Some(2))?;
                        Kind::Receiver(text(&v[0])?.into(), text(&v[1])?.into())
                    }
                    "source_type"
                    | "source_quantifier"
                    | "source_effective_field"
                    | "source_initializer"
                    | "source_usages" => {
                        let op = super::source_plan::SourceOp::parse(&n.kind, &n.value)?;
                        op.prepare(self.comparisons)?;
                        Kind::Source(op)
                    }
                    "any" => {
                        if n.children.is_empty() {
                            return Err(invalid("alternative operator requires branches"));
                        }
                        Kind::Any(
                            n.children
                                .iter()
                                .map(|b| self.nodes(b, depth + 1))
                                .collect::<Result<_>>()?,
                        )
                    }
                    "match" => {
                        let v = tuple(&n.value, Some(3))?;
                        let PlanValue::Map(b) = &v[1] else {
                            return Err(invalid("invalid named query bindings"));
                        };
                        let mut bindings = vec![];
                        for (k, v) in b.items() {
                            self.charge(1 + (k.len() + text(v)?.len()) / 64)?;
                            bindings.push((k.clone(), text(v)?.into()));
                        }
                        Kind::Match {
                            query: text(&v[0])?.into(),
                            bindings,
                            proof: text(&v[2])?.into(),
                        }
                    }
                    "optional" => Kind::Optional(branch(self)?),
                    "not" => {
                        let v = tuple(&n.value, Some(2))?;
                        Kind::Not {
                            domain: text(&v[0])?.into(),
                            owner: text(&v[1])?.into(),
                            nodes: branch(self)?,
                        }
                    }
                    "count" => {
                        let v = tuple(&n.value, Some(3))?;
                        comparison(text(&v[1])?)?;
                        let number = number(&v[2])?;
                        Kind::Count {
                            role: text(&v[0])?.into(),
                            comparison: count_comparison(text(&v[1])?)?.into(),
                            number,
                            nodes: branch(self)?,
                        }
                    }
                    "path" => {
                        let v = tuple(&n.value, Some(6))?;
                        let min = number(&v[3])?
                            .parse::<usize>()
                            .map_err(|_| invalid("invalid path bound"))?;
                        let max = number(&v[4])?
                            .parse::<usize>()
                            .map_err(|_| invalid("invalid path bound"))?;
                        if min > max || max > 32 {
                            return Err(invalid("path bounds must satisfy 0 <= min <= max <= 32"));
                        }
                        let relation = text(&v[1])?.to_owned();
                        if !self.relations.contains(&relation) {
                            return Err(invalid(format!("unknown graph relation {relation}")));
                        }
                        Kind::Path {
                            start: self.term(&v[0])?,
                            relation,
                            end: self.term(&v[2])?,
                            min,
                            max,
                            proof: text(&v[5])?.into(),
                        }
                    }
                    _ => {
                        return Err(ExecutionError::Unsupported(format!(
                            "relational operator {}",
                            n.kind
                        )));
                    }
                };
                out.push(Op { id, kind });
            }
            Ok(Arc::new(out))
        })
    }
}
fn tuple(v: &PlanValue, len: Option<usize>) -> Result<&[PlanValue]> {
    if let PlanValue::Tuple(v) = v
        && len.is_none_or(|n| v.len() == n)
    {
        return Ok(v);
    }
    Err(invalid("invalid operator tuple"))
}
fn text(v: &PlanValue) -> Result<&str> {
    if let PlanValue::Term(Term::Text(v)) = v {
        Ok(v)
    } else {
        Err(invalid("operator requires a text term"))
    }
}
fn number(v: &PlanValue) -> Result<String> {
    let s = match v {
        PlanValue::Integer(v) => v.digits(),
        _ => text(v)?,
    };
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return Err(invalid("operator requires a nonnegative integer"));
    }
    Ok(s.into())
}
pub(super) fn comparison(s: &str) -> Result<()> {
    if matches!(
        s,
        "=" | "==" | "!=" | "<" | "<=" | ">" | ">=" | "literal" | "not_literal" | "~=" | "regex"
    ) {
        Ok(())
    } else {
        Err(invalid(format!("unsupported comparison {s}")))
    }
}

fn validation_work(work: &mut usize, units: usize) -> Result<()> {
    *work = work.saturating_add(units);
    if *work > 65536 {
        Err(invalid("runtime plan validation work limit exceeded"))
    } else {
        Ok(())
    }
}

impl Inference {
    fn charge(&mut self, n: usize) -> Result<()> {
        self.interruption.check()?;
        validation_work(&mut self.work, n)
    }
    fn kinds_work(&mut self, kinds: &Kinds) -> Result<()> {
        self.charge(1)?;
        for (role, allowed) in kinds {
            self.charge(1 + role.len() / 64)?;
            for kind in allowed {
                self.charge(1 + kind.len() / 64)?;
            }
        }
        Ok(())
    }
}
fn count_comparison(s: &str) -> Result<&str> {
    match s {
        "=" | "==" | "literal" => Ok("="),
        "!=" | "not_literal" => Ok("!="),
        "<" | "<=" | ">" | ">=" => Ok(s),
        _ => Err(invalid("count requires a numeric comparison")),
    }
}
