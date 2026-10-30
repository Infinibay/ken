//! Bounded alternative proofs and detached result projection.
use super::{EvidenceMode, ExecutionError, Result, terms::Bindings};
use crate::relational::json_string as ascii_json;
use ken_program::Fact;
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
#[derive(Clone)]
pub(super) struct Row {
    pub bindings: Bindings,
    pub evidence: Arc<Vec<Proof>>,
    pub unknown: BTreeSet<String>,
}
impl Row {
    pub fn seed(bindings: Bindings) -> Self {
        Self {
            bindings,
            evidence: Arc::new(vec![]),
            unknown: BTreeSet::new(),
        }
    }
    pub fn append(&self, proof: Proof) -> Arc<Vec<Proof>> {
        let mut out = (*self.evidence).clone();
        out.push(proof);
        Arc::new(out)
    }
}
#[derive(Clone)]
pub(super) enum Proof {
    Source(Arc<Value>),
    Fact(Arc<Fact>),
    Path {
        relation: String,
        nodes: Vec<String>,
    },
    Dependency {
        query: String,
        proof: String,
        evidence: Arc<Vec<Proof>>,
    },
    Optional(Arc<Vec<Proof>>),
    Alternatives {
        items: Vec<Alternative>,
        truncated: bool,
    },
}
#[derive(Clone, PartialEq, Eq)]
pub(super) struct Alternative {
    pub evidence: Arc<Vec<Proof>>,
    pub unknown: BTreeSet<String>,
}
impl PartialEq for Proof {
    fn eq(&self, other: &Self) -> bool {
        crate::with_stack(|| match (self, other) {
            (Self::Source(a), Self::Source(b)) => Arc::ptr_eq(a, b) || a == b,
            (Self::Fact(a), Self::Fact(b)) => {
                Arc::ptr_eq(a, b)
                    || (a.subject == b.subject
                        && a.relation == b.relation
                        && a.object == b.object
                        && a.evidence == b.evidence)
            }
            (
                Self::Path {
                    relation: a,
                    nodes: b,
                },
                Self::Path {
                    relation: c,
                    nodes: d,
                },
            ) => a == c && b == d,
            (
                Self::Dependency {
                    query: a,
                    proof: b,
                    evidence: c,
                },
                Self::Dependency {
                    query: d,
                    proof: e,
                    evidence: f,
                },
            ) => a == d && b == e && c == f,
            (Self::Optional(a), Self::Optional(b)) => a == b,
            (
                Self::Alternatives {
                    items: a,
                    truncated: b,
                },
                Self::Alternatives {
                    items: c,
                    truncated: d,
                },
            ) => a == c && b == d,
            _ => false,
        })
    }
}
impl Eq for Proof {}
impl Proof {
    fn detach(&self, check: &mut dyn FnMut() -> Result<()>, depth: usize) -> Result<Value> {
        crate::with_stack(|| {
            check()?;
            if depth > 512 {
                return Err(ExecutionError::Exhausted("evidence"));
            }
            Ok(match self {
                Self::Source(value) => (**value).clone(),
                Self::Fact(f) => {
                    json!({"subject":f.subject,"relation":f.relation,"object":f.object,"source":f.evidence})
                }
                Self::Path { relation, nodes } => json!({"path":relation,"nodes":nodes}),
                Self::Dependency {
                    query,
                    proof,
                    evidence,
                } => {
                    json!({"query":query,"proof":proof,"evidence":detach_list(evidence,check,depth+1)?})
                }
                Self::Optional(e) => json!({"optional":detach_list(e,check,depth+1)?}),
                Self::Alternatives { items, truncated } => {
                    let mut out = vec![];
                    for p in items {
                        out.push(
                            json!({"evidence":detach_list(&p.evidence,check,depth+1)?,"unknown":p.unknown}),
                        );
                    }
                    json!({"alternatives":out,"truncated":truncated})
                }
            })
        })
    }
}
fn detach_list(
    proofs: &[Proof],
    check: &mut dyn FnMut() -> Result<()>,
    depth: usize,
) -> Result<Vec<Value>> {
    proofs.iter().map(|p| p.detach(check, depth)).collect()
}
/// Shared dependency proofs are a DAG. Measure the expanded public tree with
/// memoization before allocating it; a tiny cached plan must not explode in JSON.
pub(super) fn materialize(
    proofs: &Arc<Vec<Proof>>,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<Vec<Value>> {
    fn measure(
        proofs: &Arc<Vec<Proof>>,
        memo: &mut BTreeMap<usize, usize>,
        depth: usize,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<usize> {
        crate::with_stack(|| {
            check()?;
            if depth > 512 {
                return Err(ExecutionError::Exhausted("evidence"));
            }
            let key = Arc::as_ptr(proofs) as usize;
            if let Some(cost) = memo.get(&key) {
                return Ok(*cost);
            }
            let mut total = 0usize;
            for p in proofs.iter() {
                check()?;
                let cost = match p {
                    Proof::Source(value) => {
                        let mut work = vec![(value.as_ref(), 0usize)];
                        let mut cost = 0usize;
                        while let Some((v, level)) = work.pop() {
                            check()?;
                            cost = cost.saturating_add(1);
                            if level > 128 || cost > 65536 {
                                return Err(ExecutionError::Exhausted("evidence"));
                            }
                            match v {
                                Value::String(s) => cost = cost.saturating_add(s.len() / 64),
                                Value::Array(values) => {
                                    work.extend(values.iter().map(|v| (v, level + 1)))
                                }
                                Value::Object(values) => {
                                    for (k, v) in values {
                                        cost = cost.saturating_add(1 + k.len() / 64);
                                        work.push((v, level + 1));
                                    }
                                }
                                _ => (),
                            }
                        }
                        cost
                    }
                    Proof::Fact(f) => {
                        1 + (f.subject.len() + f.relation.len() + f.object.len()) / 64
                            + f.evidence.iter().map(|s| 1 + s.len() / 64).sum::<usize>()
                    }
                    Proof::Path { relation, nodes } => {
                        1 + relation.len() / 64
                            + nodes.iter().map(|s| 1 + s.len() / 64).sum::<usize>()
                    }
                    Proof::Dependency {
                        query,
                        proof,
                        evidence,
                    } => {
                        1 + (query.len() + proof.len()) / 64
                            + measure(evidence, memo, depth + 1, check)?
                    }
                    Proof::Optional(e) => 1 + measure(e, memo, depth + 1, check)?,
                    Proof::Alternatives { items, .. } => {
                        let mut cost = 1usize;
                        for p in items {
                            cost = cost.saturating_add(
                                1 + measure(&p.evidence, memo, depth + 1, check)?
                                    + p.unknown.iter().map(|s| 1 + s.len() / 64).sum::<usize>(),
                            );
                        }
                        cost
                    }
                };
                total = total.saturating_add(cost);
                if total > 65536 {
                    return Err(ExecutionError::Exhausted("evidence"));
                }
            }
            memo.insert(key, total);
            Ok(total)
        })
    }
    measure(proofs, &mut BTreeMap::new(), 0, check)?;
    detach_list(proofs, check, 0)
}
pub(super) struct Proofs {
    preferred: Row,
    alternatives: Option<Vec<Alternative>>,
    truncated: bool,
}
impl Proofs {
    pub fn new(row: Row) -> Self {
        Self {
            preferred: row,
            alternatives: None,
            truncated: false,
        }
    }
    fn unpack(row: &Row) -> (Vec<Alternative>, bool) {
        if let [Proof::Alternatives { items, truncated }] = row.evidence.as_slice() {
            (items.clone(), *truncated)
        } else {
            (
                vec![Alternative {
                    evidence: row.evidence.clone(),
                    unknown: row.unknown.clone(),
                }],
                false,
            )
        }
    }
    pub fn add(&mut self, row: Row) {
        if self.alternatives.is_none() {
            let (items, truncated) = Self::unpack(&self.preferred);
            self.alternatives = Some(items);
            self.truncated = truncated;
        }
        let (items, truncated) = Self::unpack(&row);
        self.truncated |= truncated;
        let alternatives = self.alternatives.as_mut().unwrap();
        for proof in items {
            let full = alternatives.len() == 16;
            let outranks = full
                && proof.unknown.is_empty()
                && !alternatives.last().unwrap().unknown.is_empty();
            if full && self.truncated && !outranks {
                continue;
            }
            if alternatives.contains(&proof) {
                continue;
            }
            if full {
                self.truncated = true;
                if !outranks {
                    continue;
                }
                alternatives.pop();
            }
            if proof.unknown.is_empty() {
                let pos = alternatives
                    .iter()
                    .position(|p| !p.unknown.is_empty())
                    .unwrap_or(alternatives.len());
                alternatives.insert(pos, proof);
            } else {
                alternatives.push(proof);
            }
        }
        if !self.preferred.unknown.is_empty() && row.unknown.is_empty() {
            self.preferred = row;
        }
    }
    pub fn finish(mut self) -> Row {
        if let Some(items) = self.alternatives {
            self.preferred.evidence = Arc::new(vec![Proof::Alternatives {
                items,
                truncated: self.truncated,
            }]);
        }
        self.preferred
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Match {
    pub bindings: Bindings,
    pub status: String,
    pub unknown: Vec<String>,
    pub evidence: Vec<Value>,
    pub variant: String,
    pub evidence_score: f64,
}
#[derive(Clone, Debug, Serialize)]
pub struct QueryStats {
    pub states: u64,
    pub rows_examined: u64,
    pub elapsed_ms: f64,
    pub dependencies: Vec<String>,
}
#[derive(Clone, Debug, Serialize)]
pub struct QueryOutcome {
    /// Detached usage occurrences for typed public column projection. Proof
    /// truncation never controls whether a captured occurrence has metadata.
    #[serde(skip)]
    pub usage_metadata: BTreeMap<String, BTreeMap<String, ken_program::value::GraphValue>>,
    pub matches: Vec<Match>,
    pub complete: bool,
    pub unknown: Vec<String>,
    pub stats: QueryStats,
}
pub(super) struct Projection {
    pub matches: Vec<Match>,
    pub complete: bool,
    pub unknown: BTreeSet<String>,
}
pub(super) fn project(
    mut rows: Vec<Row>,
    exports: &[(String, String)],
    mode: EvidenceMode,
    max: Option<u64>,
    mut check: impl FnMut() -> Result<()>,
) -> Result<Projection> {
    rows.sort_by(|a, b| {
        (!a.unknown.is_empty())
            .cmp(&(!b.unknown.is_empty()))
            .then_with(|| a.bindings.cmp(&b.bindings))
    });
    let mut groups: Vec<(Proofs, Match)> = vec![];
    let mut positions = BTreeMap::new();
    let mut complete = true;
    let mut unknown = BTreeSet::new();
    for row in rows {
        check()?;
        if !row.unknown.is_empty() && mode == EvidenceMode::Strict {
            unknown.extend(row.unknown);
            continue;
        }
        let binding = exports
            .iter()
            .map(|(public, role)| {
                Ok((
                    format!("${public}"),
                    row.bindings
                        .get(role)
                        .cloned()
                        .ok_or_else(|| ExecutionError::Invalid(format!("unbound export {role}")))?,
                ))
            })
            .collect::<Result<Bindings>>()?;
        if let Some(&i) = positions.get(&binding) {
            let (proofs, _): &mut (Proofs, Match) = &mut groups[i];
            proofs.add(row);
            continue;
        }
        if max.is_some_and(|m| groups.len() as u64 >= m) {
            complete = false;
            unknown.insert("budget:max_matches".into());
            break;
        }
        positions.insert(binding.clone(), groups.len());
        let hit = Match {
            bindings: binding,
            status: if row.unknown.is_empty() {
                "structural_match"
            } else {
                "unknown"
            }
            .into(),
            unknown: row.unknown.iter().cloned().collect(),
            evidence: vec![],
            variant: "default".into(),
            evidence_score: 1.,
        };
        groups.push((Proofs::new(row), hit));
    }
    let mut matches = vec![];
    for (proofs, mut hit) in groups {
        check()?;
        hit.evidence = materialize(&proofs.finish().evidence, &mut check)?;
        matches.push(hit);
    }
    Ok(Projection {
        matches,
        complete,
        unknown,
    })
}
/// Python json.dumps default separators/ensure_ascii and sort_keys=True. It is
/// observable in dependency/path proof bindings, independently of JSON transport.
pub(super) fn python_json(v: &Value) -> String {
    crate::with_stack(|| match v {
        Value::Null => "null".into(),
        Value::Bool(v) => v.to_string(),
        Value::Number(v) => v.to_string(),
        Value::String(s) => ascii_json(s),
        Value::Array(a) => format!(
            "[{}]",
            a.iter().map(python_json).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter()
                .map(|(k, v)| format!("{}: {}", ascii_json(k), python_json(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    })
}
