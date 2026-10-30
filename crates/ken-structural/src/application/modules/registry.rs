use super::{Result, invalid};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_store::ProjectDatabase;
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RegisteredModule {
    pub module: String,
    pub source: String,
    pub description: String,
    pub revision: String,
    pub queries: Vec<String>,
    pub patterns: Vec<String>,
    pub imports: Vec<String>,
    pub updated_ns: i64,
}
impl RegisteredModule {
    pub fn to_value(&self, include_source: bool) -> Value {
        let mut value = serde_json::to_value(self).unwrap();
        if !include_source {
            value.as_object_mut().unwrap().remove("source");
        }
        value
    }
}
pub fn module_tree(source: &str) -> Result<ken_query::File> {
    if source.is_empty() || source.len() > 100000 {
        return Err(invalid("a KQL2 module of at most 100000 bytes is required"));
    }
    let tree = ken_query::parse(source, "<kql>", ken_query::ParseLimits::default())?;
    if tree.module == "ken.core" || tree.module.starts_with("ken.catalog.") {
        return Err(invalid(format!(
            "reserved KQL2 module namespace: {}",
            tree.module
        )));
    }
    if !tree
        .declarations
        .iter()
        .any(|d| d.kind == "query" || d.kind == "pattern")
    {
        return Err(invalid(
            "a registered module must declare a query or pattern",
        ));
    }
    let mut names = BTreeSet::new();
    if tree.declarations.iter().any(|d| !names.insert(&d.name)) {
        return Err(invalid("duplicate module declaration"));
    }
    Ok(tree)
}
#[derive(Deserialize)]
struct Exports {
    queries: Vec<String>,
    patterns: Vec<String>,
}
fn record(row: &rusqlite::Row<'_>) -> Result<RegisteredModule> {
    let exports: Exports = serde_json::from_str(&row.get::<_, String>("exports")?)?;
    Ok(RegisteredModule {
        module: row.get("module")?,
        source: row.get("source")?,
        description: row.get("description")?,
        revision: row.get("revision")?,
        queries: exports.queries,
        patterns: exports.patterns,
        imports: serde_json::from_str(&row.get::<_, String>("imports")?)?,
        updated_ns: row.get("updated_ns")?,
    })
}
pub(super) fn records(db: &Connection, ordered: bool) -> Result<Vec<RegisteredModule>> {
    let mut statement = db.prepare(if ordered {
        "SELECT * FROM kql_modules ORDER BY module"
    } else {
        "SELECT * FROM kql_modules"
    })?;
    let mut rows = statement.query([])?;
    let mut output = Vec::new();
    while let Some(row) = rows.next()? {
        output.push(record(row)?);
    }
    Ok(output)
}
pub(super) fn root_paths(root: &Path) -> Result<(ProjectPaths, DiscoveryContext)> {
    let context = DiscoveryContext::from_process()?;
    let paths = ProjectPaths::at(root, &context)?;
    if !paths.root().is_dir() {
        return Err(invalid("project root does not exist or is not a directory"));
    }
    Ok((paths, context))
}
pub(super) fn database_path(paths: &ProjectPaths, context: &DiscoveryContext) -> Result<PathBuf> {
    Ok(paths.resolve_inside(Path::new(".ken/ken.db"), context)?)
}
pub struct ModuleRegistry {
    pub root: PathBuf,
    pub path: PathBuf,
    paths: ProjectPaths,
    context: DiscoveryContext,
    packaged: BTreeMap<String, String>,
}
impl ModuleRegistry {
    pub fn new(root: &Path) -> Result<Self> {
        Self::with_packaged(root, BTreeMap::new())
    }
    pub fn with_packaged(root: &Path, packaged: BTreeMap<String, String>) -> Result<Self> {
        let (paths, context) = root_paths(root)?;
        let path = database_path(&paths, &context)?;
        Ok(Self {
            root: paths.root().to_path_buf(),
            path,
            paths,
            context,
            packaged,
        })
    }
    // Retained public paths describe construction; owner paths resolve current
    // storage again before every operation, including initially absent .ken.
    fn current_database_path(&self) -> Result<PathBuf> {
        database_path(&self.paths, &self.context)
    }
    pub fn list_modules(&self) -> Result<Vec<RegisteredModule>> {
        let path = self.current_database_path()?;
        if !path.is_file() {
            return Ok(Vec::new());
        }
        let db = Connection::open_with_flags(
            &path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        db.busy_timeout(Duration::from_secs(5))?;
        let exists = db
            .query_row(
                "SELECT 1 FROM sqlite_master WHERE name='kql_modules'",
                [],
                |r| r.get::<_, i64>(0),
            )
            .optional()?
            .is_some();
        if !exists {
            return Ok(Vec::new());
        }
        records(&db, true)
    }
    pub fn get(&self, module: &str) -> Result<RegisteredModule> {
        self.list_modules()?
            .into_iter()
            .find(|r| r.module == module)
            .ok_or_else(|| invalid(format!("registered KQL2 module not found: {module}")))
    }
    fn validate_imports(&self, source: &str, modules: &[RegisteredModule]) -> Result<()> {
        let modules = modules
            .iter()
            .map(|r| (r.module.clone(), r.clone()))
            .collect::<BTreeMap<_, _>>();
        let mut cache = super::resolver::ParseCache::default();
        super::resolver::resolve_using(
            Some(source),
            None,
            None,
            None,
            &mut |name| Ok(modules.get(name).cloned()),
            &self.packaged,
            &mut cache,
        )?;
        Ok(())
    }
    pub fn save(
        &self,
        source: &str,
        description: Option<&str>,
        expected_revision: Option<&str>,
    ) -> Result<RegisteredModule> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| invalid("system clock precedes Unix epoch"))?
            .as_nanos();
        let now = i64::try_from(now)
            .map_err(|_| invalid("module timestamp exceeds SQLite integer range"))?;
        self.save_at(source, description, expected_revision, now)
    }
    pub fn save_at(
        &self,
        source: &str,
        description: Option<&str>,
        expected_revision: Option<&str>,
        updated_ns: i64,
    ) -> Result<RegisteredModule> {
        let tree = module_tree(source)?;
        if description.is_some_and(|s| s.chars().count() > 2000) {
            return Err(invalid("description must contain at most 2000 characters"));
        }
        self.validate_imports(source, &self.list_modules()?)?;
        let path = self.current_database_path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut database = ProjectDatabase::open(&path)?;
        database.initialize()?;
        let transaction = database.immediate()?;
        let db = transaction.connection();
        let existing = records(db, false)?;
        let old = existing.iter().find(|r| r.module == tree.module);
        if let Some(expected) = expected_revision
            && old.is_none_or(|r| r.revision != expected)
        {
            return Err(invalid("module revision changed; read it before updating"));
        }
        let description = description
            .map(str::to_owned)
            .unwrap_or_else(|| old.map(|r| r.description.clone()).unwrap_or_default());
        if let Some(old) = old {
            if old.source == source && old.description == description {
                let old = old.clone();
                transaction.commit()?;
                return Ok(old);
            }
            if expected_revision.is_none() {
                return Err(invalid(
                    "module already exists; supply its current expected_revision to update",
                ));
            }
        }
        self.validate_imports(source, &existing)?;
        let mut hash = Sha256::new();
        hash.update(source.as_bytes());
        hash.update([0]);
        hash.update(description.as_bytes());
        let registered = RegisteredModule {
            module: tree.module,
            source: source.to_owned(),
            description,
            revision: format!("{:x}", hash.finalize()),
            queries: tree
                .declarations
                .iter()
                .filter(|d| d.kind == "query")
                .map(|d| d.name.clone())
                .collect(),
            patterns: tree
                .declarations
                .iter()
                .filter(|d| d.kind == "pattern")
                .map(|d| d.name.clone())
                .collect(),
            imports: tree.imports,
            updated_ns,
        };
        db.execute("INSERT INTO kql_modules VALUES(?,?,?,?,?,?,?) ON CONFLICT(module) DO UPDATE SET source=excluded.source,description=excluded.description,revision=excluded.revision,exports=excluded.exports,imports=excluded.imports,updated_ns=excluded.updated_ns",params![registered.module,registered.source,registered.description,registered.revision,serde_json::to_string(&json!({"queries":registered.queries,"patterns":registered.patterns}))?,serde_json::to_string(&registered.imports)?,registered.updated_ns])?;
        transaction.commit()?;
        Ok(registered)
    }
    pub fn delete(&self, module: &str, expected_revision: Option<&str>) -> Result<()> {
        self.get(module)?;
        let path = self.current_database_path()?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut database = ProjectDatabase::open(&path)?;
        database.initialize()?;
        let transaction = database.immediate()?;
        let db = transaction.connection();
        let existing = records(db, false)?;
        let current = existing
            .iter()
            .find(|r| r.module == module)
            .ok_or_else(|| invalid(format!("registered KQL2 module not found: {module}")))?;
        if expected_revision.is_some_and(|expected| current.revision != expected) {
            return Err(invalid("module revision changed; read it before deleting"));
        }
        let users = existing
            .iter()
            .filter(|r| r.module != module && r.imports.iter().any(|i| i == module))
            .map(|r| r.module.as_str())
            .collect::<Vec<_>>();
        if !users.is_empty() {
            return Err(invalid(format!(
                "module is imported by: {}",
                users.join(", ")
            )));
        }
        db.execute("DELETE FROM kql_modules WHERE module=?", [module])?;
        transaction.commit()?;
        Ok(())
    }
}
