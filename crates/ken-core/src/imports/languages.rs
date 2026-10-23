//! Language module lookup owns each ecosystem's actual inventory/config rules.
use super::{ImportError, config, paths};
use std::collections::{BTreeMap, BTreeSet};
pub(super) struct LanguageModules {
    java: Vec<String>,
    kotlin: Vec<String>,
    cargo: Vec<String>,
    pub go_modules: Vec<(String, String)>,
    go_files: BTreeMap<String, Vec<String>>,
    php: Vec<(String, String)>,
}
impl LanguageModules {
    pub fn from_inputs(
        files: &[String],
        configs: Option<&BTreeMap<String, Vec<u8>>>,
    ) -> Result<Self, ImportError> {
        let mut cargo: Vec<_> = files
            .iter()
            .filter(|p| p.ends_with("Cargo.toml"))
            .map(|p| directory(p).to_owned())
            .collect();
        cargo.sort_by_key(|d| std::cmp::Reverse(d.chars().count()));
        let mut go_files: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for path in files.iter().filter(|p| p.ends_with(".go")) {
            go_files
                .entry(directory(path).into())
                .or_default()
                .push(path.clone());
        }
        let mut go_modules: Vec<(String, String)> = Vec::new();
        let mut php = Vec::new();
        if let Some(configs) = configs {
            for file in files {
                if file.ends_with("go.mod")
                    && let Some(bytes) = configs.get(file)
                {
                    let text = String::from_utf8_lossy(bytes);
                    for line in python_lines(&text).map(paths::trim) {
                        if let Some(module) = line.strip_prefix("module ") {
                            go_modules.push((directory(file).into(), paths::trim(module).into()));
                            break;
                        }
                    }
                }
                if file.ends_with("composer.json")
                    && let Some(bytes) = configs.get(file)
                {
                    let Some(data) = std::str::from_utf8(bytes).ok().and_then(config::parse) else {
                        continue;
                    };
                    if data.object().is_none() {
                        return Err(invalid(file, "composer data has no dictionary get method"));
                    }
                    for section in ["autoload", "autoload-dev"] {
                        let Some(section) = data.get(section).filter(|v| v.truth()) else {
                            continue;
                        };
                        if section.object().is_none() {
                            return Err(invalid(
                                file,
                                "autoload section has no dictionary get method",
                            ));
                        }
                        let Some(mapping) = section.get("psr-4").filter(|v| v.truth()) else {
                            continue;
                        };
                        let Some(mapping) = mapping.object() else {
                            return Err(invalid(
                                file,
                                "PSR4 mapping has no dictionary items method",
                            ));
                        };
                        for (prefix, dirs) in mapping {
                            let Some(prefix) = prefix else {
                                continue;
                            };
                            let values = if let config::ConfigValue::Array(values) = dirs {
                                values.as_slice()
                            } else {
                                std::slice::from_ref(dirs)
                            };
                            for value in values {
                                if let Some(value) = value.python_string() {
                                    let base = directory(file);
                                    let full = if base.is_empty() {
                                        value
                                    } else {
                                        format!("{base}/{value}")
                                    };
                                    php.push((prefix.clone(), full.trim_matches('/').into()));
                                }
                            }
                        }
                    }
                }
            }
        }
        go_modules.sort_by_key(|(dir, _)| std::cmp::Reverse(dir.chars().count()));
        php.sort_by_key(|(prefix, _)| std::cmp::Reverse(prefix.chars().count()));
        Ok(Self {
            java: files
                .iter()
                .filter(|p| p.ends_with(".java"))
                .cloned()
                .collect(),
            kotlin: files
                .iter()
                .filter(|p| p.ends_with(".kt") || p.ends_with(".kts"))
                .cloned()
                .collect(),
            cargo,
            go_modules,
            go_files,
            php,
        })
    }
    pub fn resolve(
        &self,
        module: &str,
        source: &str,
        language: Option<&str>,
        files: &BTreeSet<String>,
    ) -> Option<String> {
        match language {
            Some("java") => java(module, &self.java),
            Some("rust") => rust(module, source, files, &self.cargo),
            Some("go") => self.go(module, source),
            Some("ruby") => ruby(module, source, files),
            Some("cpp") => cpp(module, source, files),
            Some("kotlin") => kotlin(module, &self.kotlin),
            Some("php") => php(module, &self.php, files),
            _ => None,
        }
    }
    fn go(&self, module: &str, source: &str) -> Option<String> {
        let module = paths::trim(module).trim_matches('"');
        let source_dir = directory(source);
        for (dir, prefix) in &self.go_modules {
            if !contains(dir, source_dir) {
                continue;
            }
            if module == prefix
                || module
                    .strip_prefix(prefix)
                    .is_some_and(|s| s.starts_with('/'))
            {
                let relative = module[prefix.len()..].trim_matches('/');
                let package = if relative.is_empty() {
                    dir.clone()
                } else {
                    format!("{dir}/{relative}").trim_matches('/').to_owned()
                };
                return self
                    .go_files
                    .get(&package)
                    .and_then(|files| files.iter().filter(|p| !p.ends_with("_test.go")).min())
                    .cloned();
            }
        }
        None
    }
}
fn invalid(path: &str, reason: &str) -> ImportError {
    ImportError::Config {
        path: path.into(),
        reason: reason.into(),
    }
}
pub(super) fn directory(path: &str) -> &str {
    path.rsplit_once('/').map_or("", |(d, _)| d)
}
fn contains(base: &str, directory: &str) -> bool {
    base.is_empty()
        || base == directory
        || directory
            .strip_prefix(base)
            .is_some_and(|s| s.starts_with('/'))
}
fn java(module: &str, files: &[String]) -> Option<String> {
    let module = paths::trim(paths::trim(module).trim_matches(';'));
    if module.is_empty() || module.ends_with('*') {
        return None;
    }
    for candidate in [module, module.rsplit_once('.').map_or(module, |(m, _)| m)] {
        let suffix = candidate.replace('.', "/") + ".java";
        let matches: Vec<_> = files
            .iter()
            .filter(|p| *p == &suffix || p.ends_with(&format!("/{suffix}")))
            .collect();
        if matches.len() == 1 {
            return Some(matches[0].clone());
        }
    }
    None
}
fn rust(module: &str, source: &str, files: &BTreeSet<String>, cargo: &[String]) -> Option<String> {
    let module = paths::trim(module.split('{').next().unwrap_or("")).trim_matches(':');
    if module.is_empty() {
        return None;
    }
    let mut parts: Vec<_> = module.split("::").filter(|s| !s.is_empty()).collect();
    if parts.last() == Some(&"*") {
        parts.pop();
        if !parts.is_empty() && parts.iter().all(|p| matches!(*p, "super" | "self")) {
            return files.contains(source).then(|| source.into());
        }
    }
    let root = cargo
        .iter()
        .find(|d| contains(d, directory(source)))
        .map(|d| format!("{d}/src").trim_start_matches('/').to_owned());
    let (base, segments) = match parts.first().copied().unwrap_or("") {
        "crate" => (root, &parts[1..]),
        "self" => (Some(directory(source).into()), &parts[1..]),
        "super" => {
            let mut base = directory(source);
            let mut count = 0;
            while parts.get(count) == Some(&"super") {
                base = directory(base);
                count += 1;
            }
            (Some(base.into()), &parts[count..])
        }
        _ => (root, parts.as_slice()),
    };
    let base = base?;
    for count in (1..=segments.len()).rev() {
        let stem = format!("{base}/{}", segments[..count].join("/"))
            .trim_matches('/')
            .to_owned();
        for candidate in [format!("{stem}.rs"), format!("{stem}/mod.rs")] {
            if files.contains(&candidate) {
                return Some(candidate);
            }
        }
    }
    None
}
fn ruby(module: &str, source: &str, files: &BTreeSet<String>) -> Option<String> {
    let module = paths::trim(module).trim_matches(['\'', '"']);
    if !module.starts_with("./") && !module.starts_with("../") {
        return None;
    }
    let joined = paths::join_relative(source, module);
    [joined.clone(), format!("{joined}.rb")]
        .into_iter()
        .find(|p| files.contains(p))
}
fn cpp(module: &str, source: &str, files: &BTreeSet<String>) -> Option<String> {
    if !paths::trim(module).starts_with('"') {
        return None;
    }
    let module = paths::trim(module).trim_matches('"');
    if module.is_empty() {
        return None;
    }
    if module.starts_with("./") || module.starts_with("../") {
        let joined = paths::join_relative(source, module);
        return files.contains(&joined).then_some(joined);
    }
    let matches: Vec<_> = files
        .iter()
        .filter(|p| p.as_str() == module || p.ends_with(&format!("/{module}")))
        .collect();
    if matches.len() == 1 {
        return Some(matches[0].clone());
    }
    if matches.len() > 1 {
        let top = source.split('/').next();
        let matches: Vec<_> = matches
            .into_iter()
            .filter(|p| p.split('/').next() == top)
            .collect();
        if matches.len() == 1 {
            return Some(matches[0].clone());
        }
    }
    None
}
fn kotlin(module: &str, files: &[String]) -> Option<String> {
    let module = paths::trim(paths::trim(module).trim_matches(';'));
    if module.is_empty() || module.ends_with('*') {
        return None;
    }
    let package = module.rsplit_once('.').map_or(module, |(p, _)| p);
    if package.is_empty() {
        return None;
    }
    let package = package.replace('.', "/");
    let matches: Vec<_> = files
        .iter()
        .filter(|p| directory(p) == package || directory(p).ends_with(&format!("/{package}")))
        .collect();
    (matches.len() == 1).then(|| matches[0].clone())
}
fn php(module: &str, mappings: &[(String, String)], files: &BTreeSet<String>) -> Option<String> {
    let module = paths::trim(module)
        .trim_matches(';')
        .trim_start_matches('\\');
    if module.is_empty() {
        return None;
    }
    for (prefix, base) in mappings {
        if let Some(rest) = module.strip_prefix(prefix.trim_start_matches('\\')) {
            let rest = rest.trim_matches('\\').replace('\\', "/");
            let candidate = format!("{base}/{rest}.php").trim_matches('/').to_owned();
            if files.contains(&candidate) {
                return Some(candidate);
            }
        }
    }
    let normalized = module.replace('\\', "/");
    let tail = normalized.rsplit('/').next().unwrap_or("");
    let matches: Vec<_> = files
        .iter()
        .filter(|p| p.ends_with(&format!("/{tail}.php")) || **p == format!("{tail}.php"))
        .collect();
    (matches.len() == 1).then(|| matches[0].clone())
}
fn python_lines(text: &str) -> impl Iterator<Item = &str> {
    let mut parts = Vec::new();
    let mut start = 0;
    for (index, value) in text.match_indices([
        '\n', '\r', '\x0b', '\x0c', '\x1c', '\x1d', '\x1e', '\u{85}', '\u{2028}', '\u{2029}',
    ]) {
        if index < start {
            continue;
        }
        parts.push(&text[start..index]);
        start = index + value.len();
        if value == "\r" && text.as_bytes().get(start) == Some(&b'\n') {
            start += 1;
        }
    }
    if start < text.len() {
        parts.push(&text[start..]);
    }
    parts.into_iter()
}
