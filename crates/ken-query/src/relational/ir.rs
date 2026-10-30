//! Immutable relational operator data. Literal tokens never become role names.
use crate::{BodyPattern, ast::*};
use serde::Serialize;
use std::{collections::BTreeMap, sync::Arc};
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "OrderedMap")]
pub struct OrderedMap<T> {
    pub(crate) items: Vec<(String, T)>,
    #[serde(skip)]
    positions: BTreeMap<String, usize>,
}
impl<T> Default for OrderedMap<T> {
    fn default() -> Self {
        Self {
            items: vec![],
            positions: BTreeMap::new(),
        }
    }
}
impl<T> OrderedMap<T> {
    pub fn items(&self) -> &[(String, T)] {
        &self.items
    }
    pub fn get(&self, key: &str) -> Option<&T> {
        self.positions.get(key).map(|i| &self.items[*i].1)
    }
    pub(crate) fn insert(&mut self, key: String, value: T) {
        if let Some(i) = self.positions.get(&key) {
            self.items[*i].1 = value;
        } else {
            self.positions.insert(key.clone(), self.items.len());
            self.items.push((key, value));
        }
    }
}
impl<T> FromIterator<(String, T)> for OrderedMap<T> {
    fn from_iter<I: IntoIterator<Item = (String, T)>>(values: I) -> Self {
        let mut result = Self::default();
        for (k, v) in values {
            result.insert(k, v);
        }
        result
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "QuotedTerm")]
pub struct QuotedTerm {
    pub token: String,
    pub literal: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum Term {
    Text(String),
    Literal(QuotedTerm),
}
impl Term {
    pub fn token(&self) -> &str {
        match self {
            Self::Text(v) => v,
            Self::Literal(v) => &v.token,
        }
    }
    pub fn literal(&self) -> Option<&str> {
        match self {
            Self::Literal(v) => Some(&v.literal),
            _ => None,
        }
    }
    pub(crate) fn rewrite(&mut self, aliases: &BTreeMap<String, String>) {
        if let Self::Text(v) = self {
            *v = rewrite_text(v, aliases);
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "FrozenEdge")]
pub struct Edge {
    pub mode: String,
    pub subject: Term,
    pub relation: String,
    pub object: Term,
    pub attrs: Vec<(String, String, String)>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum PlanValue {
    None,
    Term(Term),
    Integer(crate::IntegerLiteral),
    Tuple(Vec<PlanValue>),
    Map(OrderedMap<PlanValue>),
    Edge(Edge),
    Expression(Expression),
    Body(BodyPattern),
}
impl PlanValue {
    pub(crate) fn text(v: impl Into<String>) -> Self {
        Self::Term(Term::Text(v.into()))
    }
    pub(crate) fn tuple(v: Vec<Self>) -> Self {
        Self::Tuple(v)
    }
    pub(crate) fn number(v: usize) -> Self {
        Self::Integer(crate::IntegerLiteral::from_digits(&v.to_string()))
    }
    pub(crate) fn string(&self) -> Option<&str> {
        if let Self::Term(Term::Text(v)) = self {
            Some(v)
        } else {
            None
        }
    }
    pub(crate) fn rewrite(&mut self, aliases: &BTreeMap<String, String>) {
        crate::with_stack(|| match self {
            Self::Term(v) => v.rewrite(aliases),
            Self::Tuple(v) => {
                for x in v {
                    x.rewrite(aliases);
                }
            }
            Self::Map(v) => {
                for (_, x) in &mut v.items {
                    x.rewrite(aliases);
                }
            }
            Self::Edge(v) => {
                v.subject.rewrite(aliases);
                v.object.rewrite(aliases);
            }
            _ => (),
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "FrozenNode")]
pub struct Node {
    pub kind: String,
    pub value: PlanValue,
    pub children: Vec<Vec<Node>>,
}
impl Node {
    pub(crate) fn new(kind: &str, value: PlanValue) -> Self {
        Self {
            kind: kind.into(),
            value,
            children: vec![],
        }
    }
    pub(crate) fn branches(kind: &str, value: PlanValue, children: Vec<Vec<Node>>) -> Self {
        Self {
            kind: kind.into(),
            value,
            children,
        }
    }
    pub(crate) fn rewrite(&mut self, aliases: &BTreeMap<String, String>) {
        crate::with_stack(|| {
            self.value.rewrite(aliases);
            for child in self.children.iter_mut().flatten() {
                child.rewrite(aliases);
            }
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "FrozenQuery")]
pub struct RelationalQuery {
    pub name: String,
    pub nodes: Arc<Vec<Node>>,
    pub exports: OrderedMap<String>,
    pub definitions: OrderedMap<Arc<RelationalQuery>>,
}
impl RelationalQuery {
    pub fn dependencies(&self) -> Vec<(String, OrderedMap<String>)> {
        let mut result = vec![];
        let mut pending: Vec<_> = self.nodes.iter().rev().collect();
        while let Some(node) = pending.pop() {
            if node.kind == "match"
                && let PlanValue::Tuple(values) = &node.value
                && let (Some(name), Some(PlanValue::Map(bindings))) =
                    (values.first().and_then(PlanValue::string), values.get(1))
            {
                result.push((
                    name.into(),
                    bindings
                        .items
                        .iter()
                        .filter_map(|(k, v)| v.string().map(|s| (k.clone(), s.into())))
                        .collect(),
                ));
            }
            for branch in node.children.iter().rev() {
                pending.extend(branch.iter().rev());
            }
        }
        result
    }
}
pub(crate) fn rewrite_text(value: &str, aliases: &BTreeMap<String, String>) -> String {
    let (head, tail) = value
        .split_once('.')
        .map_or((value, None), |(h, t)| (h, Some(t)));
    let head = aliases.get(head).map_or(head, String::as_str);
    tail.map_or_else(|| head.into(), |t| format!("{head}.{t}"))
}
pub(crate) fn fact(a: Term, relation: &str, b: Term, attrs: Vec<(String, String, String)>) -> Node {
    Node::new(
        "fact",
        PlanValue::Edge(Edge {
            mode: "require".into(),
            subject: a,
            relation: relation.into(),
            object: b,
            attrs,
        }),
    )
}
