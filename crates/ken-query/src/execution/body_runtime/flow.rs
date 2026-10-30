use super::*;
use context::{attr, number, strings, text};
use ken_program::Operation;
pub(super) type Snapshot = BTreeMap<String, Option<String>>;
#[derive(Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Flow {
    pub finalizers: Vec<Finalizer>,
    pub groups: Vec<Group>,
    pub returned: Option<(String, Option<Snapshot>)>,
    pub closing: bool,
    pub exception: String,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Finalizer {
    scope: String,
    target: String,
    exception: String,
    returned: Option<(String, Option<Snapshot>)>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub(super) struct Group {
    scope: String,
    exception: String,
    matched: bool,
    raised: bool,
    processed: Vec<String>,
}
// Builtin exception names in accredited CFG headers. Unknown names never gain a
// subtype claim; custom/shadowed handlers are already uncertain in CFG metadata.
fn subtype(child: &str, parent: &str) -> bool {
    if child == parent {
        return true;
    }
    if parent == "BaseException" {
        return true;
    }
    if parent == "Exception" {
        return !matches!(
            child,
            "GeneratorExit" | "KeyboardInterrupt" | "SystemExit" | "BaseExceptionGroup"
        );
    }
    let direct = match child {
        "ExceptionGroup" => "BaseExceptionGroup",
        "OverflowError" | "ZeroDivisionError" | "FloatingPointError" => "ArithmeticError",
        "ModuleNotFoundError" => "ImportError",
        "IndexError" | "KeyError" => "LookupError",
        "UnboundLocalError" => "NameError",
        "BrokenPipeError"
        | "ConnectionAbortedError"
        | "ConnectionRefusedError"
        | "ConnectionResetError" => "ConnectionError",
        "ConnectionError" | "BlockingIOError" | "ChildProcessError" | "FileExistsError"
        | "FileNotFoundError" | "InterruptedError" | "IsADirectoryError" | "NotADirectoryError"
        | "PermissionError" | "ProcessLookupError" | "TimeoutError" => "OSError",
        "NotImplementedError" | "RecursionError" => "RuntimeError",
        "IndentationError" => "SyntaxError",
        "TabError" => "IndentationError",
        "UnicodeError" => "ValueError",
        "UnicodeDecodeError" | "UnicodeEncodeError" | "UnicodeTranslateError" => "UnicodeError",
        "DeprecationWarning"
        | "PendingDeprecationWarning"
        | "RuntimeWarning"
        | "SyntaxWarning"
        | "UserWarning"
        | "FutureWarning"
        | "ImportWarning"
        | "UnicodeWarning"
        | "BytesWarning"
        | "ResourceWarning"
        | "EncodingWarning" => "Warning",
        _ => "",
    };
    !direct.is_empty() && subtype(direct, parent)
}
fn consumes(earlier: &[String], later: &[String]) -> bool {
    !later.is_empty() && later.iter().all(|c| earlier.iter().any(|p| subtype(c, p)))
}
impl Flow {
    pub fn permits(
        &self,
        event: &ken_program::Attributes,
        target: &str,
        kind: &str,
    ) -> Result<bool> {
        let action = text(event, "action")?;
        let scope = text(event, "scope")?;
        let close = text(event, "close")?;
        if self.exception == "GeneratorExit"
            && (attr(event, "close_blocked")?.truthy()
                || (action == "propagate" && close == "no")
                || (close == "no" && kind == "handler"))
        {
            return Ok(false);
        }
        if action == "finally-leave" {
            return Ok(self
                .finalizers
                .last()
                .is_some_and(|f| f.scope == scope && f.target == target));
        }
        if action == "star-exit" {
            let Some(group) = self.groups.last().filter(|g| g.scope == scope) else {
                return Ok(false);
            };
            if target == text(event, "normal")? {
                return Ok(group.matched && !group.raised);
            }
            return Ok(group.raised
                || !consumes(
                    &group.processed,
                    &[if group.exception.is_empty() {
                        "BaseException".into()
                    } else {
                        group.exception.clone()
                    }],
                ));
        }
        if action == "star-match"
            && let Some(group) = self.groups.last()
        {
            let exception = if group.exception.is_empty() {
                "BaseException".into()
            } else {
                group.exception.clone()
            };
            if consumes(&group.processed, std::slice::from_ref(&exception)) {
                return Ok(false);
            }
            let types = strings(event, "types")?;
            if !group.exception.is_empty() && !types.is_empty() && !consumes(&types, &[exception]) {
                return Ok(false);
            }
            return Ok(!consumes(&group.processed, &types));
        }
        Ok(true)
    }
    pub fn advance(
        &self,
        event: &ken_program::Attributes,
        snapshot: Option<Snapshot>,
        target: &str,
    ) -> Result<Self> {
        let mut f = self.clone();
        let action = text(event, "action")?;
        let scope = text(event, "scope")?;
        match action.as_str() {
            "unwind" => {
                let abandoned = strings(event, "scopes")?;
                let prior = f.finalizers.len();
                f.finalizers.retain(|e| !abandoned.contains(&e.scope));
                if prior != f.finalizers.len() {
                    f.returned = f.finalizers.last().and_then(|e| e.returned.clone());
                }
            }
            "return-eval" => {
                f.returned = Some((text(event, "operation")?, snapshot));
                f.exception.clear();
            }
            "finally-enter" => f.finalizers.push(Finalizer {
                scope,
                target: text(event, "target")?,
                exception: f.exception.clone(),
                returned: f.returned.clone(),
            }),
            "finally-leave" => {
                let last = f
                    .finalizers
                    .pop()
                    .ok_or_else(|| invalid("missing finalizer continuation"))?;
                f.exception = last.exception;
                f.returned = last.returned;
            }
            "star-enter" => f.groups.push(Group {
                scope,
                exception: f.exception.clone(),
                ..Default::default()
            }),
            "star-header" if target != text(event, "match")? => {
                if let Some(group) = f.groups.last_mut() {
                    group.processed.extend(strings(event, "types")?);
                }
            }
            "star-match" | "star-raise" => {
                if let Some(group) = f.groups.last_mut() {
                    group.matched |= action == "star-match";
                    group.raised |= action == "star-raise";
                    group.processed.extend(strings(event, "types")?);
                    f.exception.clear();
                }
            }
            "star-exit" => {
                let group = f
                    .groups
                    .pop()
                    .ok_or_else(|| invalid("missing exception-group continuation"))?;
                f.exception = if target == text(event, "normal")? || group.raised {
                    String::new()
                } else {
                    group.exception
                };
            }
            "handler" => f.exception.clear(),
            _ => (),
        }
        Ok(f)
    }
}
impl context::Context<'_> {
    pub fn path_successors(
        &mut self,
        group: &str,
        snapshot: Option<&Snapshot>,
        flow: &Flow,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<String>> {
        let mut following = self.successors(group, s)?;
        let event = self.events.get(group).cloned().unwrap_or_default();
        if !self.events.is_empty() {
            let edges = self.rows("CFG_NEXT", Some(group), None, s)?;
            let mut allowed = vec![];
            for f in edges {
                let kind = text(&f.attrs, "kind")?;
                if following.contains(&f.object)
                    && !matches!(kind.as_str(), "inject-throw" | "inject-close")
                    && flow.permits(&event, &f.object, &kind)?
                {
                    allowed.push(f.object.clone());
                }
            }
            following = allowed;
        }
        if self.path_enabled {
            let source = text(&event, "operation")?;
            if !source.is_empty() && self.cannot_raise(&source, snapshot, 0, s)? {
                let exceptional = self
                    .rows("CFG_NEXT", Some(group), None, s)?
                    .iter()
                    .filter(|f| text(&f.attrs, "kind").ok().as_deref() == Some("exception"))
                    .map(|f| f.object.clone())
                    .collect::<BTreeSet<_>>();
                following.retain(|p| !exceptional.contains(p));
            }
        }
        Ok(following)
    }
    pub fn advanced(
        &mut self,
        group: &str,
        snapshot: Option<&Snapshot>,
        flow: &Flow,
        successor: &str,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<(Option<Snapshot>, Flow)>> {
        let event = self.events.get(group).cloned().unwrap_or_default();
        let mut next = flow.advance(&event, snapshot.cloned(), successor)?;
        if !self.events.is_empty()
            && self
                .rows("CFG_NEXT", Some(group), Some(successor), s)?
                .iter()
                .any(|f| {
                    text(&f.attrs, "kind")
                        .is_ok_and(|k| matches!(k.as_str(), "exception" | "raise"))
                })
        {
            next.exception.clear();
        }
        let values = if self.path_enabled {
            self.advance_values(group, snapshot, Some(successor), s)?
        } else {
            vec![None]
        };
        Ok(values.into_iter().map(|v| (v, next.clone())).collect())
    }
    fn resolve_value(
        &mut self,
        value: &str,
        snapshot: &Snapshot,
        s: &mut dyn BodyServices,
    ) -> Result<Option<String>> {
        if self
            .locals
            .iter()
            .any(|n| n.local_id == value && matches!(n.kind.as_str(), "STORAGE" | "PARAMETER"))
        {
            return Ok(snapshot.get(value).cloned().flatten());
        }
        if self
            .entities
            .get(value)
            .is_some_and(|e| matches!(e.kind.as_str(), "STORAGE" | "PARAMETER" | "MEMBER"))
            || !self.rows("LOADED_FROM", Some(value), None, s)?.is_empty()
        {
            return Ok(None);
        }
        Ok(Some(value.into()))
    }
    pub fn operand_origin(
        &mut self,
        op: &Operation,
        snapshot: &Snapshot,
        s: &mut dyn BodyServices,
    ) -> Result<Option<String>> {
        let mut operands = self.rows("RETURN_OPERAND", Some(&op.id), None, s)?;
        if operands.is_empty() {
            operands = self.rows("BINDING_REFERENCE", Some(&op.id), None, s)?;
        }
        if operands.len() == 1 {
            return self.resolve_value(&operands[0].object, snapshot, s);
        }
        if matches!(
            op.native_kind.as_str(),
            "none" | "true" | "false" | "integer" | "float" | "string" | "concatenated_string"
        ) {
            return Ok(Some(op.id.clone()));
        }
        Ok(self.call(op).map(|e| e.id.clone()))
    }
    pub fn origins(
        &mut self,
        op: &Operation,
        snapshot: &Snapshot,
        depth: usize,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<Option<String>>> {
        s.check()?;
        if depth > 16 {
            return Ok(vec![None]);
        }
        let operands = self.rows("RETURN_OPERAND", Some(&op.id), None, s)?;
        if let Some(first) = operands.first() {
            return self.value_origins(&first.object, snapshot, depth + 1, s);
        }
        if op.native_kind != "conditional_expression" {
            return Ok(vec![self.operand_origin(op, snapshot, s)?]);
        }
        let mut children = self.children.get(&op.id).cloned().unwrap_or_default();
        children.retain(|c| !c.native_kind.contains("comment"));
        children.sort_by_key(|o| o.start);
        let admitted = [
            "identifier",
            "none",
            "true",
            "false",
            "integer",
            "float",
            "string",
            "conditional_expression",
        ];
        if children.len() != 3
            || !admitted.contains(&children[0].native_kind.as_str())
            || !admitted.contains(&children[2].native_kind.as_str())
        {
            return Ok(vec![None]);
        }
        let arms = match self.literal_boolean(&children[1]) {
            Some(true) => vec![children[0].clone()],
            Some(false) => vec![children[2].clone()],
            None => vec![children[0].clone(), children[2].clone()],
        };
        let mut result = vec![];
        for arm in arms {
            for origin in self.origins(&arm, snapshot, depth + 1, s)? {
                if !result.contains(&origin) {
                    result.push(origin);
                }
            }
        }
        Ok(result)
    }
    fn value_origins(
        &mut self,
        value: &str,
        snapshot: &Snapshot,
        depth: usize,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<Option<String>>> {
        if depth > 16 {
            return Ok(vec![None]);
        }
        if let Some(entity) = self.entities.get(value).cloned() {
            match text(&entity.attrs, "native_kind")?.as_str() {
                "conditional_expression" => {
                    let span = (
                        number(&entity.attrs, "start_byte")?.unwrap_or(-1),
                        number(&entity.attrs, "end_byte")?.unwrap_or(-1),
                    );
                    return if let Some(op) = self.spans.get(&span).cloned() {
                        self.origins(&op, snapshot, depth + 1, s)
                    } else {
                        Ok(vec![None])
                    };
                }
                "boolean_operator" => return Ok(vec![None]),
                _ => (),
            }
        }
        Ok(vec![self.resolve_value(value, snapshot, s)?])
    }
    pub fn cannot_raise(
        &mut self,
        id: &str,
        snapshot: Option<&Snapshot>,
        depth: usize,
        s: &mut dyn BodyServices,
    ) -> Result<bool> {
        s.check()?;
        let (Some(op), Some(snapshot)) = (self.operations.get(id).cloned(), snapshot) else {
            return Ok(false);
        };
        if depth > 32 {
            return Ok(false);
        }
        if matches!(
            op.native_kind.as_str(),
            "none" | "true" | "false" | "integer" | "float"
        ) {
            return Ok(true);
        }
        if op.native_kind == "identifier" {
            return Ok(self.operand_origin(&op, snapshot, s)?.is_some());
        }
        let children: Vec<_> = self
            .children
            .get(id)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter(|o| !o.native_kind.contains("comment"))
            .collect();
        if op.native_kind == "conditional_expression" && children.len() == 3 {
            if let Some(literal) = self.literal_boolean(&children[1]) {
                return self.cannot_raise(
                    &children[if literal { 0 } else { 2 }].id,
                    Some(snapshot),
                    depth + 1,
                    s,
                );
            }
            return Ok(false);
        }
        if op.native_kind == "assignment" {
            let left = children.iter().find(|o| o.role == "left");
            let right = children.iter().find(|o| o.role == "right");
            return if left.is_some_and(|l| l.native_kind == "identifier") {
                if let Some(right) = right {
                    self.cannot_raise(&right.id, Some(snapshot), depth + 1, s)
                } else {
                    Ok(false)
                }
            } else {
                Ok(false)
            };
        }
        if matches!(
            op.native_kind.as_str(),
            "expression_statement" | "parenthesized_expression" | "return_statement"
        ) || (op.kind == "YIELD" && !attr(&op.attrs, "delegated")?.truthy())
        {
            for child in children {
                if !self.cannot_raise(&child.id, Some(snapshot), depth + 1, s)? {
                    return Ok(false);
                }
            }
            return Ok(true);
        }
        Ok(false)
    }
    fn advance_values(
        &mut self,
        group: &str,
        snapshot: Option<&Snapshot>,
        successor: Option<&str>,
        s: &mut dyn BodyServices,
    ) -> Result<Vec<Option<Snapshot>>> {
        let Some(snapshot) = snapshot else {
            return Ok(vec![None]);
        };
        let mut environment = snapshot.clone();
        let parts = self.parts(group, s)?;
        let mut writes = vec![];
        for op in &parts {
            if !self
                .rows("ASSIGNMENT_TARGET", Some(&op.id), None, s)?
                .is_empty()
            {
                writes.push(op.clone());
            }
        }
        writes.sort_by_key(|o| (o.end, -o.start));
        let mut choices = vec![None];
        let mut choice_target = None;
        for op in &writes {
            let targets = self.rows("ASSIGNMENT_TARGET", Some(&op.id), None, s)?;
            let values = self.rows("ASSIGNMENT_VALUE", Some(&op.id), None, s)?;
            let known = writes.len() == 1
                && targets.len() == 1
                && values.len() == 1
                && op.native_kind == "assignment";
            choices = if known {
                self.value_origins(&values[0].object, snapshot, 0, s)?
            } else {
                vec![None]
            };
            for target in targets {
                if self.locals.iter().any(|n| {
                    n.local_id == target.object
                        && matches!(n.kind.as_str(), "STORAGE" | "PARAMETER")
                }) {
                    environment.insert(target.object.clone(), None);
                    if known {
                        choice_target = Some(target.object.clone());
                    }
                }
            }
        }
        let iterate = if let Some(successor) = successor {
            self.rows("CFG_NEXT", Some(group), Some(successor), s)?
                .iter()
                .any(|f| text(&f.attrs, "kind").ok().as_deref() == Some("iterate"))
        } else {
            true
        };
        for op in parts {
            if iterate {
                for f in self.rows("ITERATION_BINDING", Some(&op.id), None, s)? {
                    environment.insert(f.object.clone(), None);
                }
            }
            for f in self.rows("PATH_INVALIDATES", Some(&op.id), None, s)? {
                environment.insert(f.object.clone(), None);
            }
        }
        if let Some(target) = choice_target {
            Ok(choices
                .into_iter()
                .map(|origin| {
                    let mut result = environment.clone();
                    result.insert(target.clone(), origin);
                    Some(result)
                })
                .collect())
        } else {
            Ok(vec![Some(environment)])
        }
    }
    pub fn path_matches(
        &mut self,
        produced: &SourceNode,
        operand: &Operation,
        snapshot: &Snapshot,
        s: &mut dyn BodyServices,
    ) -> Result<Value> {
        let mut result = context::truth(false);
        for origin in self.origins(operand, snapshot, 0, s)? {
            result = result.or(if let Some(origin) = origin {
                self.captured_reaches(&produced.local_id, &BTreeSet::from([origin]), s)?
            } else {
                context::unknown("path_origin_unknown")
            });
        }
        Ok(result)
    }
}
