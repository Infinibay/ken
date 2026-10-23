//! Lexical visibility resolves identity separately from initialization availability.
use crate::{Program, ProgramError, Scope, Symbol};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Resolution {
    pub symbol: Option<usize>,
    pub status: String,
    pub availability: String,
    pub reason: String,
}
impl Resolution {
    fn unknown(reason: &str) -> Self {
        Self {
            symbol: None,
            status: "unknown".into(),
            availability: "unknown".into(),
            reason: reason.into(),
        }
    }
}
pub struct Environment<'a> {
    scopes: &'a [Scope],
    symbols: &'a [Symbol],
    names: BTreeMap<(usize, &'a str), Vec<usize>>,
}
impl<'a> Environment<'a> {
    pub fn new(program: &'a Program) -> Self {
        let mut names: BTreeMap<_, Vec<_>> = BTreeMap::new();
        for symbol in &program.symbols {
            names
                .entry((symbol.scope, symbol.name.as_str()))
                .or_default()
                .push(symbol.id);
        }
        for items in names.values_mut() {
            items.sort_by(|&a, &b| {
                let a = &program.symbols[a];
                let b = &program.symbols[b];
                b.visible_from
                    .cmp(&a.visible_from)
                    .then_with(|| b.declaration.cmp(&a.declaration))
            });
        }
        Self {
            scopes: &program.scopes,
            symbols: &program.symbols,
            names,
        }
    }
    pub fn execution_scope(&self, mut scope: usize) -> usize {
        while let Some(parent) = self.scopes[scope].parent {
            if matches!(
                self.scopes[scope].kind.as_str(),
                "module" | "callable" | "comprehension" | "deferred_block"
            ) {
                break;
            }
            scope = parent;
        }
        scope
    }
    pub fn resolve(&self, name: &str, scope: i64, point: i64) -> Result<Resolution, ProgramError> {
        let mut scope = usize::try_from(scope)
            .ok()
            .filter(|&s| s < self.scopes.len())
            .ok_or(ProgramError::Invalid("invalid lookup context"))?;
        if point < 0 {
            return Err(ProgramError::Invalid("invalid lookup context"));
        }
        let origin = scope;
        let mut nonlocal_only = false;
        let mut directive_scope = scope;
        while !matches!(
            self.scopes[directive_scope].kind.as_str(),
            "module" | "callable" | "type" | "comprehension"
        ) {
            let Some(parent) = self.scopes[directive_scope].parent else {
                break;
            };
            directive_scope = parent;
        }
        let directive = &self.scopes[directive_scope];
        if directive.global_names.iter().any(|n| n == name) {
            scope = 0;
        } else if directive.nonlocal_names.iter().any(|n| n == name) {
            let Some(parent) = directive.lookup_parent else {
                return Ok(Resolution::unknown("nonlocal_target_missing"));
            };
            scope = parent;
            nonlocal_only = true;
        }
        loop {
            if nonlocal_only && self.scopes[scope].kind == "module" {
                return Ok(Resolution::unknown("nonlocal_target_missing"));
            }
            let candidates: Vec<_> = self
                .names
                .get(&(scope, name))
                .into_iter()
                .flatten()
                .copied()
                .filter(|&i| self.symbols[i].visible_from <= point)
                .collect();
            if let Some(&first) = candidates.first() {
                if candidates.len() > 1
                    && candidates
                        .iter()
                        .any(|&i| matches!(self.symbols[i].kind.as_str(), "callable" | "type"))
                {
                    return Ok(Resolution::unknown("overload_or_redefinition"));
                }
                let symbol = &self.symbols[first];
                let mut availability = "unknown";
                let mut reason = "lexical_binding";
                if symbol.flags.iter().any(|f| {
                    matches!(
                        f.as_str(),
                        "conditional_init" | "dynamic_scope" | "uncertain_lifetime"
                    )
                }) {
                    reason = "path_sensitive_initialization_required";
                } else if self.execution_scope(origin) != self.execution_scope(symbol.scope) {
                    reason = "cross_execution_context";
                } else if let Some(initialized) = symbol.initialized_from {
                    if point >= initialized {
                        availability = "available";
                        reason = "source_initialization";
                    } else {
                        availability = "unavailable";
                        reason = "before_initialization";
                    }
                }
                return Ok(Resolution {
                    symbol: Some(symbol.id),
                    status: "known".into(),
                    availability: availability.into(),
                    reason: reason.into(),
                });
            }
            let Some(parent) = self.scopes[scope].lookup_parent else {
                return Ok(Resolution::unknown("unresolved_name"));
            };
            scope = parent;
        }
    }
}
