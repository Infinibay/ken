use super::{InspectionSources, Result, invalid, qualname};
use ken_core::imports::ImportCatalog;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    time::{Duration, Instant},
};
pub(super) struct ImportPlanner<'a> {
    root: &'a Path,
    paths: BTreeSet<String>,
    pub edges: BTreeMap<String, BTreeSet<String>>,
    pub issues: Vec<Value>,
    names: BTreeMap<(String, String), Option<BTreeSet<String>>>,
    spellings: BTreeMap<String, BTreeSet<String>>,
    sources: &'a mut dyn InspectionSources,
    deadline: Instant,
    catalog: ImportCatalog,
}
impl<'a> ImportPlanner<'a> {
    pub fn new(
        root: &'a Path,
        paths: BTreeSet<String>,
        sources: &'a mut dyn InspectionSources,
        deadline: Instant,
    ) -> Result<Self> {
        let catalog = ImportCatalog::from_inputs(paths.iter().cloned().collect(), None)
            .map_err(|e| invalid(e.to_string()))?;
        Ok(Self {
            root,
            paths,
            edges: BTreeMap::new(),
            issues: Vec::new(),
            names: BTreeMap::new(),
            spellings: BTreeMap::new(),
            sources,
            deadline,
            catalog,
        })
    }
    pub fn capture(&mut self, scope: &str, budget: Duration) -> Result<Value> {
        self.sources.capture(self.root, scope, budget)
    }
    fn time(&self) -> Result<Duration> {
        self.sources.checkpoint()?;
        self.deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or_else(|| invalid("import discovery time budget exhausted"))
    }
    pub fn read(&mut self, path: &str) -> Result<BTreeSet<String>> {
        self.time()?;
        if let Some(targets) = self.edges.get(path) {
            return Ok(targets.clone());
        }
        self.edges.insert(path.into(), BTreeSet::new());
        let outcome = (|| -> Result<BTreeSet<String>> {
            let budget = self.time()?;
            let facts = self.sources.facts(self.root, path, budget)?;
            let mut targets = BTreeSet::new();
            if path.ends_with(".py") {
                self.spellings.insert(path.into(), facts.spellings.clone());
                let mut modules = Vec::new();
                for import in facts.imports {
                    if import.kind == "import" {
                        for alias in import.aliases {
                            modules.push((alias.name, import.line, None));
                        }
                    } else {
                        let names = if import.aliases.iter().any(|a| a.name == "*") {
                            None
                        } else {
                            Some(
                                import
                                    .aliases
                                    .iter()
                                    .map(|a| a.name.clone())
                                    .collect::<BTreeSet<_>>(),
                            )
                        };
                        modules.push((import.module.clone(), import.line, names));
                        for alias in import.aliases.iter().filter(|a| a.name != "*") {
                            modules.push((
                                format!(
                                    "{}{}{}",
                                    import.module,
                                    if import.module.chars().any(|c| c != '.') {
                                        "."
                                    } else {
                                        ""
                                    },
                                    alias.name
                                ),
                                import.line,
                                None,
                            ));
                        }
                    }
                }
                for (module, line, imported) in modules {
                    let found = ken_program::python_module_targets(path, &module, &self.paths);
                    targets.extend(found.iter().cloned());
                    for destination in &found {
                        let key = (path.into(), destination.clone());
                        let previous = self
                            .names
                            .get(&key)
                            .cloned()
                            .unwrap_or(Some(BTreeSet::new()));
                        self.names.insert(
                            key,
                            match (previous, imported.clone()) {
                                (Some(mut a), Some(b)) => {
                                    a.extend(b);
                                    Some(a)
                                }
                                _ => None,
                            },
                        );
                    }
                    if found.len() > 1 {
                        self.issues.push(json!({"path":path,"line":line,"module":module,"reason":"ambiguous import; include all candidates"}));
                    }
                }
                self.issues.extend(facts.issues);
                Ok(targets)
            } else {
                for import in facts.imports {
                    for alias in import.aliases {
                        if let Some(target) =
                            self.catalog.structural_target(&alias.name, Some(path))
                        {
                            targets.insert(target);
                        }
                    }
                }
                self.edges.insert(path.into(), targets);
                Err(invalid(
                    "implicit/package imports require full-scope analysis",
                ))
            }
        })();
        match outcome {
            Ok(targets) => {
                self.edges.insert(path.into(), targets.clone());
                Ok(targets)
            }
            Err(e) => {
                self.issues.push(json!({"path":path,"reason":e.to_string().chars().take(180).collect::<String>()}));
                Ok(self.edges.get(path).cloned().unwrap_or_default())
            }
        }
    }
    pub fn neighbors(
        &mut self,
        nodes: &[Value],
        incoming: bool,
        outgoing: bool,
    ) -> Result<BTreeSet<String>> {
        let seeds = nodes
            .iter()
            .filter_map(|n| n["path"].as_str())
            .map(str::to_owned)
            .collect::<BTreeSet<_>>();
        let mut selected = seeds.clone();
        if outgoing {
            for path in &seeds {
                selected.extend(self.read(path)?);
            }
        }
        if incoming {
            for path in self.paths.clone() {
                let destinations = self.read(&path)?;
                for node in nodes {
                    let Some(target) = node["path"].as_str() else {
                        continue;
                    };
                    if !destinations.contains(target) {
                        continue;
                    }
                    let names = self
                        .names
                        .get(&(path.clone(), target.into()))
                        .cloned()
                        .unwrap_or(None);
                    let name = qualname(node).split('.').next().unwrap_or("").to_owned();
                    if names.is_none()
                        && self
                            .spellings
                            .get(&path)
                            .is_some_and(|s| !s.contains(&name))
                    {
                        continue;
                    }
                    if names.is_none_or(|names| names.contains(&name)) {
                        selected.insert(path.clone());
                    }
                }
            }
        }
        Ok(if self.issues.is_empty() {
            selected
        } else {
            self.paths.clone()
        })
    }
    pub fn closure(
        &mut self,
        seeds: &BTreeSet<String>,
        incoming: bool,
        depth: usize,
    ) -> Result<BTreeSet<String>> {
        if incoming {
            for path in self.paths.clone() {
                self.read(&path)?;
            }
        }
        let mut seen = seeds.clone();
        let mut frontier = seeds.clone();
        for _ in 0..depth {
            let mut added = BTreeSet::new();
            if incoming {
                for (path, targets) in &self.edges {
                    if targets.iter().any(|t| frontier.contains(t)) {
                        added.insert(path.clone());
                    }
                }
            } else {
                for path in &frontier {
                    added.extend(self.read(path)?);
                }
            }
            frontier = added.difference(&seen).cloned().collect();
            seen.extend(added);
            if frontier.is_empty() {
                break;
            }
        }
        if !frontier.is_empty() {
            self.issues
                .push(json!({"reason":"import traversal depth exhausted"}));
        }
        Ok(if self.issues.is_empty() {
            seen
        } else {
            self.paths.clone()
        })
    }
}
fn manifest(snapshot: &Value) -> Result<BTreeMap<String, String>> {
    snapshot["manifest"]
        .as_array()
        .ok_or_else(|| invalid("source inventory unavailable"))?
        .iter()
        .map(|p| {
            Ok((
                p[0].as_str()
                    .ok_or_else(|| invalid("invalid source path"))?
                    .to_owned(),
                p[1].as_str()
                    .ok_or_else(|| invalid("invalid source fingerprint"))?
                    .to_owned(),
            ))
        })
        .collect()
}
pub fn select_sources(
    root: &Path,
    snapshot: &Value,
    seeds: &[String],
    incoming: bool,
    sources: &mut dyn InspectionSources,
    budget: Duration,
) -> Result<Value> {
    let paths = manifest(snapshot)?.into_keys().collect::<BTreeSet<_>>();
    let starts = paths
        .iter()
        .filter(|p| {
            seeds
                .iter()
                .any(|s| *p == s || p.starts_with(&(s.trim_end_matches('/').to_owned() + "/")))
        })
        .cloned()
        .collect::<BTreeSet<_>>();
    let deadline = Instant::now()
        .checked_add(budget)
        .ok_or_else(|| invalid("source selection budget out of range"))?;
    let mut imports = ImportPlanner::new(root, paths, sources, deadline)?;
    let mut selected = imports.closure(&starts, false, 8)?;
    if incoming {
        selected.extend(imports.closure(&starts, true, 8)?);
    }
    Ok(
        json!({"paths":selected,"issues":imports.issues,"basis":"explicit imports; unresolved acquisition falls back to supplied scope"}),
    )
}
pub fn dependencies(
    root: &Path,
    snapshot: &Value,
    sources: &mut dyn InspectionSources,
    budget: Duration,
) -> Result<Value> {
    if snapshot["scope"] == "." {
        return Ok(json!({"manifest":[],"imports":[]}));
    }
    let start = Instant::now();
    let full = sources.capture(root, ".", budget)?;
    let mut all = manifest(&full)?;
    all.retain(|path, _| {
        path.rsplit('.').next().is_some_and(|e| {
            [
                "py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "java", "cs", "cpp", "hpp",
                "cc", "go", "rs", "rb", "rake", "gemspec",
            ]
            .contains(&e)
        })
    });
    if all.len() > 4000 {
        return Err(invalid("import dependency inventory budget exhausted"));
    }
    let seeds = manifest(snapshot)?.into_keys().collect::<BTreeSet<_>>();
    let deadline = start
        .checked_add(budget)
        .ok_or_else(|| invalid("source selection budget out of range"))?;
    let mut imports = ImportPlanner::new(root, all.keys().cloned().collect(), sources, deadline)?;
    let closure = imports.closure(&seeds, false, 8)?;
    let entries = closure
        .difference(&seeds)
        .filter_map(|p| all.get(p).map(|h| json!([p, h])))
        .collect::<Vec<_>>();
    Ok(
        json!({"manifest":entries,"imports":imports.edges.iter().map(|(path,targets)|json!([path,targets])).collect::<Vec<_>>(),"issues":imports.issues}),
    )
}
