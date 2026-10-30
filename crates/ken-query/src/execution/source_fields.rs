//! Effective field places retain access identity and lexical declaration identity.
use super::{
    ExecutionError, Result,
    source::{SourceRuntime, attr, string},
};
use std::collections::{BTreeMap, BTreeSet};
pub(super) struct Place {
    pub access: String,
    pub declaration: Option<String>,
    pub reason: Option<&'static str>,
    pub chain: Vec<String>,
}
struct Members {
    fields: BTreeMap<String, String>,
    methods: BTreeSet<String>,
}
impl SourceRuntime<'_> {
    fn members(&mut self, owner: &str) -> Result<Members> {
        let mut fields = BTreeMap::new();
        let mut methods = BTreeSet::new();
        for f in self.rows("HAS_FIELD", Some(owner), None)? {
            if let Some(e) = self.entity(&f.object)? {
                fields.insert(e.name.clone(), e.id.clone());
            }
        }
        for f in self.rows("HAS_METHOD", Some(owner), None)? {
            if let Some(e) = self.entity(&f.object)? {
                methods.insert(e.name.clone());
            }
        }
        Ok(Members { fields, methods })
    }
    pub(super) fn visible(&mut self, owner: &str) -> Result<Vec<Place>> {
        let mut chain = vec![];
        let mut current = owner.to_owned();
        let mut unknown = None;
        let mut members = BTreeMap::new();
        while !current.is_empty() {
            (self.tick)()?;
            if chain.contains(&current) || chain.len() >= 32 {
                unknown = Some("cyclic_or_deep_ancestry");
                break;
            }
            chain.push(current.clone());
            members.insert(current.clone(), self.members(&current)?);
            let mut bases = self
                .rows("SUBTYPE_OF", Some(&current), None)?
                .iter()
                .map(|f| f.object.clone())
                .collect::<BTreeSet<_>>();
            let spellings = self
                .rows("BASE_NAME", Some(&current), None)?
                .iter()
                .map(|f| f.object.clone())
                .collect::<BTreeSet<_>>();
            if bases.len() != spellings.len() {
                unknown = Some("unresolved_ancestry");
                break;
            }
            if let Some(e) = self.entity(&current)?
                && string(&e.attrs, "language")?
                    .as_deref()
                    .is_some_and(|v| matches!(v, "java" | "csharp"))
            {
                let mut classes = BTreeSet::new();
                for base in bases {
                    if self.entity(&base)?.is_some_and(|e| e.kind == "CLASS") {
                        classes.insert(base);
                    }
                }
                bases = classes;
            }
            if bases.len() > 1 {
                unknown = Some("multiple_inheritance");
                break;
            }
            current = bases.into_iter().next().unwrap_or_default();
        }
        let Some(local) = members.get(owner) else {
            return Ok(vec![]);
        };
        let mut names = local.fields.keys().cloned().collect::<BTreeSet<_>>();
        if unknown.is_none() {
            for m in members.values() {
                names.extend(m.fields.keys().cloned());
            }
        }
        let mut result = vec![];
        for name in names {
            (self.tick)()?;
            let access = members[owner].fields.get(&name).cloned();
            let mut declaration = None;
            let mut reason = unknown;
            if reason.is_none() {
                for ancestor in &chain {
                    let m = &members[ancestor];
                    if m.methods.contains(&name) {
                        reason = Some("descriptor_or_method_shadow");
                        break;
                    }
                    let Some(id) = m.fields.get(&name) else {
                        continue;
                    };
                    let e = self.entity(id)?.ok_or_else(|| {
                        ExecutionError::Invalid("field declaration missing".into())
                    })?;
                    if attr(&e.attrs, "declared")?.truthy() {
                        if ancestor != owner
                            && (name.starts_with('#')
                                || name.starts_with("__") && !name.ends_with("__")
                                || string(&e.attrs, "visibility")?.as_deref() == Some("private"))
                        {
                            reason = Some("private_inherited_field");
                            break;
                        }
                        declaration = Some(id.clone());
                        break;
                    }
                }
                if declaration.is_none() && reason.is_none() {
                    declaration = access.clone();
                }
            }
            if let Some(access) = access.or_else(|| declaration.clone()) {
                result.push(Place {
                    access,
                    declaration,
                    reason,
                    chain: chain.clone(),
                });
            }
        }
        Ok(result)
    }
}
