//! An unresolved edge retains original project-intent versus external meaning.
use super::{
    Resolution,
    aliases::AliasResolver,
    languages::{LanguageModules, directory},
    paths,
};
use std::collections::BTreeSet;
pub(super) fn classify(
    module: &str,
    language: Option<&str>,
    source: &str,
    aliases: &AliasResolver,
    languages: &LanguageModules,
    files: &BTreeSet<String>,
) -> Resolution {
    let m = paths::trim(
        paths::trim(module)
            .trim_matches('"')
            .trim_matches('\'')
            .trim_end_matches(';'),
    );
    let unresolved = match language {
        Some("typescript" | "javascript") => {
            m.starts_with("./") || m.starts_with("../") || aliases.is_internal_shape(m, source)
        }
        Some("rust") => matches!(
            paths::trim(
                m.split("::")
                    .next()
                    .unwrap_or("")
                    .split('{')
                    .next()
                    .unwrap_or("")
            ),
            "crate" | "super" | "self"
        ),
        Some("go") => languages.go_modules.iter().any(|(_, prefix)| {
            m == prefix || m.strip_prefix(prefix).is_some_and(|s| s.starts_with('/'))
        }),
        Some("python") => {
            let slash = m.replace('.', "/");
            m.starts_with('.')
                || files.iter().any(|p| {
                    *p == format!("{slash}.py")
                        || p.ends_with(&format!("/{slash}.py"))
                        || p.ends_with(&format!("/{slash}/__init__.py"))
                })
        }
        Some("java") => {
            !["java.", "javax.", "jakarta."]
                .iter()
                .any(|p| m.starts_with(p))
                && files
                    .iter()
                    .any(|p| p.ends_with(&format!("/{}.java", m.replace('.', "/"))))
        }
        Some("kotlin") => {
            if [
                "kotlin.",
                "kotlinx.",
                "java.",
                "javax.",
                "jakarta.",
                "android.",
                "androidx.",
            ]
            .iter()
            .any(|p| m.starts_with(p))
            {
                false
            } else {
                let trimmed = m.trim_end_matches('*').trim_end_matches('.');
                let package = if m.contains('.') {
                    trimmed.rsplit_once('.').map_or(trimmed, |(p, _)| p)
                } else {
                    m
                };
                let path = package.replace('.', "/");
                files.iter().any(|p| {
                    (p.ends_with(".kt") || p.ends_with(".kts"))
                        && (directory(p) == path || directory(p).ends_with(&format!("/{path}")))
                })
            }
        }
        Some("php") => {
            if module.contains('\\') || (!m.starts_with(['.', '/']) && !m.ends_with(".php")) {
                let name = m.trim_start_matches('\\').replace('\\', "/");
                let tail = name.rsplit('/').next().unwrap_or("");
                files
                    .iter()
                    .any(|p| *p == format!("{tail}.php") || p.ends_with(&format!("/{tail}.php")))
            } else {
                m.starts_with(['.', '/']) || m.ends_with(".php")
            }
        }
        Some("cpp") => {
            let base = m.rsplit('/').next().unwrap_or("");
            paths::trim(module).starts_with('"')
                && files.iter().any(|p| {
                    p.as_str() == m
                        || p.ends_with(&format!("/{m}"))
                        || p.ends_with(&format!("/{base}"))
                })
        }
        _ => m.starts_with(['.', '/']),
    };
    if unresolved {
        Resolution::Unresolved
    } else {
        Resolution::External
    }
}
