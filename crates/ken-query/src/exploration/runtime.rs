use super::{
    plan::{atoms, links, may_fail},
    *,
};
use crate::{
    Scan, Step,
    ast::Expr,
    execution::{
        Cancellation,
        regex_runtime::{Dialect, Pattern},
        values::{Value, arithmetic, compare, unary},
    },
};
use serde_json::{Value as Json, json};
use std::{
    cmp::Ordering,
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
    time::Instant,
};
#[derive(Clone, Default)]
pub struct SyntaxExecutionOptions {
    pub reference: bool,
    pub profile: bool,
    pub cancellation: Cancellation,
    pub deadline: Option<Instant>,
    pub max_states: Option<u64>,
    pub max_rows: Option<u64>,
}
#[derive(Clone, Debug, Default)]
pub struct SyntaxOutcome {
    pub rows: Vec<Vec<Value>>,
    pub complete: bool,
    pub reason: Option<String>,
    pub unknown_candidates: u64,
    pub results_truncated: bool,
    pub plan: Vec<Json>,
    pub states: u64,
    pub scanned_nodes: u64,
    pub query_ms: f64,
    pub operator_profile: Vec<Json>,
}
#[derive(Clone)]
enum Term {
    Scalar(Value),
    Node(Arc<SyntaxUnit>, usize),
    Tuple(Vec<Term>),
}
impl Term {
    fn scalar(&self) -> Value {
        match self {
            Self::Scalar(v) => v.clone(),
            Self::Node(t, i) => t.record(*i),
            Self::Tuple(v) => Value::tuple(v.iter().map(Self::scalar).collect()),
        }
    }
    fn unknown(&self) -> bool {
        match self {
            Self::Scalar(v) => {
                v.is_unknown()
                    || matches!(v,Value::Tuple(values) if values.iter().any(|v|Term::Scalar(v.clone()).unknown()))
            }
            Self::Tuple(v) => v.iter().any(Self::unknown),
            _ => false,
        }
    }
    fn key(&self) -> Result<String> {
        match self {
            Self::Node(t, i) => Ok(format!("SyntaxValue:{}", t.local_id(*i))),
            Self::Tuple(v) => {
                serde_json::to_string(&v.iter().map(Self::key).collect::<Result<Vec<_>>>()?)
                    .map_err(|e| invalid(e.to_string()))
            }
            Self::Scalar(v) => v.identity(),
        }
    }
    fn is_false(&self) -> bool {
        self.scalar().is_false()
    }
    fn is_true(&self) -> bool {
        self.scalar().is_true()
    }
}
type Frame = BTreeMap<String, Term>;
type Link = (String, String, bool);
struct Runtime<'a> {
    units: &'a [Arc<SyntaxUnit>],
    options: SyntaxExecutionOptions,
    coverage: bool,
    states: u64,
    scanned: u64,
    unknown: u64,
    patterns: BTreeMap<String, Pattern>,
    stats: BTreeMap<String, (u64, u64)>,
    depth: usize,
}
impl Runtime<'_> {
    fn check(&mut self) -> Result<()> {
        self.states += 1;
        if self.options.cancellation.is_cancelled() {
            Err(ExecutionError::Exhausted("cancelled"))
        } else if self.options.deadline.is_some_and(|d| Instant::now() >= d) {
            Err(ExecutionError::Exhausted("timeout"))
        } else if self.options.max_states.is_some_and(|n| self.states > n) {
            Err(ExecutionError::Exhausted("max_states"))
        } else {
            Ok(())
        }
    }
    fn regex(&mut self, value: &Term, e: &Expr) -> Result<Term> {
        let Value::Scalar(ken_program::value::GraphValue::String(text)) = value.scalar() else {
            return Ok(Term::Scalar(Value::unknown("regex_input_unknown")));
        };
        self.check()?;
        if !self.patterns.contains_key(&e.value) {
            let (raw, flags) = e
                .value
                .strip_prefix('/')
                .and_then(|v| v.rsplit_once('/'))
                .ok_or_else(|| invalid("invalid regex spelling"))?;
            let pattern = Pattern::compile(raw, flags, Dialect::Regex, &mut || self.check())?;
            self.patterns.insert(e.value.clone(), pattern);
        }
        let pattern = self.patterns[&e.value].clone();
        Ok(Term::Scalar(Value::boolean(
            pattern.is_match(&text, &mut || self.check())?,
        )))
    }
    fn exact(&mut self, scan: &Scan) -> Result<BTreeMap<String, Value>> {
        scan.properties
            .iter()
            .filter(|(_, e)| e.kind == "literal")
            .map(|(k, e)| Ok((k.clone(), Value::literal(&e.value)?)))
            .collect()
    }
    fn candidates(
        &mut self,
        role: &str,
        selector: &str,
        exact: &BTreeMap<String, Value>,
        owner: Option<&str>,
        hints: &[Link],
        frame: &Frame,
    ) -> Result<Vec<Term>> {
        self.check()?;
        let mut candidates = vec![];
        let bound = frame.get(role);
        let parent = owner.and_then(|o| frame.get(o));
        for unit_index in 0..self.units.len() {
            let unit = self.units[unit_index].clone();
            self.check()?;
            if exact
                .get("path")
                .and_then(Value::text)
                .is_some_and(|p| p != unit.path)
                || exact
                    .get("language")
                    .and_then(Value::text)
                    .is_some_and(|p| p != unit.language)
            {
                continue;
            }
            let category = match selector {
                "Expression" => "expression",
                "Statement" => "statement",
                s => s,
            };
            let mut anchor = parent.and_then(|p| {
                if let Term::Node(t, i) = p {
                    Some((t.clone(), *i, true, false))
                } else {
                    None
                }
            });
            if anchor.is_none() {
                for (left, right, direct) in hints {
                    if role == right {
                        if let Some(Term::Node(t, i)) = frame.get(left) {
                            anchor = Some((t.clone(), *i, *direct, false));
                            break;
                        }
                    } else if role == left
                        && let Some(Term::Node(t, i)) = frame.get(right)
                    {
                        anchor = Some((t.clone(), *i, *direct, true));
                        break;
                    }
                }
            }
            if !self.options.reference
                && anchor
                    .as_ref()
                    .is_some_and(|(t, _, _, _)| !Arc::ptr_eq(t, &unit))
            {
                continue;
            }
            let mut posting = if let Some(Term::Node(t, i)) = bound {
                if Arc::ptr_eq(t, &unit) {
                    vec![*i]
                } else {
                    vec![]
                }
            } else if bound.is_some() {
                vec![]
            } else if self.options.reference {
                unit.named.clone()
            } else if let Some((_, i, direct, true)) = anchor.as_ref() {
                let mut ancestors = vec![];
                let mut p = unit.records[*i].parent;
                while let Some(i) = p {
                    self.check()?;
                    ancestors.push(i);
                    if *direct {
                        break;
                    }
                    p = unit.records[i].parent;
                }
                ancestors.reverse();
                ancestors
            } else if let Some(kind) = exact.get("kind").and_then(Value::text) {
                unit.kinds.get(&kind).cloned().unwrap_or_default()
            } else if let Some(native) = exact.get("native_kind").and_then(Value::text) {
                unit.natives.get(&native).cloned().unwrap_or_default()
            } else if matches!(category, "expression" | "statement") {
                unit.categories.get(category).cloned().unwrap_or_default()
            } else {
                unit.named.clone()
            };
            if !self.options.reference
                && bound.is_none()
                && let Some((_, i, direct, false)) = anchor
            {
                let lo = posting.partition_point(|p| *p <= i);
                let hi = posting.partition_point(|p| *p < unit.records[i].subtree_end);
                posting = posting[lo..hi]
                    .iter()
                    .copied()
                    .filter(|p| !direct || unit.records[*p].parent == Some(i))
                    .collect();
            }
            for i in posting {
                self.check()?;
                self.scanned += 1;
                self.stats.entry(role.into()).or_default().0 += 1;
                let r = &unit.records[i];
                if matches!(category, "expression" | "statement") && r.category != category {
                    continue;
                }
                if !related(role, &unit, i, parent, hints, frame) {
                    continue;
                }
                let mut allowed = true;
                for (k, v) in exact {
                    let actual = unit.property(i, k);
                    if !actual.is_unknown() && actual.identity()? != v.identity()? {
                        allowed = false;
                        break;
                    }
                }
                if allowed {
                    self.stats.entry(role.into()).or_default().1 += 1;
                    candidates.push(Term::Node(unit.clone(), i));
                }
            }
        }
        Ok(candidates)
    }
    fn expr(&mut self, e: &Expr, frame: &Frame) -> Result<Term> {
        self.check()?;
        self.depth += 1;
        if self.depth > 128 {
            self.depth -= 1;
            return Err(ExecutionError::Exhausted("expression_depth"));
        }
        let result = crate::with_stack(|| self.eval(e, frame));
        self.depth -= 1;
        result
    }
    fn eval(&mut self, e: &Expr, f: &Frame) -> Result<Term> {
        match e.kind.as_str() {
            "literal" => Ok(Term::Scalar(Value::literal(&e.value)?)),
            "role" => Ok(f.get(&e.value).cloned().unwrap_or_else(unknown)),
            "member" => {
                let t = self.expr(&e.args[0], f)?;
                Ok(if let Term::Node(t, i) = t {
                    Term::Scalar(t.property(i, &e.value))
                } else {
                    unknown()
                })
            }
            "list" => Ok(Term::Tuple(
                e.args
                    .iter()
                    .map(|a| self.expr(a, f))
                    .collect::<Result<_>>()?,
            )),
            "unary" => {
                let a = self.expr(&e.args[0], f)?;
                Ok(Term::Scalar(unary(&e.value, &a.scalar())?))
            }
            "binary" => {
                let a = self.expr(&e.args[0], f)?;
                if e.value == "and" && a.is_false() {
                    return Ok(a);
                }
                if e.value == "or" && a.is_true() {
                    return Ok(a);
                }
                if e.value == "matches" {
                    return self.regex(&a, &e.args[1]);
                }
                let b = self.expr(&e.args[1], f)?;
                if e.value == "and" {
                    return Ok(Term::Scalar(a.scalar().and(b.scalar())));
                }
                if e.value == "or" {
                    return Ok(Term::Scalar(a.scalar().or(b.scalar())));
                }
                if e.value == "in" && matches!(&b,Term::Tuple(v) if v.is_empty()) {
                    return Ok(Term::Scalar(Value::boolean(false)));
                }
                if a.unknown() || b.unknown() {
                    return Ok(if a.scalar().is_unknown() {
                        a
                    } else if b.scalar().is_unknown() {
                        b
                    } else {
                        unknown()
                    });
                }
                let result = match e.value.as_str() {
                    "==" => Value::boolean(a.key()? == b.key()?),
                    "!=" => Value::boolean(a.key()? != b.key()?),
                    "in" => {
                        if let Term::Tuple(values) = b {
                            let key = a.key()?;
                            let mut found = false;
                            for value in values {
                                if value.key()? == key {
                                    found = true;
                                    break;
                                }
                            }
                            Value::boolean(found)
                        } else {
                            return Err(invalid("membership requires a tuple"));
                        }
                    }
                    "<" | ">" | "<=" | ">=" => {
                        let o = compare(&a.scalar(), &b.scalar())?;
                        Value::boolean(match e.value.as_str() {
                            "<" => o.is_lt(),
                            ">" => o.is_gt(),
                            "<=" => !o.is_gt(),
                            _ => !o.is_lt(),
                        })
                    }
                    op => arithmetic(op, &a.scalar(), &b.scalar())?,
                };
                Ok(Term::Scalar(result))
            }
            "call" => {
                let args = e
                    .args
                    .iter()
                    .map(|a| self.expr(&a.args[0], f))
                    .collect::<Result<Vec<_>>>()?;
                self.check()?;
                let value = match (e.value.as_str(), args.as_slice()) {
                    ("stable_id", [Term::Node(t, i)]) => Value::string(t.local_id(*i)),
                    ("kind_is", [Term::Node(t, i), s]) => {
                        let s = s.scalar().text();
                        Value::boolean(
                            s.as_deref() == Some("node")
                                || s.as_deref() == Some(t.records[*i].category.as_str()),
                        )
                    }
                    ("in_directory", [Term::Node(t, _), s]) => Value::boolean(
                        s.scalar()
                            .text()
                            .is_some_and(|s| t.path.split('/').rev().skip(1).any(|v| v == s)),
                    ),
                    (
                        "contains" | "contains_direct" | "owns",
                        [Term::Node(a, i), Term::Node(b, j)],
                    ) => Value::boolean(
                        Arc::ptr_eq(a, b)
                            && if e.value == "contains" {
                                i < j && *j < a.records[*i].subtree_end
                            } else {
                                b.records[*j].parent == Some(*i)
                            },
                    ),
                    _ => Value::unknown("unknown"),
                };
                Ok(Term::Scalar(value))
            }
            "quantifier" | "aggregate" => self.quantify(e, f),
            _ => Err(ExecutionError::Unsupported(format!(
                "syntax expression {}",
                e.kind
            ))),
        }
    }
    fn quantify(&mut self, e: &Expr, frame: &Frame) -> Result<Term> {
        let hints = if may_fail(e) {
            vec![]
        } else {
            links(std::iter::once(&e.args[0]))
        };
        let mut closed = frame
            .iter()
            .filter_map(|(r, v)| {
                if let Term::Node(t, i) = v {
                    (t.records[*i].flags & 6 == 0).then_some(r.clone())
                } else {
                    None
                }
            })
            .collect::<BTreeSet<_>>();
        for _ in &e.parameters {
            for (a, b, _) in &hints {
                if closed.contains(a) {
                    closed.insert(b.clone());
                }
            }
        }
        let mut uncertain =
            !self.coverage && !e.parameters.iter().all(|p| closed.contains(&p.role));
        let mut projected = BTreeSet::new();
        let mut decisive = None;
        self.quantifier_frames(e, 0, frame, &hints, &mut |runtime, local| {
            let truth = runtime.expr(&e.args[0], local)?;
            if truth.is_false() { return Ok(false); }
            if truth.unknown()
                || e.parameters.iter().any(|p| matches!(local.get(&p.role), Some(Term::Node(t,i)) if t.records[*i].flags & 6 != 0))
            {
                uncertain = true;
                return Ok(false);
            }
            if e.value == "exists" { decisive = Some(true); return Ok(true); }
            let value = if let Some(p) = e.args.get(1) {
                runtime.expr(p, local)?
            } else {
                Term::Tuple(vec![])
            };
            if e.value == "forall" && value.is_false() {
                decisive = Some(false);
                return Ok(true);
            }
            if value.unknown() { uncertain = true; }
            else { projected.insert(value.key()?); }
            Ok(false)
        })?;
        Ok(Term::Scalar(if let Some(value) = decisive {
            Value::boolean(value)
        } else if uncertain {
            Value::unknown("incomplete_syntax_domain")
        } else if e.value == "count" {
            Value::integer(projected.len())
        } else {
            Value::boolean(e.value == "forall")
        }))
    }
    fn quantifier_frames(
        &mut self,
        e: &Expr,
        pos: usize,
        frame: &Frame,
        hints: &[Link],
        visit: &mut dyn FnMut(&mut Self, &Frame) -> Result<bool>,
    ) -> Result<bool> {
        self.check()?;
        crate::with_stack(|| {
            if pos == e.parameters.len() {
                return visit(self, frame);
            }
            let p = &e.parameters[pos];
            let mut exact = BTreeMap::new();
            if !may_fail(e) {
                let mut parts = vec![];
                atoms(&e.args[0], &mut parts);
                for atom in parts {
                    if atom.kind == "binary" && atom.value == "==" && atom.args.len() == 2 {
                        for (a, b) in [
                            (&atom.args[0], &atom.args[1]),
                            (&atom.args[1], &atom.args[0]),
                        ] {
                            if a.kind == "member"
                                && a.args
                                    .first()
                                    .is_some_and(|a| a.kind == "role" && a.value == p.role)
                                && b.kind == "literal"
                            {
                                exact.insert(a.value.clone(), Value::literal(&b.value)?);
                            }
                        }
                    }
                }
            }
            for value in self.candidates(&p.role, &p.r#type.name, &exact, None, hints, frame)? {
                let mut f = frame.clone();
                f.insert(p.role.clone(), value);
                if self.quantifier_frames(e, pos + 1, &f, hints, visit)? {
                    return Ok(true);
                }
            }
            Ok(false)
        })
    }
}
fn unknown() -> Term {
    Term::Scalar(Value::unknown("unknown"))
}
fn related(
    role: &str,
    t: &Arc<SyntaxUnit>,
    i: usize,
    parent: Option<&Term>,
    hints: &[Link],
    f: &Frame,
) -> bool {
    if let Some(p) = parent
        && !matches!(p,Term::Node(a,j) if Arc::ptr_eq(a,t)&&t.records[i].parent==Some(*j))
    {
        return false;
    }
    for (a, b, direct) in hints {
        let pair = if role == b {
            f.get(a).map(|p| (p, Term::Node(t.clone(), i)))
        } else if role == a {
            f.get(b).map(|p| (p, Term::Node(t.clone(), i)))
        } else {
            None
        };
        if let Some((bound, node)) = pair {
            let (left, right) = if role == b {
                (bound, &node)
            } else {
                (&node, bound)
            };
            if !matches!((left,right),(Term::Node(a,j),Term::Node(b,k)) if Arc::ptr_eq(a,b)&&if *direct{b.records[*k].parent==Some(*j)}else{j<k&&*k<a.records[*j].subtree_end})
            {
                return false;
            }
        }
    }
    true
}
fn schedule(plan: &SyntaxPlan, runtime: &mut Runtime<'_>) -> Result<Vec<Step>> {
    let steps = plan.steps.clone();
    let mut result = vec![];
    let mut group: Vec<Scan> = vec![];
    let mut bound = BTreeSet::new();
    fn flush(
        group: &mut Vec<Scan>,
        result: &mut Vec<Step>,
        bound: &mut BTreeSet<String>,
        plan: &SyntaxPlan,
        runtime: &mut Runtime<'_>,
    ) -> Result<()> {
        while !group.is_empty() {
            runtime.check()?;
            let mut best = None;
            for (i, s) in group.iter().enumerate() {
                if s.owner.as_ref().is_some_and(|o| !bound.contains(o)) {
                    continue;
                }
                let linked = s.owner.as_ref().is_some_and(|o| bound.contains(o))
                    || plan.links.iter().any(|(a, b, _)| {
                        s.role == *a && bound.contains(b) || s.role == *b && bound.contains(a)
                    });
                let exact = runtime.exact(s)?;
                let estimate = runtime
                    .units
                    .iter()
                    .map(|u| {
                        if let Some(k) = exact.get("kind").and_then(Value::text) {
                            u.kinds.get(&k).map_or(0, Vec::len)
                        } else {
                            u.named.len()
                        }
                    })
                    .sum::<usize>();
                let score = (!linked, estimate, i);
                if runtime.options.reference {
                    best = Some((score, i));
                    break;
                }
                if best.as_ref().is_none_or(|(old, _)| score < *old) {
                    best = Some((score, i));
                }
            }
            let Some((_, i)) = best else {
                return Err(invalid("unbound syntax scan owner"));
            };
            let s = group.remove(i);
            bound.insert(s.role.clone());
            result.push(Step::Scan(s));
        }
        Ok(())
    }
    for step in steps {
        match step {
            Step::Scan(s) if !s.properties.iter().any(|(_, e)| e.kind == "regex") => group.push(s),
            other => {
                flush(&mut group, &mut result, &mut bound, plan, runtime)?;
                match &other {
                    Step::Scan(s) => {
                        bound.insert(s.role.clone());
                    }
                    Step::Action(a) if !a.role.is_empty() => {
                        bound.insert(a.role.clone());
                    }
                    _ => {}
                }
                result.push(other);
            }
        }
    }
    flush(&mut group, &mut result, &mut bound, plan, runtime)?;
    Ok(result)
}
struct Results {
    rows: Vec<(Vec<Value>, Vec<Term>)>,
    seen: BTreeSet<String>,
}
fn frames(
    runtime: &mut Runtime<'_>,
    plan: &SyntaxPlan,
    schedule: &[Step],
    position: usize,
    frame: &Frame,
    uncertain: bool,
    output: &mut Results,
) -> Result<()> {
    runtime.check()?;
    if position == schedule.len() {
        let projected = plan
            .program
            .projection
            .iter()
            .map(|e| runtime.expr(&e.args[0], frame))
            .collect::<Result<Vec<_>>>()?;
        let ordered = plan
            .program
            .ordering
            .iter()
            .map(|e| runtime.expr(&e.args[0], frame))
            .collect::<Result<Vec<_>>>()?;
        if uncertain || projected.iter().chain(&ordered).any(Term::unknown) {
            runtime.unknown += 1;
            return Ok(());
        }
        let key = serde_json::to_string(
            &projected
                .iter()
                .map(Term::key)
                .collect::<Result<Vec<_>>>()?,
        )
        .map_err(|e| invalid(e.to_string()))?;
        if output.seen.contains(&key) {
            return Ok(());
        }
        if runtime
            .options
            .max_rows
            .is_some_and(|max| output.rows.len() as u64 >= max)
        {
            return Err(ExecutionError::Exhausted("max_rows"));
        }
        output.seen.insert(key);
        output
            .rows
            .push((projected.iter().map(Term::scalar).collect(), ordered));
        return Ok(());
    }
    crate::with_stack(|| match &schedule[position] {
        Step::Action(a) => {
            let value = runtime.expr(&a.expression, frame)?;
            if !a.role.is_empty() {
                let mut frame = frame.clone();
                frame.insert(a.role.clone(), value);
                frames(
                    runtime,
                    plan,
                    schedule,
                    position + 1,
                    &frame,
                    uncertain,
                    output,
                )
            } else if !value.is_false() {
                frames(
                    runtime,
                    plan,
                    schedule,
                    position + 1,
                    frame,
                    uncertain || value.unknown(),
                    output,
                )
            } else {
                Ok(())
            }
        }
        Step::Scan(scan) => {
            let exact = runtime.exact(scan)?;
            for value in runtime.candidates(
                &scan.role,
                &scan.selector,
                &exact,
                scan.owner.as_deref(),
                &plan.links,
                frame,
            )? {
                let Term::Node(t, i) = &value else {
                    unreachable!()
                };
                let mut uncertain = uncertain
                    || t.records[*i].flags & 6 != 0
                    || exact.keys().any(|k| t.property(*i, k).is_unknown());
                let mut valid = true;
                for (k, e) in &scan.properties {
                    if e.kind == "regex" {
                        let truth = runtime.regex(&Term::Scalar(t.property(*i, k)), e)?;
                        uncertain |= truth.unknown();
                        if truth.is_false() {
                            valid = false;
                            break;
                        }
                    }
                }
                if valid {
                    let mut frame = frame.clone();
                    frame.insert(scan.role.clone(), value);
                    frames(
                        runtime,
                        plan,
                        schedule,
                        position + 1,
                        &frame,
                        uncertain,
                        output,
                    )?;
                }
            }
            Ok(())
        }
        _ => Err(ExecutionError::Unsupported("syntax BODY".into())),
    })
}
pub fn execute(
    plan: &SyntaxPlan,
    units: &[Arc<SyntaxUnit>],
    coverage_complete: bool,
    options: SyntaxExecutionOptions,
) -> Result<SyntaxOutcome> {
    if options.max_states == Some(0) || options.max_rows == Some(0) {
        return Err(invalid("syntax budgets must be positive"));
    }
    let started = Instant::now();
    let mut runtime = Runtime {
        units,
        options,
        coverage: coverage_complete,
        states: 0,
        scanned: 0,
        unknown: 0,
        patterns: BTreeMap::new(),
        stats: BTreeMap::new(),
        depth: 0,
    };
    let mut output = Results {
        rows: vec![],
        seen: BTreeSet::new(),
    };
    let mut physical = vec![];
    let mut truncated = false;
    let result = (|| {
        for branch in if plan.branches.is_empty() {
            std::slice::from_ref(plan)
        } else {
            &plan.branches
        } {
            let scheduled = schedule(branch, &mut runtime)?;
            physical.push(json!(scheduled.iter().map(|s|match s{Step::Scan(s)=>json!({"operator":"explore","role":s.role,"selector":s.selector,"owner":s.owner}),Step::Action(a)=>json!({"operator":"calculate","role":a.role}),_=>Json::Null}).collect::<Vec<_>>()));
            frames(
                &mut runtime,
                branch,
                &scheduled,
                0,
                &Frame::new(),
                false,
                &mut output,
            )?;
        }
        for pos in (0..plan.program.ordering.len()).rev() {
            let mut failure = None;
            let desc = plan.program.ordering[pos].value == "desc";
            output.rows.sort_by(|a, b| {
                let order = runtime
                    .check()
                    .and_then(|_| compare(&a.1[pos].scalar(), &b.1[pos].scalar()));
                match order {
                    Ok(o) => {
                        if desc {
                            o.reverse()
                        } else {
                            o
                        }
                    }
                    Err(e) => {
                        failure = Some(e);
                        Ordering::Equal
                    }
                }
            });
            if let Some(e) = failure {
                return Err(e);
            }
        }
        if let Some(limit) = &plan.program.limit {
            let limit = limit.digits().parse::<usize>().unwrap_or(usize::MAX);
            truncated = output.rows.len() > limit;
            output.rows.truncate(limit);
        }
        Ok(())
    })();
    let reason = result.err().map(|e| match e {
        ExecutionError::Exhausted(reason) => reason.into(),
        other => other.to_string(),
    });
    Ok(SyntaxOutcome {
        rows: output.rows.into_iter().map(|r| r.0).collect(),
        complete: reason.is_none(),
        reason,
        unknown_candidates: runtime.unknown,
        results_truncated: truncated,
        plan: physical,
        states: runtime.states,
        scanned_nodes: runtime.scanned,
        query_ms: started.elapsed().as_secs_f64() * 1000.,
        operator_profile: if runtime.options.profile {
            runtime.stats.into_iter().map(|(role,(candidates,matched))|json!({"role":role,"candidates":candidates,"matched":matched})).collect()
        } else {
            vec![]
        },
    })
}
