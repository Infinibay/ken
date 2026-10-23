//! Native syntax ownership and source-compatible language extraction.
mod grammar;
mod syntax;
pub use grammar::{GrammarCatalog, Language, ParseError};
pub use syntax::{SyntaxNode, SyntaxRecord, SyntaxTree};

mod helpers;
mod model;
mod python;
mod registry;
mod rust;
mod scopes;
pub use model::{ParsedFile, ParsedImport, ParsedScope, ParsedSymbol};
pub use registry::ParserRegistry;
mod ecmascript;
mod ecmascript_scopes;
mod go;
mod java;
mod python_literal;
