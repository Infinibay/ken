//! Callable-local receiver effects, including conservative constructor delegation.
use super::{
    Result,
    source::{Knowledge, SourceRuntime, Truth, attr, string},
};
use std::collections::BTreeSet;
impl SourceRuntime<'_> {
    pub(super) fn receiver_escape(
        &mut self,
        owner: &str,
        receiver: &str,
        depth: usize,
        active: &mut BTreeSet<(String, String)>,
    ) -> Result<Truth> {
        crate::with_stack(|| {
            (self.tick)()?;
            let key = (owner.into(), receiver.into());
            if depth >= 64 || !active.insert(key.clone()) {
                return Ok(Knowledge::Unknown("receiver_recursion"));
            }
            let result = self.receiver_contents(owner, receiver, depth, active);
            active.remove(&key);
            result
        })
    }
    fn receiver_contents(
        &mut self,
        owner: &str,
        receiver: &str,
        depth: usize,
        active: &mut BTreeSet<(String, String)>,
    ) -> Result<Truth> {
        let statuses = self.rows("CFG_STATUS", Some(owner), None)?;
        if statuses.is_empty() || statuses.iter().any(|f| f.object != "structured") {
            return Ok(Knowledge::Unknown("receiver_cfg"));
        }
        let ops = self.operations(&super::OperationProbe {
            owner: Some(owner.into()),
            ..Default::default()
        })?;
        let mut names = BTreeSet::from(["this".to_owned(), "self".to_owned()]);
        if let Some(e) = self.entity(receiver)?
            && !e.name.is_empty()
        {
            names.insert(e.name.clone());
        }
        let mut uncertain = false;
        if let Some(e) = self.entity(owner)?
            && attr(&e.attrs, "instance_constructor")?.truthy()
        {
            for containing in self.rows("IN_TYPE", Some(owner), None)? {
                let mut targets = vec![];
                for f in self.rows("SUBTYPE_OF", Some(&containing.object), None)? {
                    if let Some(e) = self.entity(&f.object)? {
                        targets.push(e);
                    }
                }
                for base in self.rows("BASE_NAME", Some(&containing.object), None)? {
                    let mut resolved = vec![];
                    for target in &targets {
                        if target.name == base.object
                            || string(&target.attrs, "qualified_name")?.as_deref()
                                == Some(base.object.as_str())
                        {
                            resolved.push(target);
                        }
                    }
                    if resolved.len() != 1 || resolved[0].kind != "INTERFACE" {
                        uncertain = true;
                    }
                }
            }
        }
        for op in &ops {
            (self.tick)()?;
            if op.native_kind == "explicit_constructor_invocation" {
                let mut tokens = vec![];
                for child in &ops {
                    if child.parent.as_deref() == Some(&op.id) && child.role == "constructor" {
                        tokens.push(string(&child.attrs, "text")?);
                    }
                }
                if tokens != vec![Some("this".into())] {
                    uncertain = true;
                }
            }
            for rel in ["ASSIGNMENT_VALUE", "RETURN_OPERAND"] {
                if !self.rows(rel, Some(&op.id), Some(receiver))?.is_empty() {
                    uncertain = true;
                }
            }
            if op.kind != "CALL" {
                continue;
            }
            for link in self.rows("SYNTAX_NODE", None, Some(&op.id))? {
                if let Some(e) = self.entity(&link.subject)?
                    && matches!(
                        e.name.as_str(),
                        "eval" | "exec" | "execfile" | "compile" | "Function"
                    )
                {
                    uncertain = true;
                }
                for argument in self.rows("ARGUMENT", Some(&link.subject), None)? {
                    if !self
                        .rows("VALUE", Some(&argument.object), Some(receiver))?
                        .is_empty()
                    {
                        return Ok(Knowledge::Known(true));
                    }
                }
                if !self
                    .rows("RECEIVER", Some(&link.subject), Some(receiver))?
                    .is_empty()
                {
                    uncertain = true;
                }
            }
        }
        for op in &ops {
            (self.tick)()?;
            if string(&op.attrs, "text")?.is_none_or(|v| !names.contains(&v)) {
                continue;
            }
            let parent = op
                .parent
                .as_ref()
                .map(|id| self.operation(id))
                .transpose()?
                .flatten();
            if let Some(p) = &parent
                && (p.kind == "MEMBER"
                    && matches!(
                        op.role.as_str(),
                        "object" | "argument" | "operand" | "value"
                    )
                    || matches!(p.native_kind.as_str(), "parameters" | "parameter_list"))
            {
                continue;
            }
            if matches!(op.role.as_str(), "name" | "parameter") {
                continue;
            }
            if let Some(parent) = parent
                && parent.native_kind == "explicit_constructor_invocation"
            {
                let links = self.rows("SYNTAX_NODE", None, Some(&parent.id))?;
                let mut delegated = BTreeSet::new();
                for link in &links {
                    for rel in ["TARGET", "CONSTRUCTOR_TARGET"] {
                        delegated.extend(
                            self.rows(rel, Some(&link.subject), None)?
                                .iter()
                                .map(|f| f.object.clone()),
                        );
                    }
                }
                if delegated.is_empty()
                    && string(&op.attrs, "text")?.as_deref() == Some("this")
                    && links.len() == 1
                    && self
                        .rows("ARGUMENT", Some(&links[0].subject), None)?
                        .is_empty()
                {
                    for containing in self.rows("IN_TYPE", Some(owner), None)? {
                        for member in self.rows("HAS_METHOD", Some(&containing.object), None)? {
                            if let Some(target) = self.entity(&member.object)?
                                && attr(&target.attrs, "instance_constructor")?.truthy()
                                && string(&target.attrs, "language")?.as_deref() == Some("java")
                            {
                                let mut parameters = 0;
                                for p in self.rows("HAS_PARAMETER", Some(&target.id), None)? {
                                    if !attr(&p.attrs, "receiver")?.truthy() {
                                        parameters += 1;
                                    }
                                }
                                if parameters == 0 {
                                    delegated.insert(target.id.clone());
                                }
                            }
                        }
                    }
                }
                if delegated.len() == 1
                    && self.receiver_escape(
                        delegated.first().unwrap(),
                        receiver,
                        depth + 1,
                        active,
                    )? == Knowledge::Known(false)
                {
                    continue;
                }
            }
            uncertain = true;
        }
        for nested in self.rows("OWNED_BY", None, Some(owner))? {
            if self
                .entity(&nested.subject)?
                .is_some_and(|e| e.kind == "CALLABLE")
            {
                uncertain = true;
            }
        }
        Ok(if uncertain {
            Knowledge::Unknown("receiver_effects")
        } else {
            Knowledge::Known(false)
        })
    }
}
