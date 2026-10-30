//! Demand-driven monotone tables for stratified finite ground predicates.
use super::*;
type Key = (String, String);
pub(super) struct Tables {
    groups: BTreeMap<String, usize>,
    arguments: BTreeMap<Key, Vec<Value>>,
    answers: BTreeMap<Key, Value>,
    pending: BTreeMap<usize, VecDeque<Key>>,
    queued: BTreeSet<Key>,
    active: BTreeSet<usize>,
    current: BTreeMap<usize, Key>,
    dependents: BTreeMap<Key, BTreeSet<Key>>,
}
impl Tables {
    pub fn new(groups: BTreeMap<String, usize>) -> Self {
        Self {
            groups,
            arguments: BTreeMap::new(),
            answers: BTreeMap::new(),
            pending: BTreeMap::new(),
            queued: BTreeSet::new(),
            active: BTreeSet::new(),
            current: BTreeMap::new(),
            dependents: BTreeMap::new(),
        }
    }
    fn enqueue(&mut self, key: Key) {
        if self.queued.insert(key.clone()) {
            self.pending
                .entry(self.groups[&key.0])
                .or_default()
                .push_back(key);
        }
    }
}
impl Runtime<'_, '_> {
    pub(super) fn predicate(&mut self, name: &str, arguments: &[Value]) -> Result<Value> {
        if arguments.iter().any(Value::is_unknown) {
            return Ok(Value::unknown("predicate_argument_unknown"));
        }
        let group = *self
            .predicates
            .groups
            .get(name)
            .ok_or_else(|| invalid(format!("unknown predicate {name}")))?;
        let key = (
            name.to_owned(),
            Value::tuple(arguments.to_vec()).identity()?,
        );
        if let Some(current) = self.predicates.current.get(&group) {
            self.predicates
                .dependents
                .entry(key.clone())
                .or_default()
                .insert(current.clone());
        }
        let new = !self.predicates.arguments.contains_key(&key);
        if new {
            self.check()?;
            self.predicates
                .arguments
                .insert(key.clone(), arguments.to_vec());
            self.predicates
                .answers
                .insert(key.clone(), Value::boolean(false));
            self.predicates.enqueue(key.clone());
        }
        if self.predicates.active.contains(&group) || !new {
            return Ok(self.predicates.answers[&key].clone());
        }
        self.predicates.active.insert(group);
        let result = self.saturate(group);
        self.predicates.active.remove(&group);
        self.predicates.current.remove(&group);
        result?;
        Ok(self.predicates.answers[&key].clone())
    }
    fn saturate(&mut self, group: usize) -> Result<()> {
        while let Some(item) = self
            .predicates
            .pending
            .entry(group)
            .or_default()
            .pop_front()
        {
            self.predicates.queued.remove(&item);
            self.check()?;
            self.predicates.current.insert(group, item.clone());
            let pred = self
                .program
                .predicates
                .iter()
                .find(|p| p.name == item.0)
                .cloned()
                .ok_or_else(|| invalid("predicate definition missing"))?;
            let args = &self.predicates.arguments[&item];
            if args.len() != pred.parameters.len() {
                return Err(invalid("predicate argument arity differs"));
            }
            let bindings = pred
                .parameters
                .iter()
                .zip(args)
                .map(|(p, a)| (p.role.clone(), a.clone()))
                .collect();
            let value = self.evaluate(&pred.formula, &bindings)?;
            if rank(&value) > rank(&self.predicates.answers[&item]) {
                self.predicates.answers.insert(item.clone(), value);
                for dependent in self
                    .predicates
                    .dependents
                    .get(&item)
                    .cloned()
                    .unwrap_or_default()
                {
                    self.predicates.enqueue(dependent);
                }
            }
        }
        Ok(())
    }
}
fn rank(value: &Value) -> u8 {
    if value.is_true() {
        2
    } else if value.is_unknown() {
        1
    } else {
        0
    }
}
