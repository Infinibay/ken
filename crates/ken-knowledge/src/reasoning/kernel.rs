use super::model::{Atom, Key, Rule, digest, unify};
use crate::{Result, invalid};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const MAX_FACTS: usize = 10000;
const MAX_JOBS: usize = 50000;
const MAX_PROOFS: usize = 50000;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct Proof {
    pub kind: String,
    pub source: String,
    pub premises: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub rule: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub(super) struct Fact {
    pub atom: Atom,
    pub proofs: Vec<Proof>,
}
/// JSON object order is part of the saved stochastic join frontier.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct State {
    pub version: u32,
    #[serde(with = "ordered_facts")]
    pub(super) facts: Vec<(String, Fact)>,
    pub(super) jobs: Vec<Job>,
    pub applications: Vec<String>,
    pub rng: u32,
    pub steps: u64,
    pub limits: Vec<String>,
}
mod ordered_facts {
    use super::Fact;
    use serde::{
        Deserializer, Serializer,
        de::{MapAccess, Visitor},
        ser::SerializeMap,
    };
    use std::fmt;
    pub fn serialize<S: Serializer>(
        items: &[(String, Fact)],
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(Some(items.len()))?;
        for (id, fact) in items {
            map.serialize_entry(id, fact)?;
        }
        map.end()
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(
        de: D,
    ) -> std::result::Result<Vec<(String, Fact)>, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Vec<(String, Fact)>;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("an ordered fact object")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let mut values = Vec::new();
                while let Some(entry) = map.next_entry()? {
                    values.push(entry);
                }
                Ok(values)
            }
        }
        de.deserialize_map(Ordered)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub(super) enum Job {
    #[serde(rename = "expand")]
    Expand { fact: String },
    #[serde(rename = "join")]
    Join {
        rule: usize,
        binding: BTreeMap<String, String>,
        premises: Vec<String>,
        remaining: Vec<usize>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        position: Option<usize>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        cursor: Option<usize>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        stop: Option<usize>,
    },
}
type IndexKey = (Key, u8, String, String);
pub struct Kernel {
    pub rules: Vec<Rule>,
    pub state: State,
    lookup: BTreeMap<String, usize>,
    index: BTreeMap<IndexKey, Vec<String>>,
    applied: BTreeSet<String>,
    by_pred: BTreeMap<Key, Vec<(usize, usize)>>,
}
impl Kernel {
    pub fn new(rules: Vec<Rule>, state: Option<State>, seed: i64) -> Result<Self> {
        let state = state.unwrap_or(State {
            version: 1,
            facts: Vec::new(),
            jobs: Vec::new(),
            applications: Vec::new(),
            rng: (seed as u32).max(if seed as u32 == 0 { 1 } else { 0 }),
            steps: 0,
            limits: Vec::new(),
        });
        if state.version != 1 {
            return Err(invalid("Incompatible reasoning checkpoint"));
        }
        let mut kernel = Self {
            rules,
            state,
            lookup: BTreeMap::new(),
            index: BTreeMap::new(),
            applied: BTreeSet::new(),
            by_pred: BTreeMap::new(),
        };
        for i in 0..kernel.state.facts.len() {
            let (id, fact) = kernel.state.facts[i].clone();
            Atom::read(&fact.atom.data(), true)?;
            kernel.lookup.insert(id.clone(), i);
            kernel.index_atom(&id, &fact.atom);
        }
        kernel.applied = kernel.state.applications.iter().cloned().collect();
        for (ri, r) in kernel.rules.iter().enumerate() {
            for (pos, a) in r.body.iter().enumerate() {
                kernel.by_pred.entry(a.key()).or_default().push((ri, pos));
            }
        }
        Ok(kernel)
    }
    fn index_atom(&mut self, id: &str, atom: &Atom) {
        for (kind, s, o) in [
            (0, String::new(), String::new()),
            (1, atom.subject.clone(), String::new()),
            (2, String::new(), atom.object.clone()),
            (3, atom.subject.clone(), atom.object.clone()),
        ] {
            self.index
                .entry((atom.key(), kind, s, o))
                .or_default()
                .push(id.to_owned());
        }
    }
    fn candidates(&self, p: &Atom) -> Vec<String> {
        let (kind, s, o) = if !p.subject.starts_with('?') && !p.object.starts_with('?') {
            (3, p.subject.clone(), p.object.clone())
        } else if !p.subject.starts_with('?') {
            (1, p.subject.clone(), String::new())
        } else if !p.object.starts_with('?') {
            (2, String::new(), p.object.clone())
        } else {
            (0, String::new(), String::new())
        };
        self.index
            .get(&(p.key(), kind, s, o))
            .cloned()
            .unwrap_or_default()
    }
    fn atom(&self, id: &str) -> Option<&Atom> {
        self.lookup.get(id).map(|i| &self.state.facts[*i].1.atom)
    }
    fn enqueue(&mut self, job: Job) {
        if self.state.jobs.len() >= MAX_JOBS {
            self.state.limits = vec!["max_jobs".into()];
        } else {
            self.state.jobs.push(job);
        }
    }
    pub(super) fn add(&mut self, atom: Atom, proof: Proof) {
        let id = atom.id();
        let key = digest(&json!([id, proof]));
        if self.applied.contains(&key) {
            return;
        }
        if self.applied.len() >= MAX_PROOFS {
            self.state.limits = vec!["max_proofs".into()];
            return;
        }
        if !self.lookup.contains_key(&id) {
            if self.lookup.len() >= MAX_FACTS {
                self.state.limits = vec!["max_facts".into()];
                return;
            }
            self.lookup.insert(id.clone(), self.state.facts.len());
            self.state.facts.push((
                id.clone(),
                Fact {
                    atom: atom.clone(),
                    proofs: Vec::new(),
                },
            ));
            self.index_atom(&id, &atom);
            self.enqueue(Job::Expand { fact: id.clone() });
        }
        self.applied.insert(key);
        let index = self.lookup[&id];
        self.state.facts[index].1.proofs.push(proof);
    }
    fn relevant(&self, goal: &Atom) -> BTreeSet<Key> {
        let mut keys = BTreeSet::from([goal.key(), goal.opposite().key()]);
        loop {
            let n = keys.len();
            for r in &self.rules {
                if keys.contains(&r.head.key()) {
                    keys.extend(r.body.iter().map(Atom::key));
                }
            }
            if keys.len() == n {
                return keys;
            }
        }
    }
    pub fn run(&mut self, goal: &Atom, budget: u64) -> Result<Value> {
        let relevant = self.relevant(goal);
        let start = self.state.steps;
        while !self.state.jobs.is_empty()
            && self.state.steps - start < budget
            && self.state.limits.is_empty()
        {
            let mut selected = 0;
            if !self.state.steps.is_multiple_of(10) {
                self.state.rng = self
                    .state
                    .rng
                    .wrapping_mul(1664525)
                    .wrapping_add(1013904223);
                let weights = self
                    .state
                    .jobs
                    .iter()
                    .take(64)
                    .map(|j| {
                        let key = match j {
                            Job::Expand { fact } => self.atom(fact).map(Atom::key),
                            Job::Join { rule, .. } => self.rules.get(*rule).map(|r| r.head.key()),
                        };
                        if key.as_ref().is_some_and(|k| relevant.contains(k)) {
                            4u32
                        } else {
                            1
                        }
                    })
                    .collect::<Vec<_>>();
                let mut pick = self.state.rng % weights.iter().sum::<u32>();
                for (index, weight) in weights.into_iter().enumerate() {
                    selected = index;
                    if pick < weight {
                        break;
                    }
                    pick -= weight;
                }
            }
            let job = self.state.jobs.remove(selected);
            self.state.steps += 1;
            match job {
                Job::Expand { fact } => {
                    let atom = self
                        .atom(&fact)
                        .ok_or_else(|| invalid("Invalid reasoning checkpoint fact"))?
                        .clone();
                    for (ri, pos) in self.by_pred.get(&atom.key()).cloned().unwrap_or_default() {
                        let r = &self.rules[ri];
                        if let Some(binding) = unify(&r.body[pos], &atom, &BTreeMap::new()) {
                            let remaining = (0..r.body.len()).filter(|i| *i != pos).collect();
                            self.enqueue(Job::Join {
                                rule: ri,
                                binding,
                                premises: vec![fact.clone()],
                                remaining,
                                position: None,
                                cursor: None,
                                stop: None,
                            });
                        }
                    }
                }
                join => self.join(join)?,
            }
        }
        self.state.applications = self.applied.iter().cloned().collect();
        let pending = self.state.jobs.len();
        Ok(
            json!({"work":self.state.steps-start,"total_work":self.state.steps,"facts":self.lookup.len(),"pending":pending,"complete":pending==0&&self.state.limits.is_empty(),"limits":if !self.state.limits.is_empty(){self.state.limits.clone()}else if pending>0{vec!["budget".into()]}else{Vec::<String>::new()},"resumable":pending>0&&self.state.limits.is_empty()}),
        )
    }
    fn join(&mut self, job: Job) -> Result<()> {
        let Job::Join {
            rule,
            binding,
            premises,
            remaining,
            position,
            cursor,
            stop,
        } = job
        else {
            unreachable!()
        };
        let r = self
            .rules
            .get(rule)
            .ok_or_else(|| invalid("Invalid reasoning checkpoint rule"))?
            .clone();
        if remaining.is_empty() {
            let atom = r.head.bind(&binding);
            if premises.contains(&atom.id())
                || (atom.predicate == "subclass" && atom.subject == atom.object)
            {
                return Ok(());
            }
            let mut premises = premises;
            premises.sort();
            self.add(
                atom,
                Proof {
                    kind: "deduced".into(),
                    source: r.source,
                    rule: Some(r.id),
                    premises,
                },
            );
            return Ok(());
        }
        if remaining.iter().any(|i| *i >= r.body.len())
            || position.is_some_and(|i| i >= r.body.len())
        {
            return Err(invalid("Invalid reasoning checkpoint position"));
        }
        let position = position.unwrap_or_else(|| {
            *remaining
                .iter()
                .min_by_key(|i| self.candidates(&r.body[**i].bind(&binding)).len())
                .unwrap()
        });
        let p = &r.body[position];
        let candidates = self.candidates(&p.bind(&binding));
        let stop = stop.unwrap_or(candidates.len());
        let cursor = cursor.unwrap_or(0);
        if cursor >= stop {
            return Ok(());
        }
        let Some(id) = candidates.get(cursor) else {
            return Err(invalid("Invalid reasoning checkpoint join cursor"));
        };
        let atom = self
            .atom(id)
            .ok_or_else(|| invalid("Invalid reasoning checkpoint fact"))?;
        let new_binding = unify(p, atom, &binding);
        if cursor + 1 < stop {
            self.enqueue(Job::Join {
                rule,
                binding: binding.clone(),
                premises: premises.clone(),
                remaining: remaining.clone(),
                position: Some(position),
                cursor: Some(cursor + 1),
                stop: Some(stop),
            });
        }
        if let Some(binding) = new_binding {
            let mut next = premises;
            next.push(id.clone());
            self.enqueue(Job::Join {
                rule,
                binding,
                premises: next,
                remaining: remaining.into_iter().filter(|i| *i != position).collect(),
                position: None,
                cursor: None,
                stop: None,
            });
        }
        Ok(())
    }
    fn proof_inner(
        &self,
        id: &str,
        path: &BTreeSet<String>,
        depth: usize,
        remaining: &mut usize,
    ) -> Option<Value> {
        if path.contains(id) || depth == 0 || *remaining == 0 {
            return None;
        }
        *remaining -= 1;
        let index = *self.lookup.get(id)?;
        let record = &self.state.facts[index].1;
        let mut proofs = record.proofs.iter().collect::<Vec<_>>();
        proofs.sort_by_key(|p| p.kind == "deduced");
        let mut next = path.clone();
        next.insert(id.to_owned());
        for support in proofs {
            let children = support
                .premises
                .iter()
                .map(|p| self.proof_inner(p, &next, depth - 1, remaining))
                .collect::<Vec<_>>();
            if children.iter().all(Option::is_some) {
                let children = children.into_iter().map(Option::unwrap).collect::<Vec<_>>();
                return Some(json!({"fact":record.atom,"support":support,"premises":children}));
            }
        }
        None
    }
    pub fn proof(&self, id: &str) -> Option<Value> {
        self.proof_inner(id, &BTreeSet::new(), 50, &mut 300)
    }
    pub fn answers(&self, goal: &Atom, limit: usize) -> Value {
        let mut positives = Vec::new();
        let mut negatives = Vec::new();
        for (id, fact) in &self.state.facts {
            if let Some(b) = unify(goal, &fact.atom, &BTreeMap::new()) {
                positives.push((id, &fact.atom, b));
            }
            if unify(&goal.opposite(), &fact.atom, &BTreeMap::new()).is_some() {
                negatives.push(id);
            }
        }
        let mut status = if positives.is_empty() {
            "unknown"
        } else {
            "supported"
        };
        if goal.variables().is_empty() {
            status = if !positives.is_empty() && !negatives.is_empty() {
                "conflict"
            } else if !negatives.is_empty() {
                "refuted"
            } else {
                status
            };
        } else if positives
            .iter()
            .any(|(_, a, _)| self.lookup.contains_key(&a.opposite().id()))
        {
            status = "conflict";
        }
        let count = positives.len();
        positives.sort_by(|a, b| a.0.cmp(b.0));
        let answers=positives.into_iter().take(limit).map(|(id,a,b)|json!({"fact":a,"binding":b,"proof":self.proof(id),"opposing_proof":self.proof(&a.opposite().id())})).collect::<Vec<_>>();
        json!({"status":status,"answers":answers,"answers_truncated":count>limit,"opposition":if goal.variables().is_empty(){negatives.into_iter().take(limit).map(|id|self.proof(id)).collect::<Vec<_>>()}else{Vec::new()},"proof_note":"Null proof means the explanation depth limit was reached, not absence of support."})
    }
    pub(super) fn missing(&self, query: &Atom) -> Value {
        if !query.variables().is_empty() {
            return json!([]);
        }
        let mut out = Vec::new();
        for r in &self.rules {
            let Some(binding) = unify(&r.head, query, &BTreeMap::new()) else {
                continue;
            };
            let body = r.body.iter().map(|a| a.bind(&binding)).collect::<Vec<_>>();
            if body.iter().any(|a| !a.variables().is_empty()) {
                continue;
            }
            let missing = body
                .into_iter()
                .filter(|a| !self.lookup.contains_key(&a.id()))
                .collect::<Vec<_>>();
            if !missing.is_empty() && !missing.contains(query) {
                let opposing = missing
                    .iter()
                    .filter(|a| self.lookup.contains_key(&a.opposite().id()))
                    .collect::<Vec<_>>();
                out.push(json!({"kind":"conditional_candidate","rule":r.id,"source":r.source,"required":missing,"promoted":false,"known_opposition":opposing,"next_step":"Obtain evidence for these conditions or test them in an assumption world; no causal/probability claim."}));
            }
            if out.len() == 10 {
                break;
            }
        }
        json!(out)
    }
    pub fn fact_count(&self) -> usize {
        self.lookup.len()
    }
}
