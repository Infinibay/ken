//! Ordered project aliases, inherited bases and workspace package names.
use super::{
    ImportError,
    config::{self, ConfigValue},
    paths,
};
use std::collections::{BTreeMap, BTreeSet};
struct Config {
    directory: String,
    base: Option<String>,
    paths: Vec<(String, Vec<String>)>,
}
#[derive(Default)]
pub(super) struct AliasResolver {
    configs: Vec<Config>,
    packages: Vec<(String, String)>,
}
impl AliasResolver {
    pub fn from_inputs(
        files: &[String],
        bytes: &BTreeMap<String, Vec<u8>>,
    ) -> Result<Self, ImportError> {
        let mut load = |file: &str| bytes.get(file).cloned();
        Self::from_loader(files, &mut load)
    }
    pub fn from_loader(
        files: &[String],
        load: &mut dyn FnMut(&str) -> Option<Vec<u8>>,
    ) -> Result<Self, ImportError> {
        let mut resolver = Self::default();
        for file in files {
            let (directory, name) = file.rsplit_once('/').unwrap_or(("", file));
            if matches!(name, "tsconfig.json" | "jsconfig.json") {
                if let Some(config) = read_config(file, directory, load, 0)? {
                    resolver.configs.push(config);
                }
            } else if name == "package.json"
                && let Some(value) = load(file).and_then(|b| config::jsonc(&b))
                && let Some(name) = value.get("name").and_then(ConfigValue::text)
            {
                if let Some(existing) = resolver.packages.iter_mut().find(|(key, _)| key == name) {
                    existing.1 = directory.into();
                } else {
                    resolver.packages.push((name.into(), directory.into()));
                }
            }
        }
        resolver
            .configs
            .sort_by_key(|c| std::cmp::Reverse(c.directory.chars().count()));
        Ok(resolver)
    }
    pub fn resolve(&self, module: &str, source: &str, files: &BTreeSet<String>) -> Option<String> {
        let directory = source.rsplit_once('/').map_or("", |(d, _)| d);
        for config in &self.configs {
            if !contains(&config.directory, directory) {
                continue;
            }
            let Some(base) = &config.base else {
                continue;
            };
            for (pattern, targets) in &config.paths {
                let rest = if let Some(prefix) = pattern.strip_suffix('*') {
                    module.strip_prefix(prefix)
                } else {
                    (module == pattern).then_some("")
                };
                let Some(rest) = rest else {
                    continue;
                };
                for target in targets {
                    let target = if pattern.ends_with('*') {
                        target.strip_suffix('*').unwrap_or(target).to_owned() + rest
                    } else {
                        target.clone()
                    };
                    if let Some(found) = paths::match_js_module(&norm_join(base, &target), files) {
                        return Some(found);
                    }
                }
            }
        }
        for (name, package) in &self.packages {
            if module == name
                || module
                    .strip_prefix(name)
                    .is_some_and(|s| s.starts_with('/'))
            {
                let sub = module[name.len()..].trim_start_matches('/');
                let base = if sub.is_empty() {
                    package.clone()
                } else {
                    norm_join(package, sub)
                };
                if let Some(found) = paths::match_js_module(&base, files) {
                    return Some(found);
                }
            }
        }
        None
    }
    pub fn is_internal_shape(&self, module: &str, source: &str) -> bool {
        let directory = source.rsplit_once('/').map_or("", |(d, _)| d);
        self.configs
            .iter()
            .filter(|c| contains(&c.directory, directory))
            .any(|c| {
                c.paths.iter().any(|(pattern, _)| {
                    if let Some(prefix) = pattern.strip_suffix('*') {
                        module.starts_with(prefix)
                    } else {
                        module == pattern
                    }
                })
            })
            || self.packages.iter().any(|(name, _)| {
                module == name
                    || module
                        .strip_prefix(name)
                        .is_some_and(|s| s.starts_with('/'))
            })
    }
}
fn contains(base: &str, directory: &str) -> bool {
    base.is_empty()
        || base == directory
        || directory
            .strip_prefix(base)
            .is_some_and(|s| s.starts_with('/'))
}
pub(super) fn norm_join(base: &str, relative: &str) -> String {
    let mut parts: Vec<String> = base
        .split('/')
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect();
    for part in relative.replace('\\', "/").split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(part.into()),
        }
    }
    parts.join("/")
}
fn path(base: &str, value: &ConfigValue, file: &str) -> Result<Option<String>, ImportError> {
    match value {
        ConfigValue::Text(value) => Ok(value.as_ref().map(|v| norm_join(base, v))),
        _ => Err(ImportError::Config {
            path: file.into(),
            reason: "baseUrl must support string path replacement".into(),
        }),
    }
}
fn clean_paths(value: Option<&ConfigValue>) -> Vec<(String, Vec<String>)> {
    value
        .and_then(ConfigValue::object)
        .map_or_else(Vec::new, |values| {
            values
                .iter()
                .filter_map(|(key, value)| {
                    let key = key.clone()?;
                    let targets = match value {
                        ConfigValue::Text(Some(value)) => vec![value.clone()],
                        ConfigValue::Text(None) => vec![],
                        ConfigValue::Array(values) => values
                            .iter()
                            .filter_map(ConfigValue::text)
                            .map(str::to_owned)
                            .collect(),
                        _ => return None,
                    };
                    Some((key, targets))
                })
                .collect()
        })
}
fn read_config(
    file: &str,
    directory: &str,
    load: &mut dyn FnMut(&str) -> Option<Vec<u8>>,
    depth: usize,
) -> Result<Option<Config>, ImportError> {
    let Some(data) = load(file)
        .and_then(|b| config::jsonc(&b))
        .filter(|v| v.object().is_some())
    else {
        return Ok(None);
    };
    let options = data.get("compilerOptions").filter(|v| v.truth());
    if options.is_some_and(|v| v.object().is_none()) {
        return Err(ImportError::Config {
            path: file.into(),
            reason: "compilerOptions has no dictionary get method".into(),
        });
    }
    let base = options
        .and_then(|o| o.get("baseUrl"))
        .filter(|v| !v.is_null());
    let paths = options
        .and_then(|o| o.get("paths"))
        .filter(|v| !v.is_null());
    if (base.is_none() || paths.is_none())
        && depth < 3
        && let Some(extends) = data.get("extends").and_then(ConfigValue::text)
    {
        let mut parent = norm_join(directory, extends);
        if !parent.ends_with(".json") {
            parent.push_str(".json");
        }
        let parent_dir = parent.rsplit_once('/').map_or("", |(d, _)| d);
        if let Some(parent) = read_config(&parent, parent_dir, load, depth + 1)? {
            let base = if let Some(base) = base {
                path(directory, base, file)?
            } else {
                parent.base
            };
            let paths = if paths.is_some_and(ConfigValue::truth) {
                clean_paths(paths)
            } else {
                parent.paths
            };
            return Ok(Some(Config {
                directory: directory.into(),
                base,
                paths,
            }));
        }
    }
    if !paths.is_some_and(ConfigValue::truth) && base.is_none() {
        return Ok(None);
    }
    let base = if let Some(base) = base.filter(|v| v.truth()) {
        path(directory, base, file)?
    } else {
        Some(directory.into())
    };
    Ok(Some(Config {
        directory: directory.into(),
        base,
        paths: clean_paths(paths),
    }))
}
