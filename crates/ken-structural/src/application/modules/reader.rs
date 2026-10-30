use super::{ModuleError, RegisteredModule, Result, registry};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::Arc,
    thread::{self, ThreadId},
    time::Duration,
};
#[derive(Clone, Debug)]
pub struct RegistrySnapshot {
    pub generation: i64,
    modules: BTreeMap<String, RegisteredModule>,
}
impl RegistrySnapshot {
    fn empty() -> Self {
        Self {
            generation: -1,
            modules: BTreeMap::new(),
        }
    }
    pub fn modules(&self) -> &BTreeMap<String, RegisteredModule> {
        &self.modules
    }
    pub fn to_value(&self, include_source: bool) -> Value {
        json!({"generation":self.generation,"modules":self.modules.iter().map(|(name,module)|(name,module.to_value(include_source))).collect::<BTreeMap<_,_>>()})
    }
}
#[derive(Debug, PartialEq, Eq)]
struct Identity {
    path: PathBuf,
    device: u64,
    inode: u64,
}
fn identity(path: &Path) -> Result<Option<Identity>> {
    use std::os::unix::fs::MetadataExt;
    match path.metadata() {
        Ok(m) => Ok(Some(Identity {
            path: path.to_path_buf(),
            device: m.dev(),
            inode: m.ino(),
        })),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}
pub struct RegistryReader {
    paths: ProjectPaths,
    context: DiscoveryContext,
    owner_pid: u32,
    owner_thread: ThreadId,
    closed: bool,
    db: Option<Connection>,
    identity: Option<Identity>,
    cached: Arc<RegistrySnapshot>,
}
impl RegistryReader {
    pub fn new(root: &Path) -> Result<Self> {
        let (paths, context) = registry::root_paths(root)?;
        registry::database_path(&paths, &context)?;
        Ok(Self {
            paths,
            context,
            owner_pid: std::process::id(),
            owner_thread: thread::current().id(),
            closed: false,
            db: None,
            identity: None,
            cached: Arc::new(RegistrySnapshot::empty()),
        })
    }
    fn owned(&self) -> bool {
        self.owner_pid == std::process::id() && self.owner_thread == thread::current().id()
    }
    pub fn snapshot(&mut self) -> Result<Arc<RegistrySnapshot>> {
        if self.closed || !self.owned() {
            return Err(ModuleError::Owner(
                "registry readers belong to their open owner process and thread".into(),
            ));
        }
        let path = registry::database_path(&self.paths, &self.context)?;
        let current = identity(&path)?;
        if current != self.identity {
            self.db = None;
            self.identity = None;
            self.cached = Arc::new(RegistrySnapshot::empty());
        }
        if current.is_none() {
            return Ok(self.cached.clone());
        }
        if self.db.is_none() {
            let db = Connection::open_with_flags(
                &path,
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            )?;
            db.busy_timeout(Duration::ZERO)?;
            self.db = Some(db);
            self.identity = current;
        }
        let db = self.db.as_ref().unwrap();
        let exists = db
            .query_row(
                "SELECT 1 FROM sqlite_master WHERE name='kql_registry_state'",
                [],
                |r| r.get::<_, i64>(0),
            )
            .optional()?
            .is_some();
        if !exists {
            self.cached = Arc::new(RegistrySnapshot::empty());
            return Ok(self.cached.clone());
        }
        let generation = db
            .query_row(
                "SELECT generation FROM kql_registry_state WHERE singleton=1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .optional()?
            .unwrap_or(0);
        if generation == self.cached.generation {
            return Ok(self.cached.clone());
        }
        db.execute_batch("BEGIN")?;
        let result = (|| {
            let generation = db.query_row(
                "SELECT generation FROM kql_registry_state WHERE singleton=1",
                [],
                |r| r.get::<_, i64>(0),
            )?;
            let modules = registry::records(db, false)?
                .into_iter()
                .map(|r| (r.module.clone(), r))
                .collect();
            Ok::<_, super::ModuleError>(RegistrySnapshot {
                generation,
                modules,
            })
        })();
        let rolled_back = db.execute_batch("ROLLBACK");
        let snapshot = result?;
        rolled_back?;
        self.cached = Arc::new(snapshot);
        Ok(self.cached.clone())
    }
    pub fn close(&mut self) -> Result<()> {
        if !self.owned() {
            return Err(ModuleError::Owner(
                "registry readers belong to their creating process and thread".into(),
            ));
        }
        self.db = None;
        self.closed = true;
        Ok(())
    }
}
