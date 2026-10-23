//! Ordered project aliases, inherited bases and workspace package names.
use super::{
    ImportError,
    config::{self, ConfigValue},
    paths,
};
use ken_text::PythonText;
use std::collections::{BTreeMap, BTreeSet};
struct Config {
    directory: String,
    base: PythonText,
    paths: Vec<(String, Vec<PythonText>)>,
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
            let base = &config.base;
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
                    let mut target = target.codepoints().to_vec();
                    if pattern.ends_with('*') {
                        if target.last() == Some(&u32::from('*')) {
                            target.pop();
                        }
                        target.extend(rest.chars().map(u32::from));
                    }
                    let target = PythonText::from_codepoints(target).expect("existing code points");
                    if let Some(target) = norm_path(base, &target).to_utf8()
                        && let Some(found) = paths::match_js_module(&target, files)
                    {
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
    norm_path(&base.into(), &relative.into())
        .to_utf8()
        .expect("scalar path inputs")
}
fn norm_path(base: &PythonText, relative: &PythonText) -> PythonText {
    let mut parts: Vec<Vec<u32>> = base
        .codepoints()
        .split(|&p| p == 47)
        .filter(|p| !p.is_empty())
        .map(<[u32]>::to_vec)
        .collect();
    let relative: Vec<u32> = relative
        .codepoints()
        .iter()
        .map(|&p| if p == 92 { 47 } else { p })
        .collect();
    for part in relative.split(|&p| p == 47) {
        match part {
            [] | [46] => {}
            [46, 46] => {
                parts.pop();
            }
            _ => parts.push(part.to_vec()),
        }
    }
    PythonText::from_codepoints(parts.join(&47)).expect("existing code points")
}
fn path(base: &str, value: &ConfigValue, file: &str) -> Result<PythonText, ImportError> {
    value
        .path_text()
        .map(|v| norm_path(&base.into(), v))
        .ok_or_else(|| ImportError::Config {
            path: file.into(),
            reason: "baseUrl must support string path replacement".into(),
        })
}
fn clean_paths(value: Option<&ConfigValue>) -> Vec<(String, Vec<PythonText>)> {
    value
        .and_then(ConfigValue::object)
        .map_or_else(Vec::new, |values| {
            values
                .iter()
                .filter_map(|(key, value)| {
                    let key = key.clone()?;
                    let targets = match value {
                        ConfigValue::Text(value) => vec![value.points.clone()],
                        ConfigValue::Array(values) => values
                            .iter()
                            .filter_map(ConfigValue::path_text)
                            .cloned()
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
        && let Some(extends) = data.get("extends").and_then(ConfigValue::path_text)
        && let Some(mut parent) = norm_path(&directory.into(), extends).to_utf8()
    {
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
        directory.into()
    };
    Ok(Some(Config {
        directory: directory.into(),
        base,
        paths: clean_paths(paths),
    }))
}
