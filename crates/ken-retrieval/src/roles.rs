use regex::Regex;
use std::sync::OnceLock;
pub fn classify_role(path: &str, name: Option<&str>, annotations: &[String]) -> &'static str {
    static RUST: OnceLock<Regex> = OnceLock::new();
    static JS: OnceLock<Regex> = OnceLock::new();
    let rust =
        RUST.get_or_init(|| Regex::new(r"^#\[\s*(?:test|cfg\(\s*test\s*\))\s*\]\z").unwrap());
    let js = JS.get_or_init(|| Regex::new(r"(?i)\.(?:test|spec)\.(?:[cm]?[jt]sx?)\z").unwrap());
    let parts: Vec<_> = path
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .collect();
    let file = parts.last().copied().unwrap_or("");
    let stem = file
        .rsplit_once('.')
        .filter(|(s, _)| !s.is_empty())
        .map_or(file, |(s, _)| s);
    let lower: Vec<_> = parts.iter().map(|s| s.to_lowercase()).collect();
    if lower.iter().any(|s| {
        matches!(
            s.as_str(),
            "tests" | "test" | "__tests__" | "spec" | "specs"
        )
    }) || stem.to_lowercase().starts_with("test_")
        || name
            .unwrap_or("")
            .rsplit('.')
            .next()
            .unwrap_or("")
            .starts_with("test_")
        || file.ends_with("_test.go")
        || js.is_match(file)
        || annotations
            .iter()
            .any(|a| rust.is_match(a.trim_matches(ken_text::unicode::whitespace)))
    {
        return "test";
    }
    if lower
        .iter()
        .any(|s| matches!(s.as_str(), "examples" | "example" | "demo" | "demos"))
    {
        return "example";
    }
    if lower
        .iter()
        .any(|s| matches!(s.as_str(), "docs" | "doc" | "documentation"))
        || file
            .rsplit_once('.')
            .is_some_and(|(_, s)| matches!(s.to_lowercase().as_str(), "md" | "rst" | "txt"))
    {
        return "documentation";
    }
    "definition"
}
