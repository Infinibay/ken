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
mod c;
mod cpp;
mod cpp_declarator;
mod csharp;
mod dart;
mod detection;
mod ecmascript;
mod ecmascript_scopes;
mod go;
mod java;
mod kotlin;
mod php;
mod python_literal;
mod python_unicode;
mod ruby;
