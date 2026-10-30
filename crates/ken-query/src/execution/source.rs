//! Source semantics interprets immutable facts; missing knowledge stays explicit.
//! This service is shared by source selectors and subsequent BODY/indexed work.
use super::{ExecutionError, FactProbe, GraphRead, Result};
use crate::ast::Expr;
use ken_program::{Entity, Fact, TypeRef, value::GraphValue as V};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Knowledge<T> {
    Known(T),
    Unknown(&'static str),
}
pub type Truth = Knowledge<bool>;
impl Truth {
    pub fn and(self, other: Self) -> Self {
        match (self, other) {
            (Self::Known(false), _) | (_, Self::Known(false)) => Self::Known(false),
            (Self::Unknown(r), _) | (_, Self::Unknown(r)) => Self::Unknown(r),
            _ => Self::Known(true),
        }
    }
    pub fn or(self, other: Self) -> Self {
        match (self, other) {
            (Self::Known(true), _) | (_, Self::Known(true)) => Self::Known(true),
            (Self::Unknown(r), _) | (_, Self::Unknown(r)) => Self::Unknown(r),
            _ => Self::Known(false),
        }
    }
}
#[derive(Default)]
pub(super) struct SourceCache {
    descriptors: BTreeMap<String, Knowledge<Arc<TypeRef>>>,
    descriptor_bytes: usize,
    pub usage_metadata: BTreeMap<String, BTreeMap<String, V>>,
}
pub(super) struct SourceRuntime<'a> {
    pub graph: &'a dyn GraphRead,
    pub cache: &'a mut SourceCache,
    pub tick: &'a mut dyn FnMut() -> Result<()>,
}
pub(super) fn attr(attrs: &ken_program::Attributes, key: &str) -> Result<V> {
    Ok(attrs
        .get(key)
        .map(|v| V::parse(v))
        .transpose()?
        .unwrap_or(V::Null))
}
pub(super) fn string(attrs: &ken_program::Attributes, key: &str) -> Result<Option<String>> {
    Ok(attr(attrs, key)?.string())
}
impl SourceRuntime<'_> {
    pub fn operations(
        &mut self,
        probe: &super::OperationProbe,
    ) -> Result<Vec<Arc<ken_program::Operation>>> {
        (self.tick)()?;
        let mut ops = vec![];
        self.graph.operations_checked(probe, self.tick, &mut |op| {
            ops.push(op);
            Ok(())
        })?;
        Ok(ops)
    }
    pub fn operation(&mut self, id: &str) -> Result<Option<Arc<ken_program::Operation>>> {
        Ok(self
            .operations(&super::OperationProbe {
                id: Some(id.into()),
                ..Default::default()
            })?
            .into_iter()
            .next())
    }
    pub fn rows(
        &mut self,
        relation: &str,
        subject: Option<&str>,
        object: Option<&str>,
    ) -> Result<Vec<Arc<Fact>>> {
        (self.tick)()?;
        let probe = FactProbe {
            relation: relation.into(),
            subject: subject.map(str::to_owned),
            object: object.map(str::to_owned),
            attribute: None,
        };
        let mut rows = vec![];
        self.graph.facts(&probe, &mut |fact| {
            (self.tick)()?;
            if subject.is_none_or(|v| v == fact.subject) && object.is_none_or(|v| v == fact.object)
            {
                rows.push(fact);
            }
            Ok(())
        })?;
        Ok(rows)
    }
    pub fn entity(&mut self, id: &str) -> Result<Option<Arc<Entity>>> {
        (self.tick)()?;
        self.graph.entity(id)
    }
    pub fn type_of(&mut self, id: &str, returns: bool) -> Result<Knowledge<Arc<TypeRef>>> {
        let refs = self.rows(
            if returns {
                "RETURN_TYPE_REF"
            } else {
                "TYPE_REF"
            },
            Some(id),
            None,
        )?;
        if refs.is_empty() {
            return Ok(Knowledge::Unknown("type_information_missing"));
        }
        for f in &refs {
            if string(&f.attrs, "basis")?.as_deref() == Some("missing-annotation") {
                return Ok(Knowledge::Unknown("type_information_missing"));
            }
        }
        if refs
            .iter()
            .map(|f| &f.object)
            .collect::<BTreeSet<_>>()
            .len()
            != 1
        {
            return Ok(Knowledge::Unknown("ambiguous_type_descriptor"));
        }
        let mut descriptor = self.descriptor(&refs[0].object, 0)?;
        if !returns
            && let Knowledge::Known(value) = &descriptor
            && !self.rows("TYPE", Some(id), None)?.is_empty()
        {
            let mut nominal = (**value).clone();
            nominal.kind = "nominal".into();
            nominal.bits = None;
            nominal.signed = None;
            nominal.extent = None;
            nominal.rank = None;
            nominal.qualifiers.clear();
            descriptor = Knowledge::Known(Arc::new(nominal));
        }
        Ok(descriptor)
    }
    fn scalar(&mut self, relation: &str, key: &str) -> Result<Option<String>> {
        let rows = self.rows(relation, Some(key), None)?;
        Ok((rows.len() == 1).then(|| rows[0].object.clone()))
    }
    fn descriptor(&mut self, key: &str, depth: usize) -> Result<Knowledge<Arc<TypeRef>>> {
        crate::with_stack(|| {
            (self.tick)()?;
            if depth > 128 {
                return Ok(Knowledge::Unknown("type_descriptor_depth"));
            }
            if let Some(refs) = self.cache.descriptors.get(key) {
                return Ok(refs.clone());
            }
            // Bound memo retention; recursion membership is independent of this cache.
            let result = self.build_descriptor(key, depth, &mut BTreeSet::new(), &mut 0);
            if let Ok(value) = &result {
                let mut bytes = 128 + key.len();
                if let Knowledge::Known(value) = value {
                    let mut pending = vec![value.as_ref()];
                    while let Some(t) = pending.pop() {
                        (self.tick)()?;
                        bytes = bytes.saturating_add(
                            256 + t.kind.len()
                                + t.native.len()
                                + t.extent.as_ref().map_or(0, String::len)
                                + t.qualifiers.iter().map(|v| 32 + v.len()).sum::<usize>(),
                        );
                        pending.extend(&t.arguments);
                    }
                }
                if bytes <= 2_000_000 {
                    if self.cache.descriptor_bytes.saturating_add(bytes) > 2_000_000
                        || self.cache.descriptors.len() >= 1024
                    {
                        self.cache.descriptors.clear();
                        self.cache.descriptor_bytes = 0;
                    }
                    self.cache.descriptor_bytes += bytes;
                    self.cache.descriptors.insert(key.into(), value.clone());
                }
            }
            result
        })
    }
    fn build_descriptor(
        &mut self,
        key: &str,
        depth: usize,
        active: &mut BTreeSet<String>,
        work: &mut usize,
    ) -> Result<Knowledge<Arc<TypeRef>>> {
        crate::with_stack(|| {
            (self.tick)()?;
            *work += 1;
            if *work > 65536 {
                return Err(ExecutionError::Exhausted("source_types"));
            }
            if depth > 128 {
                return Ok(Knowledge::Unknown("type_descriptor_depth"));
            }
            if !active.insert(key.into()) {
                return Ok(Knowledge::Unknown("type_descriptor_cycle"));
            }
            let result = self.descriptor_contents(key, depth, active, work);
            active.remove(key);
            result
        })
    }
    fn descriptor_contents(
        &mut self,
        key: &str,
        depth: usize,
        active: &mut BTreeSet<String>,
        work: &mut usize,
    ) -> Result<Knowledge<Arc<TypeRef>>> {
        let (Some(kind), Some(native)) = (
            self.scalar("TYPE_KIND", key)?,
            self.scalar("TYPE_NATIVE", key)?,
        ) else {
            return Ok(Knowledge::Unknown("type_descriptor_missing"));
        };
        let children = self.rows("TYPE_ARGUMENT", Some(key), None)?;
        let mut children = children
            .into_iter()
            .map(|f| {
                let position = attr(&f.attrs, "position")?;
                let p = match position {
                    V::Null => 0,
                    V::Int(s) => s.parse::<i128>().map_err(|_| {
                        ExecutionError::Invalid("invalid descriptor argument position".into())
                    })?,
                    _ => {
                        return Err(ExecutionError::Invalid(
                            "invalid descriptor argument position".into(),
                        ));
                    }
                };
                Ok((p, f))
            })
            .collect::<Result<Vec<_>>>()?;
        children.sort_by_key(|(p, _)| *p);
        let mut arguments = vec![];
        for (_, f) in children {
            match self.build_descriptor(&f.object, depth + 1, active, work)? {
                Knowledge::Known(a) => arguments.push((*a).clone()),
                Knowledge::Unknown(_) => return Ok(Knowledge::Unknown("type_argument_missing")),
            }
        }
        let bits = self
            .scalar("TYPE_BITS", key)?
            .map(|v| v.parse())
            .transpose()
            .map_err(|_| ExecutionError::Invalid("invalid descriptor bits".into()))?;
        let signed = self
            .scalar("TYPE_SIGNED", key)?
            .filter(|v| !v.is_empty())
            .map(|v| v == "true");
        let extent = self.scalar("TYPE_EXTENT", key)?;
        let rank = self
            .scalar("TYPE_RANK", key)?
            .map(|v| v.parse())
            .transpose()
            .map_err(|_| ExecutionError::Invalid("invalid descriptor rank".into()))?;
        let qualifiers = self
            .rows("TYPE_QUALIFIER", Some(key), None)?
            .iter()
            .map(|f| f.object.clone())
            .collect();
        Ok(Knowledge::Known(Arc::new(TypeRef {
            kind,
            native,
            arguments,
            bits,
            signed,
            extent,
            rank,
            qualifiers,
        })))
    }
    pub fn matches(&mut self, actual: &Knowledge<Arc<TypeRef>>, expected: &Expr) -> Result<Truth> {
        self.match_type(actual, expected, 0)
    }
    fn match_type(
        &mut self,
        actual: &Knowledge<Arc<TypeRef>>,
        expected: &Expr,
        depth: usize,
    ) -> Result<Truth> {
        crate::with_stack(|| {
            (self.tick)()?;
            if depth > 128 {
                return Err(ExecutionError::Invalid(
                    "source matcher depth limit exceeded".into(),
                ));
            }
            if expected.kind == "wildcard" {
                return Ok(Truth::Known(true));
            }
            let Knowledge::Known(actual) = actual else {
                let Knowledge::Unknown(r) = actual else {
                    unreachable!()
                };
                return Ok(Truth::Unknown(r));
            };
            if expected.kind == "call" && expected.value == "oneof" {
                let mut accepted = Truth::Known(false);
                for arg in &expected.args {
                    accepted = accepted.or(self.match_type(
                        &Knowledge::Known(actual.clone()),
                        &arg.args[0],
                        depth + 1,
                    )?);
                }
                return Ok(accepted);
            }
            if matches!(actual.kind.as_str(), "opaque" | "generic") {
                return Ok(Truth::Unknown("unresolved_type_family"));
            }
            let aliases = &crate::capabilities::vocabulary().source_aliases;
            let expected_kind = aliases
                .get(&expected.value)
                .ok_or_else(|| ExecutionError::Invalid("unknown source type matcher".into()))?;
            if &actual.kind != expected_kind {
                return Ok(Truth::Known(false));
            }
            if expected.args.is_empty() {
                return Ok(Truth::Known(true));
            }
            if actual.arguments.is_empty() {
                return Ok(Truth::Unknown("type_arguments_unavailable"));
            }
            if actual.arguments.len() != expected.args.len() {
                return Ok(Truth::Known(false));
            }
            let mut accepted = Truth::Known(true);
            for (a, e) in actual.arguments.iter().zip(&expected.args) {
                accepted = accepted.and(self.match_type(
                    &Knowledge::Known(Arc::new(a.clone())),
                    e,
                    depth + 1,
                )?);
            }
            Ok(accepted)
        })
    }
}
