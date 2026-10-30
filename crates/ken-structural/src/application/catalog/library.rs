//! Visible rule definitions reserve public aliases and prepare one immutable registry.
use super::compilation::Compilation;
use super::*;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_query::relational::{PlanValue, RelationalNode, RelationalQuery, Term};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};
pub struct RuleLibrary {
    pub(super) rules: Vec<SavedRule>,
    queries: BTreeMap<String, Arc<RelationalQuery>>,
    catalog: Catalog,
}
impl RuleLibrary {
    pub fn packaged(catalog: &Catalog) -> Result<Self> {
        let rules = catalog.rules.clone();
        let queries = build_queries(&rules, catalog)?;
        Ok(Self {
            rules,
            queries,
            catalog: catalog.clone(),
        })
    }
    pub fn load(root: &Path, catalog: &Catalog, files: &[PathBuf]) -> Result<Self> {
        let context = DiscoveryContext::from_process()?;
        let paths = ProjectPaths::at(root, &context)?;
        let mut selected = vec![];
        let local = paths.resolve_inside(Path::new(".ken/rules.json"), &context)?;
        if local.exists() {
            selected.push(local);
        }
        let directory = paths.resolve_inside(Path::new(".ken/rules"), &context)?;
        if directory.is_dir() {
            let mut files = std::fs::read_dir(&directory)?
                .map(|e| e.map(|e| e.path()))
                .collect::<std::io::Result<Vec<_>>>()?;
            files.sort();
            for path in files {
                if path.extension().is_some_and(|s| s == "toml") {
                    selected.push(paths.resolve_inside(&path, &context)?);
                }
            }
        }
        for path in files {
            let path = paths.resolve_inside(path, &context)?;
            if !selected.contains(&path) {
                selected.push(path);
            }
        }
        let mut rules = catalog.rules.clone();
        let mut reserved = BTreeSet::new();
        for rule in &rules {
            reserved.insert(rule.id.clone());
            if rule.collections.iter().any(|c| c == "gof") {
                reserved.insert(format!("legacy.gof.{}", rule.id));
                reserved.insert(format!("gof.{}", rule.id));
            }
            for variant in &rule.variants {
                if let Some(id) = variant["id"].as_str() {
                    reserved.insert(format!("{}#{id}", rule.id));
                    reserved.insert(format!("gof.{}#{id}", rule.id));
                }
            }
        }
        for path in selected {
            for rule in read_rules(&paths, &path)? {
                if !reserved.insert(rule.id.clone()) {
                    return Err(invalid(format!(
                        "duplicate rule id: {}; use a distinct id instead of shadowing a rule",
                        rule.id
                    )));
                }
                rules.push(rule);
            }
        }
        let queries = build_queries(&rules, catalog)?;
        Ok(Self {
            rules,
            queries,
            catalog: catalog.clone(),
        })
    }
    pub fn rules(&self) -> &[SavedRule] {
        &self.rules
    }
    pub fn queries(&self) -> Result<&BTreeMap<String, Arc<RelationalQuery>>> {
        Ok(&self.queries)
    }
    pub fn select(
        &self,
        ids: &[String],
        collections: &[String],
        tags: &[String],
    ) -> Result<Vec<SavedRule>> {
        for (label, requested, known) in [
            (
                "rule",
                ids,
                self.rules
                    .iter()
                    .map(|r| r.id.clone())
                    .collect::<BTreeSet<_>>(),
            ),
            (
                "collection",
                collections,
                self.rules
                    .iter()
                    .flat_map(|r| r.collections.clone())
                    .collect(),
            ),
            (
                "tag",
                tags,
                self.rules.iter().flat_map(|r| r.tags.clone()).collect(),
            ),
        ] {
            let unknown: BTreeSet<_> = requested
                .iter()
                .filter(|id| !known.contains(*id))
                .cloned()
                .collect();
            if !unknown.is_empty() {
                return Err(invalid(format!(
                    "unknown {label}: {}",
                    unknown.into_iter().collect::<Vec<_>>().join(", ")
                )));
            }
        }
        Ok(self
            .rules
            .iter()
            .filter(|r| {
                (ids.is_empty() || ids.contains(&r.id))
                    && (collections.is_empty()
                        || r.collections.iter().any(|c| collections.contains(c)))
                    && (tags.is_empty() || r.tags.iter().any(|t| tags.contains(t)))
            })
            .cloned()
            .collect())
    }
    pub fn named(&self, id: &str) -> Result<Arc<RelationalQuery>> {
        let query = self
            .queries
            .get(id)
            .ok_or_else(|| invalid(format!("unknown or unavailable named query: {id}")))?;
        let bindings = query
            .exports
            .items()
            .iter()
            .map(|(name, _)| {
                (
                    name.clone(),
                    PlanValue::Term(Term::Text(format!("${name}"))),
                )
            })
            .collect();
        let node = RelationalNode {
            kind: "match".into(),
            value: PlanValue::Tuple(vec![
                PlanValue::Term(Term::Text(id.into())),
                PlanValue::Map(bindings),
                PlanValue::Term(Term::Text(String::new())),
            ]),
            children: vec![],
        };
        Ok(reachable(RelationalQuery {
            name: "selected".into(),
            nodes: Arc::new(vec![node]),
            exports: query
                .exports
                .items()
                .iter()
                .map(|(name, _)| (name.clone(), format!("${name}")))
                .collect(),
            definitions: self
                .queries
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        }))
    }
    pub fn inline(&self, source: &str) -> Result<Arc<RelationalQuery>> {
        let mut plan = (*Compilation::new(&self.catalog).query(source)?).clone();
        let mut definitions = self.queries.clone();
        for (k, v) in plan.definitions.items() {
            definitions.insert(k.clone(), v.clone());
        }
        plan.definitions = definitions.into_iter().collect();
        Ok(reachable(plan))
    }
    pub fn save(&self, root: &Path, rule: &SavedRule, overwrite: bool) -> Result<PathBuf> {
        let mut compiled = Compilation::new(&self.catalog);
        rule.validate(&mut compiled)?;
        super::publication::save(root, rule, overwrite, &self.catalog)
    }
}
// A catalog is a registry of independent entry points, not one executable plan.
// Only the selected dependency closure consumes runtime plan-validation work.
fn reachable(mut plan: RelationalQuery) -> Arc<RelationalQuery> {
    let registry = plan
        .definitions
        .items()
        .iter()
        .map(|(name, query)| (name.clone(), query.clone()))
        .collect::<BTreeMap<_, _>>();
    let mut selected = BTreeMap::new();
    let mut pending = plan.dependencies();
    let mut seen = BTreeSet::new();
    while let Some((name, _)) = pending.pop() {
        if !seen.insert(name.clone()) {
            continue;
        }
        if let Some(query) = registry.get(&name) {
            pending.extend(query.dependencies());
            selected.insert(name, query.clone());
        }
    }
    plan.definitions = selected.into_iter().collect();
    Arc::new(plan)
}
fn read_rules(paths: &ProjectPaths, path: &Path) -> Result<Vec<SavedRule>> {
    let bytes = ken_core::source_reader::SourceFileReader::new(paths)?
        .open(path)?
        .read_bounded(16_000_000)?
        .ok_or_else(|| invalid("rule document exceeds 16 MB"))?;
    let mut data: Value = if path.extension().is_some_and(|s| s == "toml") {
        let data: toml::Value = toml::from_str(
            std::str::from_utf8(&bytes).map_err(|_| invalid("rule document is not UTF-8"))?,
        )?;
        serde_json::to_value(data)?
    } else {
        serde_json::from_slice(&bytes)?
    };
    if path.extension().is_some_and(|s| s == "toml") && data.get("id").is_some() {
        data = json!({"version":1,"rules":[data]});
    }
    if !data.is_object()
        || data["version"].as_i64() != Some(1)
        || !data["version"].is_number()
        || !data["rules"].is_array()
    {
        return Err(invalid(format!(
            "{}: expected version 1 and a rules array",
            path.display()
        )));
    }
    let mut seen = BTreeSet::new();
    let mut rules = vec![];
    for item in data["rules"].as_array().unwrap() {
        let rule: SavedRule = serde_json::from_value(item.clone())?;
        if !seen.insert(rule.id.clone()) {
            return Err(invalid(format!("duplicate rule id: {}", rule.id)));
        }
        rules.push(rule);
    }
    Ok(rules)
}
pub(super) fn build_queries(
    rules: &[SavedRule],
    catalog: &Catalog,
) -> Result<BTreeMap<String, Arc<RelationalQuery>>> {
    let mut compiled = Compilation::new(catalog);
    let mut queries = BTreeMap::new();
    for rule in rules {
        rule.validate(&mut compiled)?;
        if let Some(source) = catalog
            .sources()
            .iter()
            .find(|s| s.path == rule.source && s.path.starts_with("patterns/"))
        {
            let data: toml::Value = toml::from_str(source.text)?;
            if let Some(old) = data
                .get("legacy_query")
                .and_then(toml::Value::as_str)
                .filter(|s| !s.is_empty())
            {
                queries.insert(
                    format!("legacy.gof.{}", rule.id),
                    Arc::new(ken_query::legacy_blocks::legacy_query(old, &rule.id)?),
                );
            }
        }
        let query = if super::compilation::block(&rule.query) {
            compiled.query(&rule.query)?
        } else {
            Arc::new(ken_query::legacy_blocks::legacy_query(
                &rule.query,
                &rule.id,
            )?)
        };
        queries.insert(rule.id.clone(), query.clone());
        let gof = rule.collections.iter().any(|c| c == "gof");
        if gof {
            queries.insert(format!("gof.{}", rule.id), query);
        }
        for variant in &rule.variants {
            if variant["status"] == "ready" {
                let id = variant["id"].as_str().unwrap();
                let query = compiled.query(variant["query"].as_str().unwrap())?;
                queries.insert(format!("{}#{id}", rule.id), query.clone());
                if gof {
                    queries.insert(format!("gof.{}#{id}", rule.id), query);
                }
            }
        }
    }
    for rule in rules {
        for operation in &rule.operations {
            if operation["status"] != "ready" {
                continue;
            }
            let name = format!("{}.{}", rule.id, operation["id"].as_str().unwrap());
            if queries.contains_key(&name) {
                return Err(invalid(format!("duplicate named query: {name}")));
            }
            queries.insert(name, compiled.query(operation["query"].as_str().unwrap())?);
        }
    }
    for rule in rules {
        if !rule.collections.iter().any(|c| c == "gof")
            || rule.query.trim_start().starts_with("language \"kql/2\"")
        {
            continue;
        }
        let ready = rule
            .variants
            .iter()
            .filter(|v| v["status"] == "ready")
            .collect::<Vec<_>>();
        if ready.is_empty() {
            continue;
        }
        let mut common: Option<BTreeSet<String>> = None;
        for variant in &ready {
            let q = compiled.query(variant["query"].as_str().unwrap())?;
            let roles: BTreeSet<_> = q
                .exports
                .items()
                .iter()
                .map(|(name, _)| name.clone())
                .collect();
            if let Some(common) = &mut common {
                common.retain(|r| roles.contains(r));
            } else {
                common = Some(roles);
            }
        }
        let common = common.unwrap();
        if common.is_empty() {
            return Err(invalid(format!(
                "rule {}: ready variants need common exported roles",
                rule.id
            )));
        }
        let exports: ken_query::relational::OrderedMap<_> = common
            .into_iter()
            .map(|r| {
                let var = format!("${r}");
                (r, var)
            })
            .collect();
        let branches = ready
            .iter()
            .map(|v| {
                vec![RelationalNode {
                    kind: "match".into(),
                    value: PlanValue::Tuple(vec![
                        PlanValue::Term(Term::Text(format!(
                            "{}#{}",
                            rule.id,
                            v["id"].as_str().unwrap()
                        ))),
                        PlanValue::Map(
                            exports
                                .items()
                                .iter()
                                .map(|(k, v)| (k.clone(), PlanValue::Term(Term::Text(v.clone()))))
                                .collect(),
                        ),
                        PlanValue::Term(Term::Text(String::new())),
                    ]),
                    children: vec![],
                }]
            })
            .collect();
        queries.insert(
            format!("gof.{}", rule.id),
            Arc::new(RelationalQuery {
                name: format!("gof.{}", rule.id),
                nodes: Arc::new(vec![RelationalNode {
                    kind: "any".into(),
                    value: PlanValue::None,
                    children: branches,
                }]),
                exports,
                definitions: Default::default(),
            }),
        );
    }
    let dependencies = queries
        .values()
        .flat_map(|q| {
            q.definitions
                .items()
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
        })
        .collect::<Vec<_>>();
    queries.extend(dependencies);
    Ok(queries)
}
