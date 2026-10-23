//! Public common-ast/1 values and the original structural validity boundary.
use crate::ProgramError;
use serde::{Deserialize, Serialize};
pub const VERSION: &str = "common-ast/1";
fn version() -> String {
    VERSION.into()
}
fn unknown() -> String {
    "unknown".into()
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Node {
    pub id: usize,
    pub kind: String,
    pub category: String,
    #[serde(deserialize_with = "crate::nullable")]
    pub parent: Option<usize>,
    pub ordinal: i64,
    pub role: String,
    pub native_role: String,
    pub native_kind: String,
    pub source_id: String,
    pub start: i64,
    pub end: i64,
    pub line: i64,
    pub scope: usize,
    pub owner: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub operator: String,
    #[serde(default)]
    pub type_kind: String,
    #[serde(default)]
    pub flags: Vec<String>,
    #[serde(default)]
    pub subtree_end: usize,
    #[serde(default)]
    pub argument_kind: String,
    #[serde(default)]
    pub argument_name: String,
    #[serde(default)]
    pub argument_position: Option<i64>,
    #[serde(default)]
    pub source_position: Option<i64>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    pub id: usize,
    #[serde(deserialize_with = "crate::nullable")]
    pub parent: Option<usize>,
    pub node: usize,
    pub kind: String,
    pub name: String,
    pub namespace: String,
    #[serde(deserialize_with = "crate::nullable")]
    pub lookup_parent: Option<usize>,
    #[serde(default)]
    pub global_names: Vec<String>,
    #[serde(default)]
    pub nonlocal_names: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Symbol {
    pub id: usize,
    pub name: String,
    pub scope: usize,
    pub declaration: usize,
    pub kind: String,
    pub source_id: String,
    pub visible_from: i64,
    #[serde(deserialize_with = "crate::nullable")]
    pub initialized_from: Option<i64>,
    #[serde(default = "unknown")]
    pub type_kind: String,
    #[serde(default)]
    pub native_type: String,
    #[serde(default)]
    pub mutable: Option<bool>,
    #[serde(default)]
    pub flags: Vec<String>,
    #[serde(default)]
    pub position: Option<i64>,
    #[serde(default)]
    pub parameter_kind: String,
    #[serde(default)]
    pub native_position: Option<i64>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reference {
    pub node: usize,
    pub name: String,
    pub scope: usize,
    pub mode: String,
    #[serde(deserialize_with = "crate::nullable")]
    pub symbol: Option<usize>,
    pub status: String,
    #[serde(default)]
    pub reason: String,
    #[serde(default = "unknown")]
    pub availability: String,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Link {
    pub source: usize,
    pub relation: String,
    pub target: usize,
    #[serde(default)]
    pub ordinal: i64,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Program {
    pub path: String,
    pub language: String,
    pub nodes: Vec<Node>,
    pub scopes: Vec<Scope>,
    pub symbols: Vec<Symbol>,
    pub references: Vec<Reference>,
    pub links: Vec<Link>,
    pub diagnostics: Vec<String>,
    #[serde(default = "version")]
    pub version: String,
}
impl Program {
    pub fn from_json(data: &str) -> Result<Self, ProgramError> {
        let program: Self = serde_json::from_str(data)?;
        program.validate()?;
        Ok(program)
    }
    pub fn to_json(&self) -> Result<String, ProgramError> {
        Ok(serde_json::to_string(self)?)
    }
    pub fn validate(&self) -> Result<(), ProgramError> {
        let fail = |message| Err(ProgramError::Invalid(message));
        if self.version != VERSION {
            return fail("incompatible common AST");
        }
        for (i, node) in self.nodes.iter().enumerate() {
            if node.id != i
                || node.start < 0
                || node.end < node.start
                || node.subtree_end <= i
                || node.subtree_end > self.nodes.len()
            {
                return fail("invalid AST node or range");
            }
            if let Some(parent) = node.parent
                && (parent >= i || i >= self.nodes[parent].subtree_end)
            {
                return fail("invalid AST parent");
            }
            if node.scope >= self.scopes.len() {
                return fail("invalid AST scope");
            }
        }
        for (i, scope) in self.scopes.iter().enumerate() {
            if scope.id != i || scope.node >= self.nodes.len() {
                return fail("invalid scope");
            }
            if [scope.parent, scope.lookup_parent]
                .iter()
                .any(|parent| parent.is_some_and(|p| p >= i))
            {
                return fail("invalid scope ancestry");
            }
        }
        for (i, symbol) in self.symbols.iter().enumerate() {
            if symbol.id != i
                || symbol.scope >= self.scopes.len()
                || symbol.declaration >= self.nodes.len()
            {
                return fail("invalid symbol");
            }
        }
        for reference in &self.references {
            if reference.node >= self.nodes.len()
                || reference.scope >= self.scopes.len()
                || reference.symbol.is_some_and(|s| s >= self.symbols.len())
            {
                return fail("invalid reference");
            }
        }
        for link in &self.links {
            if link.source >= self.nodes.len() || link.target >= self.nodes.len() {
                return fail("invalid AST link");
            }
        }
        Ok(())
    }
}
