use crate::{Result, invalid, wire};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub fn digest(value: &Value) -> String {
    wire::digest(value)
}
pub(super) fn name(value: &str) -> Result<()> {
    if value.trim().is_empty() || value.chars().count() > 256 {
        Err(invalid(
            "Expected a nonempty identifier of at most 256 characters",
        ))
    } else {
        Ok(())
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Atom {
    pub predicate: String,
    pub subject: String,
    pub object: String,
    #[serde(default)]
    pub negative: bool,
    #[serde(default = "present")]
    pub scope: String,
}
fn present() -> String {
    "present".into()
}
pub(super) type Key = (String, bool, String);
impl Atom {
    pub fn read(data: &Value, ground: bool) -> Result<Self> {
        wire::fields(
            data,
            &["predicate", "subject", "object", "negative", "scope"],
            "Atom fields: predicate, subject, object, negative, scope",
        )?;
        for field in ["predicate", "subject", "object"] {
            let value = data[field].as_str().ok_or_else(|| {
                invalid("Expected a nonempty identifier of at most 256 characters")
            })?;
            name(value)?;
        }
        let scope = data
            .get("scope")
            .map_or(Some("present"), Value::as_str)
            .ok_or_else(|| invalid("Expected a nonempty identifier of at most 256 characters"))?;
        name(scope)?;
        if data.get("negative").is_some_and(|v| !v.is_boolean()) {
            return Err(invalid("negative must be boolean"));
        }
        let atom: Self = serde_json::from_value(data.clone())?;
        if atom.predicate.starts_with('?') || atom.scope.starts_with('?') {
            return Err(invalid("Only subject and object may contain variables"));
        }
        if ground && !atom.variables().is_empty() {
            return Err(invalid("Premises must be ground; variables start with ?"));
        }
        Ok(atom)
    }
    pub fn data(&self) -> Value {
        serde_json::to_value(self).unwrap()
    }
    pub fn variables(&self) -> BTreeSet<String> {
        [&self.subject, &self.object]
            .into_iter()
            .filter(|s| s.starts_with('?'))
            .cloned()
            .collect()
    }
    pub(super) fn key(&self) -> Key {
        (self.predicate.clone(), self.negative, self.scope.clone())
    }
    pub fn id(&self) -> String {
        digest(&self.data())
    }
    pub fn opposite(&self) -> Self {
        let mut a = self.clone();
        a.negative = !a.negative;
        a
    }
    pub fn bind(&self, b: &BTreeMap<String, String>) -> Self {
        let mut a = self.clone();
        a.subject = b
            .get(&self.subject)
            .cloned()
            .unwrap_or_else(|| self.subject.clone());
        a.object = b
            .get(&self.object)
            .cloned()
            .unwrap_or_else(|| self.object.clone());
        a
    }
}
pub fn unify(
    pattern: &Atom,
    fact: &Atom,
    binding: &BTreeMap<String, String>,
) -> Option<BTreeMap<String, String>> {
    if pattern.key() != fact.key() {
        return None;
    }
    let mut out = binding.clone();
    for (p, f) in [
        (&pattern.subject, &fact.subject),
        (&pattern.object, &fact.object),
    ] {
        if p.starts_with('?') {
            if out.get(p).is_some_and(|old| old != f) {
                return None;
            }
            out.insert(p.clone(), f.clone());
        } else if p != f {
            return None;
        }
    }
    Some(out)
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Rule {
    pub body: Vec<Atom>,
    pub head: Atom,
    pub source: String,
    pub id: String,
}
pub(super) fn rule(data: &Value) -> Result<Value> {
    wire::fields(data, &["body", "head"], "Rule fields: body, head")?;
    if data.as_object().unwrap().len() != 2 {
        return Err(invalid("Rule fields: body, head"));
    }
    let body = data["body"]
        .as_array()
        .filter(|b| (1..=3).contains(&b.len()))
        .ok_or_else(|| invalid("Rules require one to three premises"))?
        .iter()
        .map(|a| Atom::read(a, false))
        .collect::<Result<Vec<_>>>()?;
    let head = Atom::read(&data["head"], false)?;
    let vars = body
        .iter()
        .flat_map(Atom::variables)
        .collect::<BTreeSet<_>>();
    if !head.variables().is_subset(&vars) {
        return Err(invalid("Head variables must be bound in the body"));
    }
    Ok(json!({"body":body,"head":head}))
}
pub(super) fn sourced(data: &Value, source: &str, id: String) -> Result<Rule> {
    Ok(Rule {
        body: data["body"]
            .as_array()
            .ok_or_else(|| invalid("invalid rule body"))?
            .iter()
            .map(|a| Atom::read(a, false))
            .collect::<Result<Vec<_>>>()?,
        head: Atom::read(&data["head"], false)?,
        source: source.to_owned(),
        id,
    })
}
pub(super) fn builtin_rules(atoms: &[Atom]) -> Vec<Rule> {
    let scopes = atoms
        .iter()
        .map(|a| a.scope.clone())
        .collect::<BTreeSet<_>>();
    let predicates = atoms
        .iter()
        .filter(|a| a.predicate.starts_with("all/"))
        .map(|a| a.predicate.clone())
        .collect::<BTreeSet<_>>();
    let mut out = Vec::new();
    for scope in scopes {
        let a = |p: &str, s: &str, o: &str, n: bool| Atom {
            predicate: p.into(),
            subject: s.into(),
            object: o.into(),
            negative: n,
            scope: scope.clone(),
        };
        let mut add = |body: Vec<Atom>, head: Atom| {
            let data = json!({"body":body,"head":head});
            out.push(Rule {
                body,
                head,
                source: "@builtin".into(),
                id: digest(&data),
            });
        };
        add(
            vec![
                a("subclass", "?a", "?b", false),
                a("subclass", "?b", "?c", false),
            ],
            a("subclass", "?a", "?c", false),
        );
        add(
            vec![
                a("type", "?x", "?a", false),
                a("subclass", "?a", "?b", false),
            ],
            a("type", "?x", "?b", false),
        );
        for p in &predicates {
            for n in [false, true] {
                add(
                    vec![a("type", "?x", "?c", false), a(p, "?c", "?o", n)],
                    a(&p[4..], "?x", "?o", n),
                );
                add(
                    vec![a("subclass", "?a", "?b", false), a(p, "?b", "?o", n)],
                    a(p, "?a", "?o", n),
                );
            }
        }
    }
    out
}
