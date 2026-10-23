//! Coordinate grammar selection and the language that owns extraction rules.
use crate::{
    GrammarCatalog, Language, ParseError, ecmascript, go, java, model::ParsedFile, python, rust,
};
use crate::{
    bash, c, cpp, csharp, css, dart, detection, graphql, html, kotlin, php, powershell, ruby, sql,
};

pub struct ParserRegistry {
    catalog: GrammarCatalog,
}
impl ParserRegistry {
    pub fn new(catalog: GrammarCatalog) -> Self {
        Self { catalog }
    }
    pub fn detect(
        &self,
        path: &std::path::Path,
        source: Option<&[u8]>,
    ) -> Result<Option<Language>, ParseError> {
        detection::detect(&self.catalog, path, source)
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
            Language::C => Ok(c::extract(source, tree.root())),
            Language::Cpp => cpp::extract(source, tree.root(), |header| {
                self.catalog.syntax(Language::Cpp, header, "namespace.hpp")
            }),
            Language::CSharp => Ok(csharp::extract(source, tree.root())),
            Language::Ruby => Ok(ruby::extract(source, tree.root())),
            Language::Kotlin => Ok(kotlin::extract(source, tree.root())),
            Language::Dart => Ok(dart::extract(source, tree.root())),
            Language::Php => Ok(php::extract(source, tree.root())),
            Language::Bash => Ok(bash::extract(source, tree.root())),
            Language::PowerShell => Ok(powershell::extract(source, tree.root())),
            Language::Css => Ok(css::extract(source, tree.root())),
            Language::Html => Ok(html::extract(source, tree.root())),
            Language::GraphQL => Ok(graphql::extract(source, tree.root())),
            Language::Sql => Ok(sql::extract(source, tree.root())),
        }
    }
}
