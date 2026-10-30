//! Occurrence-level value uses; never propagate through historical storage flow.
use super::{
    OperationProbe, Result,
    source::{SourceRuntime, attr, string},
    source_occurrences::integer,
};
use ken_program::{Fact, Operation, value::GraphValue as V};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
pub(super) struct Usage {
    pub id: String,
    pub attrs: BTreeMap<String, V>,
    pub uncertain: bool,
    pub fact: Arc<Fact>,
}
type Consumer = (String, String, Option<i64>);
type Witness = (BTreeMap<String, V>, bool, Arc<Fact>);
impl SourceRuntime<'_> {
    fn source_operation(&mut self, id: &str) -> Result<Option<Arc<Operation>>> {
        if let Some(op) = self.operation(id)? {
            return Ok(Some(op));
        }
        let Some(e) = self.entity(id)? else {
            return Ok(None);
        };
        let (Some(start), Some(end)) = (
            integer(attr(&e.attrs, "start_byte")?),
            integer(attr(&e.attrs, "end_byte")?),
        ) else {
            return Ok(None);
        };
        let owner = string(&e.attrs, "owner")?;
        let mut candidates = vec![];
        for op in self.operations(&OperationProbe {
            owner,
            ..Default::default()
        })? {
            if op.start == start
                && op.end == end
                && self
                    .entity(&op.owner)?
                    .is_some_and(|owner| owner.path == e.path)
            {
                candidates.push(op);
            }
        }
        let native = string(&e.attrs, "native_kind")?;
        let exact = candidates
            .iter()
            .filter(|op| Some(op.native_kind.as_str()) == native.as_deref())
            .collect::<Vec<_>>();
        Ok(if exact.len() == 1 {
            Some(exact[0].clone())
        } else if candidates.len() == 1 {
            candidates.pop()
        } else {
            None
        })
    }
    fn call_at(&mut self, id: &str) -> Result<Option<String>> {
        let mut result = None;
        for f in self.rows("SYNTAX_NODE", None, Some(id))? {
            if self.entity(&f.subject)?.is_some_and(|e| e.kind == "CALL") {
                result = Some(f.subject.clone());
            }
        }
        Ok(result)
    }
    fn consumer(&mut self, op: &Operation) -> Result<Option<Consumer>> {
        let mut current = Arc::new(op.clone());
        let mut seen = BTreeSet::new();
        while let Some(parent) = current
            .parent
            .as_ref()
            .map(|id| self.operation(id))
            .transpose()?
            .flatten()
        {
            (self.tick)()?;
            if !seen.insert(current.id.clone()) {
                break;
            }
            if current.role == "object" && parent.kind == "MEMBER" && parent.role == "function" {
                return Ok(if let Some(id) = &parent.parent {
                    self.call_at(id)?
                        .map(|call| ("receiver".into(), call, None))
                } else {
                    None
                });
            }
            if matches!(parent.native_kind.as_str(), "argument_list" | "arguments") {
                let mut args = self
                    .children(&parent)?
                    .into_iter()
                    .filter(|o| !o.native_kind.contains("comment"))
                    .collect::<Vec<_>>();
                args.sort_by_key(|o| o.start);
                let call = parent
                    .parent
                    .as_ref()
                    .map(|id| self.call_at(id))
                    .transpose()?
                    .flatten();
                return Ok(call.and_then(|call| {
                    args.iter()
                        .position(|o| o.id == current.id)
                        .map(|p| ("argument".into(), call, Some(p as i64)))
                }));
            }
            for operand in self.rows("OPERAND", Some(&parent.id), Some(&current.id))? {
                if matches!(parent.kind.as_str(), "BINARY" | "UNARY") {
                    return Ok(Some((
                        "operand".into(),
                        parent.id.clone(),
                        integer(attr(&operand.attrs, "position")?),
                    )));
                }
            }
            if matches!(parent.kind.as_str(), "BRANCH" | "LOOP") {
                return Ok(
                    if self
                        .rows("CONTROL_CONDITION", Some(&parent.id), Some(&current.id))?
                        .is_empty()
                    {
                        None
                    } else {
                        Some(("condition".into(), parent.id.clone(), None))
                    },
                );
            }
            if parent.kind == "RETURN" {
                return Ok(Some(("return".into(), parent.id.clone(), None)));
            }
            if parent.kind == "ASSIGN" && matches!(current.role.as_str(), "value" | "right") {
                return Ok(Some(("assignment".into(), parent.id.clone(), None)));
            }
            if !matches!(
                parent.native_kind.as_str(),
                "parenthesized_expression" | "condition_clause" | "argument" | "expression_list"
            ) {
                return Ok(None);
            }
            current = parent;
        }
        Ok(None)
    }
    fn unreachable(&mut self, op: &Operation) -> Result<bool> {
        let mut current = Some(Arc::new(op.clone()));
        let mut seen = BTreeSet::new();
        while let Some(op) = current {
            (self.tick)()?;
            if !seen.insert(op.id.clone()) {
                break;
            }
            if string(&op.attrs, "execution")?.as_deref() == Some("unreachable") {
                return Ok(true);
            }
            let parent = op
                .parent
                .as_ref()
                .map(|id| self.operation(id))
                .transpose()?
                .flatten();
            if let Some(parent) = &parent
                && parent.kind == "BRANCH"
                && matches!(op.role.as_str(), "consequence" | "alternative")
            {
                let conditions = self.rows("CONTROL_CONDITION", Some(&parent.id), None)?;
                if conditions.len() == 1 {
                    let mut condition = self.operation(&conditions[0].object)?;
                    let mut unwrapped = BTreeSet::new();
                    while let Some(c) = &condition {
                        if !matches!(
                            c.native_kind.as_str(),
                            "parenthesized_expression" | "condition_clause"
                        ) || !unwrapped.insert(c.id.clone())
                        {
                            break;
                        }
                        let mut children = self
                            .children(c)?
                            .into_iter()
                            .filter(|c| !c.native_kind.contains("comment"))
                            .collect::<Vec<_>>();
                        condition = if children.len() == 1 {
                            children.pop()
                        } else {
                            None
                        };
                    }
                    if let Some(c) = condition
                        && matches!(c.native_kind.as_str(), "true" | "false" | "boolean_literal")
                    {
                        let literal = string(&c.attrs, "text")?;
                        let truth = match literal.as_deref() {
                            Some("true" | "True") => Some(true),
                            Some("false" | "False") => Some(false),
                            _ => None,
                        };
                        if truth.is_some_and(|truth| truth != (op.role == "consequence")) {
                            return Ok(true);
                        }
                    }
                }
            }
            current = parent;
        }
        Ok(false)
    }
    pub(super) fn usages(&mut self, value: &str) -> Result<Vec<Usage>> {
        let mut origins = BTreeSet::from([value.to_owned()]);
        origins.extend(
            self.rows("RESULT", None, Some(value))?
                .iter()
                .map(|f| f.subject.clone()),
        );
        let mut collected: BTreeMap<Consumer, Witness> = BTreeMap::new();
        for origin in origins {
            let mut witnesses = vec![];
            for (rel, kind) in [
                ("ARGUMENT_VALUE_ORIGIN", "argument"),
                ("RETURN_ORIGIN", "return"),
                ("ASSIGNMENT_ORIGIN", "assignment"),
                ("READ_ORIGIN", "condition"),
                ("VALUE_DEPENDS_ON", "operand"),
            ] {
                for f in self.rows(rel, None, Some(&origin))? {
                    witnesses.push((kind.to_owned(), f));
                }
            }
            if self.entity(&origin)?.is_some_and(|e| e.kind == "CALL") {
                for f in self.rows("SYNTAX_NODE", Some(&origin), None)? {
                    if let Some(op) = self.operation(&f.object)?
                        && let Some((kind, subject, position)) = self.consumer(&op)?
                    {
                        let entity = self.entity(&origin)?.unwrap();
                        let attrs = BTreeMap::from([
                            (
                                "modality".into(),
                                serde_json::value::RawValue::from_string("\"must\"".into())
                                    .unwrap(),
                            ),
                            (
                                "position".into(),
                                serde_json::value::RawValue::from_string(
                                    json!(position).to_string(),
                                )
                                .unwrap(),
                            ),
                        ]);
                        witnesses.push((
                            kind,
                            Arc::new(Fact {
                                subject,
                                relation: "DIRECT_VALUE_USE".into(),
                                object: origin.clone(),
                                attrs,
                                evidence: vec![format!("{}:{}", entity.path, op.line)],
                            }),
                        ));
                    }
                }
            }
            for (mut kind, fact) in witnesses {
                (self.tick)()?;
                let mut consumer = fact.subject.clone();
                let mut position = integer(attr(&fact.attrs, "position")?);
                let mut op = self.source_operation(&consumer)?;
                if fact.relation == "READ_ORIGIN" {
                    let classified = if let Some(op) = &op {
                        self.consumer(op)?
                    } else {
                        None
                    };
                    let Some(classified) = classified else {
                        continue;
                    };
                    (kind, consumer, position) = classified;
                    op = self.source_operation(&consumer)?;
                }
                if kind == "operand"
                    && let Some(op) = &op
                {
                    consumer = op.id.clone();
                }
                let entity = self.entity(&consumer)?;
                if op.is_none() && entity.is_none() {
                    continue;
                }
                let owner = if let Some(op) = &op {
                    Some(op.owner.clone())
                } else if let Some(e) = &entity {
                    string(&e.attrs, "owner")?
                } else {
                    None
                };
                let owner_entity = owner
                    .as_ref()
                    .map(|id| self.entity(id))
                    .transpose()?
                    .flatten();
                if let Some(op) = &op
                    && self.unreachable(op)?
                {
                    continue;
                }
                if let Some(e) = &entity
                    && string(&e.attrs, "execution")?.as_deref() == Some("unreachable")
                {
                    continue;
                }
                if matches!(kind.as_str(), "argument" | "operand") && position.is_none() {
                    continue;
                }
                let path = entity
                    .as_ref()
                    .map(|e| e.path.clone())
                    .or_else(|| owner_entity.as_ref().map(|e| e.path.clone()));
                let line = op
                    .as_ref()
                    .map(|o| o.line)
                    .or_else(|| entity.as_ref().map(|e| e.line));
                let mut attrs = BTreeMap::from([
                    ("kind".into(), V::String(kind.as_str().into())),
                    ("consumer".into(), V::String(consumer.as_str().into())),
                    (
                        "owner".into(),
                        owner.map_or(V::Null, |v| V::String(v.into())),
                    ),
                    ("path".into(), path.map_or(V::Null, |v| V::String(v.into()))),
                    (
                        "line".into(),
                        line.map_or(V::Null, |v| V::Int(v.to_string())),
                    ),
                    (
                        "position".into(),
                        position.map_or(V::Null, |v| V::Int(v.to_string())),
                    ),
                ]);
                if let Some(e) = &entity
                    && e.kind == "CALL"
                {
                    attrs.insert(
                        "consumer_name".into(),
                        if e.attrs.contains_key("name") {
                            attr(&e.attrs, "name")?
                        } else {
                            V::String(e.name.as_str().into())
                        },
                    );
                }
                let mut uncertain = string(&fact.attrs, "modality")?.as_deref() != Some("must");
                if kind == "argument" {
                    for a in self.rows("ARGUMENT", Some(&consumer), None)? {
                        for metadata in self.rows("ENTITY", Some(&a.object), Some("ARGUMENT"))? {
                            if string(&metadata.attrs, "kind")?
                                .is_some_and(|v| v.starts_with("spread"))
                                && integer(attr(&metadata.attrs, "position")?)
                                    .zip(position)
                                    .is_some_and(|(a, b)| a <= b)
                            {
                                uncertain = true;
                            }
                        }
                    }
                }
                let key = (kind, consumer, position);
                if collected
                    .get(&key)
                    .is_none_or(|(_, old, _)| *old && !uncertain)
                {
                    collected.insert(key, (attrs, uncertain, fact));
                }
            }
        }
        let mut uses = vec![];
        for ((kind, consumer, position), (attrs, uncertain, fact)) in collected {
            let key = format!(
                "[{},{},{}]",
                crate::relational::json_string(&kind),
                crate::relational::json_string(&consumer),
                position.map_or("null".into(), |p| p.to_string())
            );
            let id = format!("usage:{:x}", Sha256::digest(key.as_bytes()));
            uses.push(Usage {
                id,
                attrs,
                uncertain,
                fact,
            });
        }
        Ok(uses)
    }
}
