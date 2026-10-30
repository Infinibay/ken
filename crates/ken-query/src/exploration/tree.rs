use super::*;
use crate::execution::values::Value;
use ken_program::value::GraphValue;
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, sync::Arc};
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NodeRecord {
    pub native_kind: String,
    pub kind: String,
    pub category: String,
    pub role: String,
    pub parent: Option<usize>,
    pub subtree_end: usize,
    pub start_byte: usize,
    pub end_byte: usize,
    pub flags: u8,
}
#[derive(Debug)]
pub struct SyntaxUnit {
    pub(super) path: String,
    pub(super) language: String,
    source: Arc<[u8]>,
    pub(super) records: Vec<NodeRecord>,
    pub(super) named: Vec<usize>,
    pub(super) kinds: BTreeMap<String, Vec<usize>>,
    pub(super) natives: BTreeMap<String, Vec<usize>>,
    pub(super) categories: BTreeMap<String, Vec<usize>>,
    lines: Vec<usize>,
}
impl SyntaxUnit {
    pub fn new(
        path: String,
        language: String,
        source: Arc<[u8]>,
        records: Vec<NodeRecord>,
    ) -> Result<Self> {
        Self::new_checked(path, language, source, records, &mut || Ok(()))
    }
    /// Shared validation/projection with cooperative host control for large units.
    pub fn new_checked(
        path: String,
        language: String,
        source: Arc<[u8]>,
        records: Vec<NodeRecord>,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        check()?;
        if records.is_empty() {
            return Err(invalid("syntax unit has no root"));
        }
        let n = records.len();
        let mut stack: Vec<usize> = vec![];
        for (i, r) in records.iter().enumerate() {
            if i % 256 == 0 {
                check()?;
            }
            while stack.last().is_some_and(|p| records[*p].subtree_end <= i) {
                stack.pop();
            }
            if r.parent != stack.last().copied()
                || r.subtree_end <= i
                || r.subtree_end > n
                || r.start_byte > r.end_byte
                || r.end_byte > source.len()
                || r.flags & !15 != 0
            {
                return Err(invalid("invalid syntax preorder record"));
            }
            if let Some(p) = r.parent {
                let parent = &records[p];
                if r.subtree_end > parent.subtree_end
                    || r.start_byte < parent.start_byte
                    || r.end_byte > parent.end_byte
                {
                    return Err(invalid("syntax child escapes parent"));
                }
            } else if i != 0 || r.subtree_end != n {
                return Err(invalid("syntax unit must have one enclosing root"));
            }
            stack.push(i);
        }
        let mut lines = vec![];
        for (chunk_index, chunk) in source.chunks(8192).enumerate() {
            check()?;
            lines.extend(
                chunk
                    .iter()
                    .enumerate()
                    .filter_map(|(i, c)| (*c == b'\n').then_some(chunk_index * 8192 + i)),
            );
        }
        let mut unit = Self {
            path,
            language,
            source,
            records,
            named: vec![],
            kinds: BTreeMap::new(),
            natives: BTreeMap::new(),
            categories: BTreeMap::new(),
            lines,
        };
        for i in 0..n {
            if i % 256 == 0 {
                check()?;
            }
            if unit.records[i].flags & 1 != 0 {
                unit.named.push(i);
                let kind = unit.kind(i);
                unit.kinds.entry(kind).or_default().push(i);
                unit.natives
                    .entry(unit.records[i].native_kind.clone())
                    .or_default()
                    .push(i);
                unit.categories
                    .entry(unit.records[i].category.clone())
                    .or_default()
                    .push(i);
            }
        }
        Ok(unit)
    }
    pub fn records(&self) -> &[NodeRecord] {
        &self.records
    }
    pub(super) fn children(&self, i: usize, named: bool) -> Vec<usize> {
        let mut out = vec![];
        let mut c = i + 1;
        while c < self.records[i].subtree_end {
            if !named || self.records[c].flags & 1 != 0 {
                out.push(c);
            }
            c = self.records[c].subtree_end;
        }
        out
    }
    fn spelling(&self, i: usize) -> String {
        let r = &self.records[i];
        String::from_utf8_lossy(&self.source[r.start_byte..r.end_byte]).into_owned()
    }
    fn operator(&self, i: usize) -> String {
        // Exact exploration vocabulary, intentionally narrower than source-operation lowering.
        let tokens = self
            .children(i, false)
            .into_iter()
            .filter(|c| self.records[*c].flags & 1 == 0)
            .map(|c| self.records[c].native_kind.as_str())
            .filter(|s| {
                matches!(
                    *s,
                    "==" | "!="
                        | "==="
                        | "!=="
                        | "<"
                        | ">"
                        | "<="
                        | ">="
                        | "in"
                        | "is"
                        | "not in"
                        | "is not"
                        | "+"
                        | "-"
                        | "*"
                        | "/"
                        | "//"
                        | "%"
                        | "**"
                        | "="
                        | "+="
                        | "-="
                        | "*="
                        | "/="
                        | "&&"
                        | "||"
                        | "and"
                        | "or"
                        | "not"
                        | "!"
                        | "&"
                        | "|"
                        | "^"
                        | "~"
                        | "<<"
                        | ">>"
                        | "??"
                        | ":="
                )
            })
            .collect::<Vec<_>>()
            .join(" ");
        match tokens.as_str() {
            "&&" => "and".into(),
            "||" => "or".into(),
            "!" => "not".into(),
            ":=" => "=".into(),
            _ => tokens,
        }
    }
    pub(super) fn kind(&self, i: usize) -> String {
        let r = &self.records[i];
        if r.kind == "binary"
            && matches!(
                self.operator(i).as_str(),
                "==" | "!="
                    | "==="
                    | "!=="
                    | "<"
                    | ">"
                    | "<="
                    | ">="
                    | "in"
                    | "is"
                    | "not in"
                    | "is not"
            )
        {
            "compare".into()
        } else {
            r.kind.clone()
        }
    }
    pub fn property(&self, i: usize, name: &str) -> Value {
        let Some(r) = self.records.get(i) else {
            return Value::unknown("syntax_node_unavailable");
        };
        let kind = self.kind(i);
        match name {
            "path" => Value::string(self.path.as_str()),
            "language" => Value::string(self.language.as_str()),
            "native_kind" => Value::string(r.native_kind.as_str()),
            "start_byte" => Value::integer(r.start_byte),
            "end_byte" => Value::integer(r.end_byte),
            "line" => Value::integer(self.lines.partition_point(|b| *b < r.start_byte) + 1),
            "kind" => Value::string(kind.as_str()),
            "category" => Value::string(r.category.as_str()),
            "operator" => Value::string(self.operator(i)),
            "normalized" => Value::boolean(r.category != "opaque"),
            "role" => Value::string(
                r.parent
                    .map(|p| ken_program::canonical_syntax_role(&self.kind(p), &r.role).to_owned())
                    .unwrap_or_default(),
            ),
            "name" => {
                let name = if kind == "identifier" {
                    self.spelling(i)
                } else if kind == "module" {
                    self.path.clone()
                } else {
                    let names = self
                        .children(i, true)
                        .into_iter()
                        .filter(|c| self.records[*c].role == "name")
                        .collect::<Vec<_>>();
                    if names.len() == 1 {
                        self.spelling(names[0])
                    } else {
                        String::new()
                    }
                };
                Value::string(name)
            }
            "text" => Value::string(if kind == "literal" || self.children(i, true).is_empty() {
                self.spelling(i)
            } else {
                String::new()
            }),
            "type_kind" => {
                if kind != "literal" {
                    return Value::unknown("type_resolution_required");
                }
                let t = self.spelling(i);
                let native = r.native_kind.as_str();
                let found = if matches!(t.as_str(), "true" | "false" | "True" | "False") {
                    Some("bool")
                } else if matches!(t.as_str(), "None" | "null" | "nil") {
                    Some("null")
                } else if native.contains("char") || native.contains("rune") {
                    Some("char")
                } else if native.contains("string") {
                    Some("str")
                } else if native.contains("float") || native.contains("real") {
                    Some("float")
                } else if matches!(native, "number" | "number_literal") {
                    let s = t.to_lowercase().replace('_', "");
                    Some(
                        if s.contains('.')
                            || if s.starts_with("0x") {
                                s.contains('p')
                            } else {
                                s.contains('e') && !s.starts_with("0b") && !s.starts_with("0o")
                            }
                        {
                            "float"
                        } else {
                            "int"
                        },
                    )
                } else if native.contains("integer") || native == "int_literal" {
                    Some("int")
                } else {
                    None
                };
                found.map_or_else(|| Value::unknown("literal_type_unavailable"), Value::string)
            }
            _ => Value::unknown(format!("syntax_property_unavailable:{name}")),
        }
    }
    pub(super) fn local_id(&self, i: usize) -> String {
        let r = &self.records[i];
        format!(
            "{}::syntax:{i}:{}:{}:{}",
            self.path, r.start_byte, r.end_byte, r.native_kind
        )
    }
    pub(super) fn record(&self, i: usize) -> Value {
        Value::Scalar(GraphValue::Dict(
            [
                "path",
                "language",
                "native_kind",
                "kind",
                "start_byte",
                "end_byte",
                "line",
            ]
            .into_iter()
            .map(|key| {
                let Value::Scalar(v) = self.property(i, key) else {
                    unreachable!()
                };
                (key.into(), v)
            })
            .collect(),
        ))
    }
}
