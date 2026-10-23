//! Native syntax ownership and source-compatible language extraction.
mod grammar;
mod syntax;
pub use grammar::{GrammarCatalog, Language, ParseError};
pub use syntax::{SyntaxNode, SyntaxRecord, SyntaxTree};
