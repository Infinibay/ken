//! Coordinate grammar selection and the language that owns extraction rules.
use crate::{
    GrammarCatalog, Language, ParseError, ecmascript, go, java, model::ParsedFile, python, rust,
};

pub struct ParserRegistry {
    catalog: GrammarCatalog,
}
impl ParserRegistry {
    pub fn new(catalog: GrammarCatalog) -> Self {
        Self { catalog }
    }
    pub fn parse(
        &self,
        language: Language,
        source: &[u8],
        hint: &str,
    ) -> Result<ParsedFile, ParseError> {
        let tree = self.catalog.syntax(language, source, hint)?;
        match language {
            Language::Python => Ok(python::extract(source, tree.root())),
            Language::Rust => Ok(rust::extract(source, tree.root())),
            Language::JavaScript => ecmascript::extract(source, tree.root(), false),
            Language::TypeScript => ecmascript::extract(source, tree.root(), true),
            Language::Go => Ok(go::extract(source, tree.root())),
            Language::Java => Ok(java::extract(source, tree.root())),
            _ => Err(ParseError::Parse {
                language: language.as_str().into(),
                reason: "frontend migration pending".into(),
            }),
        }
    }
}
