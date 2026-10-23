//! Source-compatible parser results; syntax ownership stays in the frontend.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParsedSymbol {
    pub kind: String,
    pub name: String,
    pub qualname: String,
    pub line_start: usize,
    pub line_end: usize,
    pub docstring: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParsedImport {
    pub module: String,
    pub line: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParsedScope {
    pub symbol: ParsedSymbol,
    pub signature: String,
    pub documentation: Option<crate::PythonText>,
    pub owner: Option<String>,
    pub statements: Vec<(usize, usize)>,
    pub implementation_start_line: Option<usize>,
    pub annotations: Vec<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ParsedFile {
    pub symbols: Vec<ParsedSymbol>,
    pub imports: Vec<ParsedImport>,
    pub docstring: Option<String>,
    pub scopes: Vec<ParsedScope>,
}
