//! Declaration initializer roots; nested calls are not initializer root values.
use super::{
    OperationProbe, Result,
    source::{SourceRuntime, attr, string},
    source_occurrences::{Initializer, integer, unknown},
};
use std::collections::BTreeSet;
impl SourceRuntime<'_> {
    pub(super) fn initializers(&mut self, binding: &str) -> Result<Vec<Initializer>> {
        let Some(entity) = self.entity(binding)? else {
            return Ok(vec![]);
        };
        if !attr(&entity.attrs, "declared")?.truthy() {
            return Ok(vec![]);
        }
        let start = integer(attr(&entity.attrs, "start_byte")?).unwrap_or(-1);
        let targets = self.rows("ASSIGNMENT_TARGET", None, Some(binding))?;
        let mut result = vec![];
        for target in &targets {
            (self.tick)()?;
            let Some(op) = self.operation(&target.subject)? else {
                result.push(Initializer {
                    assignment: target.subject.clone(),
                    expression: String::new(),
                    call: None,
                    unknown: unknown("initializer_operation_missing"),
                });
                continue;
            };
            if let Some(owner) = self.entity(&op.owner)?
                && owner.path != entity.path
            {
                continue;
            }
            if !(op.start <= start && start < op.end)
                || string(&op.attrs, "execution")?.as_deref() == Some("unreachable")
            {
                continue;
            }
            let mut missing = BTreeSet::new();
            if string(&target.attrs, "modality")?.as_deref() == Some("may") {
                missing.insert("initializer_target_may".into());
            }
            let raw = self.children(&op)?;
            let mut children = raw
                .iter()
                .filter(|o| {
                    matches!(o.role.as_str(), "value" | "right")
                        && !o.native_kind.contains("comment")
                })
                .cloned()
                .collect::<Vec<_>>();
            if children.is_empty()
                && string(&entity.attrs, "language")?.as_deref() == Some("csharp")
                && op.native_kind == "variable_declarator"
            {
                children = raw
                    .iter()
                    .filter(|o| o.role != "name" && !o.native_kind.contains("comment"))
                    .cloned()
                    .collect();
            }
            if children.is_empty()
                && raw.len() == 1
                && matches!(
                    raw[0].native_kind.as_str(),
                    "var_spec" | "short_var_declaration" | "const_spec"
                )
            {
                children = self
                    .children(&raw[0])?
                    .into_iter()
                    .filter(|o| {
                        matches!(o.role.as_str(), "value" | "right")
                            && !o.native_kind.contains("comment")
                    })
                    .collect();
            }
            if children.len() != 1 {
                missing.insert("initializer_expression_missing".into());
                result.push(Initializer {
                    assignment: op.id.clone(),
                    expression: String::new(),
                    call: None,
                    unknown: missing,
                });
                continue;
            }
            let mut expression = children.pop().unwrap();
            let mut seen = BTreeSet::new();
            while matches!(
                expression.native_kind.as_str(),
                "parenthesized_expression" | "parenthesized_list" | "expression_list"
            ) {
                (self.tick)()?;
                if !seen.insert(expression.id.clone()) {
                    missing.insert("initializer_expression_cycle".into());
                    break;
                }
                let mut inner = self
                    .children(&expression)?
                    .into_iter()
                    .filter(|o| !o.native_kind.contains("comment"))
                    .collect::<Vec<_>>();
                if inner.len() != 1 {
                    break;
                }
                expression = inner.pop().unwrap();
            }
            let mut calls = BTreeSet::new();
            for f in self.rows("SYNTAX_NODE", None, Some(&expression.id))? {
                if self.entity(&f.subject)?.is_some_and(|e| e.kind == "CALL") {
                    calls.insert(f.subject.clone());
                }
            }
            let call = (calls.len() == 1).then(|| calls.first().unwrap().clone());
            if expression.kind == "CALL" && call.is_none() {
                missing.insert("initializer_call_link_missing".into());
            }
            result.push(Initializer {
                assignment: op.id.clone(),
                expression: expression.id.clone(),
                call,
                unknown: missing,
            });
        }
        if targets.is_empty() {
            for op in self.operations(&OperationProbe {
                kind: Some("ASSIGN".into()),
                ..Default::default()
            })? {
                if let Some(owner) = self.entity(&op.owner)?
                    && owner.path == entity.path
                    && op.start <= start
                    && start < op.end
                {
                    result.push(Initializer {
                        assignment: op.id.clone(),
                        expression: String::new(),
                        call: None,
                        unknown: unknown("initializer_target_missing"),
                    });
                }
            }
        }
        Ok(result)
    }
}
