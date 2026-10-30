use super::{ModuleError, RegisteredModule, RegistryReader, RegistrySnapshot, Result, invalid};
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::{Path, PathBuf},
    sync::Arc,
};
#[derive(Clone, Debug, Serialize)]
pub struct ResolvedQuery {
    pub source: String,
    pub query_name: Option<String>,
    libraries: BTreeMap<String, String>,
    revisions: BTreeMap<String, String>,
}
impl ResolvedQuery {
    pub fn libraries(&self) -> &BTreeMap<String, String> {
        &self.libraries
    }
    pub fn revisions(&self) -> &BTreeMap<String, String> {
        &self.revisions
    }
    pub fn annotate(&self, result: &mut Value) -> Result<()> {
        if self.revisions.is_empty() {
            return Ok(());
        }
        let result = result
            .as_object_mut()
            .ok_or_else(|| invalid("query result must be an object"))?;
        let analysis = result.entry("analysis").or_insert(json!({}));
        let analysis = analysis
            .as_object_mut()
            .ok_or_else(|| invalid("query analysis must be an object"))?;
        analysis.insert("registry_modules".into(), json!(self.revisions));
        Ok(())
    }
}
#[derive(Default)]
pub(super) struct ParseCache {
    entries: VecDeque<(String, Arc<ken_query::File>)>,
}
impl ParseCache {
    fn tree(&mut self, source: &str) -> Result<Arc<ken_query::File>> {
        if let Some(position) = self.entries.iter().position(|(text, _)| text == source) {
            let entry = self.entries.remove(position).unwrap();
            let tree = entry.1.clone();
            self.entries.push_back(entry);
            return Ok(tree);
        }
        let tree = Arc::new(ken_query::parse(
            source,
            "<query>",
            ken_query::ParseLimits::default(),
        )?);
        if self.entries.len() >= 128 {
            self.entries.pop_front();
        }
        self.entries.push_back((source.to_owned(), tree.clone()));
        Ok(tree)
    }
}
pub fn validate_entry(source: Option<&str>, saved_query: Option<&str>) -> Result<()> {
    if source.is_some_and(|s| !s.is_empty()) == saved_query.is_some_and(|s| !s.is_empty()) {
        Err(invalid(
            "provide either query source or saved_query, not both",
        ))
    } else {
        Ok(())
    }
}
#[allow(clippy::too_many_arguments)]
pub(super) fn resolve_using(
    source: Option<&str>,
    saved_query: Option<&str>,
    query_name: Option<&str>,
    supplied: Option<&BTreeMap<String, String>>,
    lookup: &mut dyn FnMut(&str) -> Result<Option<RegisteredModule>>,
    packaged: &BTreeMap<String, String>,
    parsed: &mut ParseCache,
) -> Result<ResolvedQuery> {
    validate_entry(source, saved_query)?;
    let mut revisions = BTreeMap::new();
    let source = if let Some(saved) = saved_query.filter(|s| !s.is_empty()) {
        let record = lookup(saved)?
            .ok_or_else(|| invalid(format!("registered KQL2 module not found: {saved}")))?;
        if record.queries.is_empty() {
            return Err(invalid(format!(
                "registered module has no executable query: {saved}"
            )));
        }
        if let Some(query) = query_name
            && !record.queries.iter().any(|q| q == query)
        {
            return Err(invalid(format!(
                "query not declared in registered module: {query}"
            )));
        }
        revisions.insert(record.module, record.revision);
        record.source
    } else {
        source.unwrap_or("").to_owned()
    };
    let mut libraries = supplied.cloned().unwrap_or_default();
    if !source.contains("import") {
        return Ok(ResolvedQuery {
            source,
            query_name: query_name.map(str::to_owned),
            libraries,
            revisions,
        });
    }
    let entry = parsed.tree(&source)?;
    let mut visited = BTreeSet::from([entry.module.clone(), "ken.core".into()]);
    let mut pending = entry.imports.clone();
    while let Some(name) = pending.pop() {
        if !visited.insert(name.clone()) {
            continue;
        }
        let text = if let Some(text) = libraries.get(&name) {
            text.clone()
        } else if let Some(text) = packaged
            .get(&name)
            .filter(|_| name.starts_with("ken.catalog."))
        {
            text.clone()
        } else {
            let record =
                lookup(&name)?.ok_or_else(|| invalid(format!("missing library module: {name}")))?;
            revisions.insert(name.clone(), record.revision);
            record.source
        };
        let tree = parsed.tree(&text)?;
        if tree.module != name {
            return Err(invalid(format!("mismatched library module: {name}")));
        }
        libraries.insert(name, text);
        pending.extend(tree.imports.iter().cloned());
    }
    Ok(ResolvedQuery {
        source,
        query_name: query_name.map(str::to_owned),
        libraries,
        revisions,
    })
}
pub struct ModuleResolver {
    root: PathBuf,
    reader: Option<RegistryReader>,
    closed: bool,
    packaged: BTreeMap<String, String>,
    parsed: ParseCache,
}
impl ModuleResolver {
    pub fn new(root: &Path, packaged: BTreeMap<String, String>) -> Self {
        Self {
            root: root.to_path_buf(),
            reader: None,
            closed: false,
            packaged,
            parsed: ParseCache::default(),
        }
    }
    pub fn resolve(
        &mut self,
        source: Option<&str>,
        saved_query: Option<&str>,
        query_name: Option<&str>,
        libraries: Option<&BTreeMap<String, String>>,
    ) -> Result<ResolvedQuery> {
        if self.closed {
            return Err(ModuleError::Owner("module resolver is closed".into()));
        }
        let mut snapshot: Option<Arc<RegistrySnapshot>> = None;
        let reader = &mut self.reader;
        let root = &self.root;
        let mut lookup = |name: &str| -> Result<Option<RegisteredModule>> {
            if snapshot.is_none() {
                if reader.is_none() {
                    *reader = Some(RegistryReader::new(root)?);
                }
                snapshot = Some(reader.as_mut().unwrap().snapshot()?);
            }
            Ok(snapshot.as_ref().unwrap().modules().get(name).cloned())
        };
        resolve_using(
            source,
            saved_query,
            query_name,
            libraries,
            &mut lookup,
            &self.packaged,
            &mut self.parsed,
        )
    }
    pub fn close(&mut self) -> Result<()> {
        if let Some(reader) = self.reader.as_mut() {
            reader.close()?;
        }
        self.closed = true;
        Ok(())
    }
}
