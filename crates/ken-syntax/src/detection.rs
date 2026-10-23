//! Original extension selection and optional C++ syntax evidence for .h files.
use crate::{GrammarCatalog, Language, ParseError, cpp};
use std::path::Path;
pub(crate) fn detect(
    catalog: &GrammarCatalog,
    path: &Path,
    source: Option<&[u8]>,
) -> Result<Option<Language>, ParseError> {
    let Some(extension) = path
        .extension()
        .and_then(|p| p.to_str())
        .map(str::to_lowercase)
    else {
        return Ok(None);
    };
    if extension == "h"
        && let Some(source) = source
    {
        match catalog.syntax(Language::Cpp, source, "header.h") {
            Ok(tree) if cpp::has_syntax(tree.root()) => return Ok(Some(Language::Cpp)),
            Err(ParseError::Grammar { .. }) => {}
            Err(error) => return Err(error),
            _ => {}
        }
    }
    Ok(Some(match extension.as_str() {
        "c" | "h" => Language::C,
        "cpp" | "cc" | "cxx" | "hpp" | "hh" | "hxx" | "ipp" => Language::Cpp,
        "cs" | "csx" => Language::CSharp,
        "css" => Language::Css,
        "html" | "htm" | "vue" | "svelte" => Language::Html,
        "py" | "pyi" => Language::Python,
        "rs" => Language::Rust,
        "rb" | "rake" | "gemspec" => Language::Ruby,
        "js" | "jsx" | "mjs" | "cjs" => Language::JavaScript,
        "ts" | "tsx" => Language::TypeScript,
        "go" => Language::Go,
        "java" => Language::Java,
        "kt" | "kts" => Language::Kotlin,
        "dart" => Language::Dart,
        "php" | "phtml" => Language::Php,
        "sql" => Language::Sql,
        "graphql" | "gql" => Language::GraphQL,
        "sh" | "bash" | "ksh" => Language::Bash,
        "ps1" | "psm1" | "psd1" => Language::PowerShell,
        _ => return Ok(None),
    }))
}
