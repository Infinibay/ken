//! Original lexical path joining, module suffix priority and ambiguity rules.
use std::collections::{BTreeMap, BTreeSet};

const JS_EXTENSIONS: [&str; 7] = [".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs"];
pub(super) fn trim(value: &str) -> &str {
    value.trim_matches(|c: char| c.is_whitespace() || matches!(c, '\x1c'..='\x1f'))
}
pub(super) fn python_suffixes(files: &[String]) -> BTreeMap<String, Vec<String>> {
    let mut index: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for path in files.iter().filter(|p| p.ends_with(".py")) {
        let parts: Vec<_> = path.split('/').collect();
        for i in 1..parts.len() {
            index
                .entry(format!("/{}", parts[i..].join("/")))
                .or_default()
                .push(path.clone());
        }
    }
    index
}
pub(super) fn join_relative(source: &str, module: &str) -> String {
    let mut parts: Vec<_> = source.split('/').collect();
    parts.pop();
    for segment in module.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(segment),
        }
    }
    parts.join("/")
}
pub(super) fn match_js_module(joined: &str, files: &BTreeSet<String>) -> Option<String> {
    if joined.is_empty() {
        return None;
    }
    if files.contains(joined) {
        return Some(joined.into());
    }
    let stem = [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]
        .into_iter()
        .find_map(|ext| joined.strip_suffix(ext))
        .unwrap_or(joined);
    for suffix in JS_EXTENSIONS {
        let candidate = format!("{stem}{suffix}");
        if files.contains(&candidate) {
            return Some(candidate);
        }
    }
    for suffix in JS_EXTENSIONS {
        let candidate = format!("{stem}/index{suffix}");
        if files.contains(&candidate) {
            return Some(candidate);
        }
    }
    None
}
pub(super) fn structural_target(
    module: &str,
    source: Option<&str>,
    files: &BTreeSet<String>,
    suffixes: &BTreeMap<String, Vec<String>>,
) -> Option<String> {
    let module = trim(module).trim_matches(['\'', '"']);
    if module.is_empty() {
        return None;
    }
    if let Some(source) = source.filter(|_| module.starts_with("./") || module.starts_with("../")) {
        return match_js_module(&join_relative(source, module), files);
    }
    let module = module.trim_start_matches('.');
    let slash = module.replace('.', "/");
    let mut candidates: BTreeSet<_> = [
        ".py",
        "/__init__.py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".java",
        ".rs",
        ".dart",
    ]
    .into_iter()
    .map(|ext| format!("{slash}{ext}"))
    .collect();
    if module.contains('/') {
        candidates.extend([
            module.to_owned(),
            format!("{module}.py"),
            format!("{module}.ts"),
            format!("{module}.js"),
        ]);
    }
    let mut matches: BTreeSet<_> = candidates.intersection(files).cloned().collect();
    if let Some(paths) = suffixes.get(&format!("/{slash}.py")) {
        matches.extend(paths.iter().cloned());
    }
    (matches.len() == 1)
        .then(|| matches.into_iter().next())
        .flatten()
}
