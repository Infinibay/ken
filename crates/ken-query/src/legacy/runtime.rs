use super::*;
use crate::execution::{
    Comparisons, Execution, ExecutionError, ExecutionOptions, FactProbe, GraphRead, Interruption,
    Result,
};
use ken_program::{Fact, value::GraphValue};
use std::{sync::Arc, time::Instant};

type Bindings = BTreeMap<String, String>;
#[derive(Clone, Default)]
struct Row {
    bindings: Bindings,
    evidence: Vec<Arc<Fact>>,
}
const STOP: &str = "__legacy_first_hit";
fn resolve(term: &str, bindings: &Bindings) -> Option<String> {
    if term == "_" || term.contains('|') {
        None
    } else if variable(term) {
        bindings.get(term).cloned()
    } else {
        Some(term.into())
    }
}
fn bind(term: &str, value: &str, bindings: &mut Bindings) -> bool {
    if term == "_" {
        true
    } else if variable(term) {
        if let Some(old) = bindings.get(term) {
            old == value
        } else {
            bindings.insert(term.into(), value.into());
            true
        }
    } else {
        term.split('|').any(|v| v == value)
    }
}
fn probe_matches(probe: &FactProbe, fact: &Fact) -> bool {
    fact.relation == probe.relation
        && probe.subject.as_ref().is_none_or(|s| s == &fact.subject)
        && probe.object.as_ref().is_none_or(|o| o == &fact.object)
}
fn stopped(result: Result<()>) -> Result<()> {
    match result {
        Err(ExecutionError::Exhausted(STOP)) => Ok(()),
        other => other,
    }
}
struct Engine<'a> {
    graph: &'a dyn GraphRead,
    options: ExecutionOptions,
    interruption: Interruption,
    comparisons: Comparisons,
    stats: LegacyStats,
    matches: Vec<LegacyMatch>,
    seen: BTreeSet<(String, Bindings)>,
    unknown: BTreeSet<String>,
    sizes: BTreeMap<FactProbe, u64>,
}
impl Engine<'_> {
    fn tick(&mut self, key: &'static str) -> Result<()> {
        let (counter, maximum) = match key {
            "rows_examined" => (&mut self.stats.rows_examined, self.options.budget.max_rows),
            "path_edges" => (&mut self.stats.path_edges, self.options.budget.max_rows),
            _ => (&mut self.stats.states, self.options.budget.max_states),
        };
        *counter = counter
            .checked_add(1)
            .ok_or(ExecutionError::Exhausted(key))?;
        if maximum.is_some_and(|n| *counter > n) {
            return Err(ExecutionError::Exhausted(key));
        }
        self.interruption.check()
    }
    fn size(&mut self, probe: &FactProbe) -> Result<u64> {
        self.interruption.check()?;
        if let Some(size) = self.sizes.get(probe) {
            return Ok(*size);
        }
        let mut size = 0u64;
        let interruption = &self.interruption;
        self.graph.facts(probe, &mut |f| {
            interruption.check()?;
            if probe_matches(probe, &f) {
                size = size.saturating_add(1);
            }
            Ok(())
        })?;
        self.sizes.insert(probe.clone(), size);
        Ok(size)
    }
    // FactIndex.rows chooses the smaller posting, then binding checks intersect
    // endpoints. Keep this contract, including its observable row counters.
    fn posting(&mut self, c: &Clause, b: &Bindings) -> Result<(FactProbe, u64)> {
        let mut p = FactProbe::relation(&c.relation);
        p.subject = resolve(&c.subject, b);
        let subject_size = self.size(&p)?;
        if let Some(object) = resolve(&c.object, b) {
            let mut other = FactProbe::relation(&c.relation);
            other.object = Some(object);
            let object_size = self.size(&other)?;
            if p.subject.is_none() || object_size < subject_size {
                return Ok((other, object_size));
            }
        }
        Ok((p, subject_size))
    }
    fn emit(
        &mut self,
        c: &Clause,
        b: &Bindings,
        f: Arc<Fact>,
        visit: &mut dyn FnMut(&mut Self, Row) -> Result<bool>,
    ) -> Result<bool> {
        self.tick("rows_examined")?;
        let mut bindings = b.clone();
        if !bind(&c.subject, &f.subject, &mut bindings)
            || !bind(&c.object, &f.object, &mut bindings)
        {
            return Ok(false);
        }
        for (key, op, expected) in &c.attrs {
            let Some(raw) = f.attrs.get(key) else {
                return Ok(false);
            };
            let actual = GraphValue::parse(raw)?;
            if !self.comparisons.compare(&actual, op, expected)? {
                return Ok(false);
            }
        }
        visit(
            self,
            Row {
                bindings,
                evidence: vec![f],
            },
        )
    }
    fn rows(
        &mut self,
        c: &Clause,
        b: &Bindings,
        visit: &mut dyn FnMut(&mut Self, Row) -> Result<bool>,
    ) -> Result<()> {
        self.interruption.check()?;
        if c.maximum == 1 {
            let (probe, _) = self.posting(c, b)?;
            let graph = self.graph;
            return stopped(graph.facts(&probe, &mut |f| {
                self.interruption.check()?;
                if probe_matches(&probe, &f) && self.emit(c, b, f, visit)? {
                    return Err(ExecutionError::Exhausted(STOP));
                }
                Ok(())
            }));
        }
        if !c.attrs.is_empty() {
            return Err(ExecutionError::Invalid(
                "path clauses do not accept edge attributes".into(),
            ));
        }
        let subject = resolve(&c.subject, b);
        let object = resolve(&c.object, b);
        let starts = if let Some(s) = subject {
            vec![s]
        } else {
            let mut set = BTreeSet::new();
            let probe = FactProbe::relation(&c.relation);
            self.graph.facts(&probe, &mut |f| {
                self.interruption.check()?;
                if probe_matches(&probe, &f) {
                    set.insert(f.subject.clone());
                }
                Ok(())
            })?;
            set.into_iter().collect()
        };
        for start in starts {
            let mut frontier = vec![(start.clone(), Vec::<String>::new())];
            let mut emitted = BTreeSet::new();
            for depth in 1..=c.maximum {
                let mut following = Vec::<(String, Vec<String>)>::new();
                let mut positions = BTreeSet::new();
                for (current, evidence) in &frontier {
                    self.interruption.check()?;
                    let mut probe = FactProbe::relation(&c.relation);
                    probe.subject = Some(current.clone());
                    let graph = self.graph;
                    graph.facts(&probe, &mut |f| {
                        self.interruption.check()?;
                        if probe_matches(&probe, &f) {
                            self.tick("path_edges")?;
                            if positions.insert(f.object.clone()) {
                                let mut proof = evidence.clone();
                                proof.extend(f.evidence.iter().cloned());
                                following.push((f.object.clone(), proof));
                            }
                        }
                        Ok(())
                    })?;
                }
                for (target, evidence) in &following {
                    if depth >= c.minimum
                        && !emitted.contains(target)
                        && object.as_ref().is_none_or(|o| o == target)
                    {
                        emitted.insert(target.clone());
                        let mut attrs = ken_program::Attributes::new();
                        attrs.insert(
                            "depth".into(),
                            serde_json::value::RawValue::from_string(depth.to_string())
                                .map_err(|e| ExecutionError::Invalid(e.to_string()))?,
                        );
                        let fact = Arc::new(Fact {
                            subject: start.clone(),
                            relation: c.relation.clone(),
                            object: target.clone(),
                            attrs,
                            evidence: evidence.clone(),
                        });
                        if self.emit(c, b, fact, visit)? {
                            return Ok(());
                        }
                    }
                }
                frontier = following;
                if frontier.is_empty() {
                    break;
                }
            }
        }
        Ok(())
    }
    fn join(
        &mut self,
        clauses: &[&Clause],
        row: Row,
        visit: &mut dyn FnMut(&mut Self, Row) -> Result<()>,
    ) -> Result<()> {
        self.tick("states")?;
        if clauses.is_empty() {
            return visit(self, row);
        }
        let mut selected = 0;
        let mut minimum = u64::MAX;
        for (i, c) in clauses.iter().enumerate() {
            let (_, size) = self.posting(c, &row.bindings)?;
            if size < minimum {
                minimum = size;
                selected = i;
            }
        }
        let c = clauses[selected];
        let remaining: Vec<_> = clauses
            .iter()
            .enumerate()
            .filter(|(i, _)| *i != selected)
            .map(|(_, c)| *c)
            .collect();
        self.rows(c, &row.bindings, &mut |engine, mut next| {
            let mut proof = row.evidence.clone();
            proof.append(&mut next.evidence);
            next.evidence = proof;
            crate::with_stack(|| engine.join(&remaining, next, visit))?;
            Ok(false)
        })
    }
    fn accept(
        &mut self,
        p: &Pattern,
        variant: &str,
        clauses: &[&Clause],
        mut row: Row,
    ) -> Result<()> {
        for (a, b) in &p.different {
            let a = row.bindings.get(a).ok_or_else(|| {
                ExecutionError::Invalid(
                    "different requires two roles bound by required clauses".into(),
                )
            })?;
            let b = row.bindings.get(b).ok_or_else(|| {
                ExecutionError::Invalid(
                    "different requires two roles bound by required clauses".into(),
                )
            })?;
            if a == b {
                return Ok(());
            }
        }
        let mut missing = self.unknown.clone();
        let optional_total = clauses.iter().filter(|c| c.mode == "optional").count();
        let mut optional_hits = 0;
        for c in clauses.iter().filter(|c| c.mode != "require") {
            self.interruption.check()?;
            let needed = if c.mode == "forbid" && c.capability.is_empty() {
                match c.relation.as_str() {
                    "CALLS" | "TARGET" | "TYPE" | "MAY_TARGET" => "complete_type_resolution",
                    "WAITS_FOR" => "complete_concurrency_flow",
                    "FLOWS_TO" => "complete_dataflow",
                    _ => "syntax",
                }
            } else {
                &c.capability
            };
            if !needed.is_empty() && !self.graph.capabilities().contains(needed) {
                missing.insert(needed.into());
                continue;
            }
            if c.mode == "count" {
                let mut counts = BTreeSet::new();
                let mut count_evidence = vec![];
                let where_clauses: Vec<_> = c.r#where.iter().collect();
                self.rows(c, &row.bindings, &mut |engine, main| {
                    let fact = main.evidence[0].clone();
                    engine.join(&where_clauses, main, &mut |_, enriched| {
                        let key = if !c.distinct.is_empty() {
                            (
                                enriched
                                    .bindings
                                    .get(&c.distinct)
                                    .ok_or_else(|| {
                                        ExecutionError::Invalid(format!(
                                            "unbound count distinct role {}",
                                            c.distinct
                                        ))
                                    })?
                                    .clone(),
                                String::new(),
                            )
                        } else {
                            (fact.subject.clone(), fact.object.clone())
                        };
                        counts.insert(key);
                        count_evidence.extend(enriched.evidence);
                        Ok(())
                    })?;
                    Ok(false)
                })?;
                if !self.comparisons.compare(
                    &GraphValue::Int(counts.len().to_string()),
                    &c.count_op,
                    &c.count.to_string(),
                )? {
                    return Ok(());
                }
                row.evidence.extend(count_evidence);
            } else {
                let mut hit = None;
                self.rows(c, &row.bindings, &mut |_, r| {
                    hit = r.evidence.into_iter().next();
                    Ok(true)
                })?;
                if c.mode == "forbid" && hit.is_some() {
                    return Ok(());
                }
                if c.mode == "optional"
                    && let Some(f) = hit
                {
                    optional_hits += 1;
                    row.evidence.push(f);
                }
            }
        }
        let key = (variant.to_owned(), row.bindings.clone());
        if !self.seen.insert(key) {
            return Ok(());
        }
        if self
            .options
            .budget
            .max_matches
            .is_some_and(|limit| self.matches.len() as u64 >= limit)
        {
            return Err(ExecutionError::Exhausted("max_matches"));
        }
        let required = clauses.iter().filter(|c| c.mode == "require").count();
        let total = required + optional_total;
        if total == 0 {
            return Err(ExecutionError::Invalid(
                "a variant needs a required or optional clause".into(),
            ));
        }
        self.matches.push(LegacyMatch {
            pattern: p.name.clone(),
            variant: variant.into(),
            bindings: row.bindings,
            status: if missing.is_empty() {
                "structural_match"
            } else {
                "unknown"
            }
            .into(),
            unknown: missing.into_iter().collect(),
            optional_hits,
            optional_total,
            evidence_score: round_score((required + optional_hits) as f64 / total as f64),
            evidence: row
                .evidence
                .iter()
                .flat_map(|f| f.evidence.iter().cloned())
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect(),
            facts: row
                .evidence
                .iter()
                .map(|f| LegacyFact {
                    subject: f.subject.clone(),
                    relation: f.relation.clone(),
                    object: f.object.clone(),
                })
                .collect(),
        });
        Ok(())
    }
    fn run(&mut self, p: &Pattern) -> Result<()> {
        self.interruption.check()?;
        for relation in self.graph.relations() {
            let size = self.size(&FactProbe::relation(relation))?;
            if size > 0 {
                self.stats.relations.insert(relation.clone(), size);
            }
        }
        let mut order: Vec<_> = p.ordered_variants().into_iter().cloned().collect();
        if order.is_empty() {
            order.push("default".into());
        }
        for variant in order {
            let clauses: Vec<_> = p
                .clauses
                .iter()
                .chain(p.variants.get(&variant).into_iter().flatten())
                .collect();
            let required: Vec<_> = clauses
                .iter()
                .copied()
                .filter(|c| c.mode == "require")
                .collect();
            self.join(&required, Row::default(), &mut |engine, row| {
                engine.accept(p, &variant, &clauses, row)
            })?;
        }
        Ok(())
    }
}
fn validate(p: &Pattern) -> Result<()> {
    let mut pending: Vec<_> = p
        .clauses
        .iter()
        .chain(p.variants.values().flatten())
        .map(|c| (c, 0))
        .collect();
    while let Some((c, depth)) = pending.pop() {
        if depth > 96 {
            return Err(ExecutionError::Invalid(
                "legacy clause nesting limit exceeded".into(),
            ));
        }
        if !matches!(c.mode.as_str(), "require" | "optional" | "forbid" | "count") {
            return Err(ExecutionError::Invalid(format!(
                "unknown legacy clause mode: {}",
                c.mode
            )));
        }
        if c.minimum < 1 || c.minimum > c.maximum || c.maximum > 32 {
            return Err(ExecutionError::Invalid(
                "path bounds must satisfy 1 <= min <= max <= 32".into(),
            ));
        }
        if c.mode == "count" && !matches!(c.count_op.as_str(), "=" | ">" | "<" | ">=" | "<=") {
            return Err(ExecutionError::Invalid("invalid count comparison".into()));
        }
        pending.extend(c.r#where.iter().map(|c| (c, depth + 1)));
    }
    Ok(())
}
/// Evaluate one pattern against exactly the supplied immutable graph snapshot.
/// Partial matches survive explicit budget exhaustion; missing negative-proof
/// capabilities affect individual matches, while declared capabilities affect
/// the outcome's completeness, matching the original legacy contract.
pub fn execute(
    graph: &dyn GraphRead,
    pattern: &Pattern,
    options: ExecutionOptions,
) -> Result<LegacyOutcome> {
    validate(pattern)?;
    let started = Instant::now();
    let run = Execution::new(options.clone())?;
    let interruption = run.interruption();
    let mut engine = Engine {
        graph,
        options,
        comparisons: Comparisons::new(interruption.clone()),
        interruption,
        stats: LegacyStats::default(),
        matches: vec![],
        seen: BTreeSet::new(),
        unknown: pattern
            .capabilities
            .difference(graph.capabilities())
            .cloned()
            .collect(),
        sizes: BTreeMap::new(),
    };
    match engine.run(pattern) {
        Ok(()) => (),
        Err(ExecutionError::Exhausted(reason)) => {
            engine.unknown.insert(format!("budget:{reason}"));
        }
        Err(e) => return Err(e),
    }
    engine.matches.sort_by(|a, b| {
        b.evidence_score
            .total_cmp(&a.evidence_score)
            .then_with(|| binding_repr(&a.bindings).cmp(&binding_repr(&b.bindings)))
    });
    engine.stats.elapsed_ms =
        (started.elapsed().as_secs_f64() * 1_000_000.).round_ties_even() / 1000.;
    Ok(LegacyOutcome {
        matches: engine.matches,
        complete: engine.unknown.is_empty(),
        unknown: engine.unknown.into_iter().collect(),
        stats: engine.stats,
    })
}
fn binding_repr(bindings: &Bindings) -> String {
    let repr = |s: &str| GraphValue::String(s.into()).repr();
    format!(
        "[{}]",
        bindings
            .iter()
            .map(|(k, v)| format!("({}, {})", repr(k), repr(v)))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

// Python round(value,3) rounds the exact binary input to decimal places. A
// floating multiply by 1000 can erase which side of a decimal tie it was on.
fn round_score(value: f64) -> f64 {
    if value == 0. {
        return 0.;
    }
    let bits = value.to_bits();
    let exponent = ((bits >> 52) & 0x7ff) as i32 - 1023 - 52;
    let mantissa = ((bits & ((1u64 << 52) - 1)) | (1u64 << 52)) as u128;
    let scaled = mantissa * 1000;
    if exponent >= 0 {
        return ((scaled << exponent) as f64) / 1000.;
    }
    let shift = (-exponent) as u32;
    if shift >= 128 {
        return 0.;
    }
    let unit = 1u128 << shift;
    let whole = scaled / unit;
    let remainder = scaled % unit;
    let rounded =
        whole + u128::from(remainder > unit / 2 || (remainder == unit / 2 && whole % 2 == 1));
    rounded as f64 / 1000.
}
