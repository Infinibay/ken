//! All scenario writes stay under one disposable owned directory.
#[path = "owned_files.rs"]
mod owned_files;
use super::{Result, invalid};
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage,
    source_catalog::SourceCatalog,
    source_snapshot::{SourceAuthority, SourceError, SourceResult},
};
use owned_files::OwnedFiles;
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
    sync::Arc,
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Physical {
    pub files: BTreeMap<String, Vec<u8>>,
    pub owners: Vec<Owner>,
    #[serde(default)]
    pub symlinks: Vec<Link>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Owner {
    pub key: EntityKey,
    pub passages: Vec<Passage>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Link {
    pub path: String,
    pub target: String,
}
fn source_invalid(message: impl Into<String>) -> SourceError {
    SourceError::Invalid(message.into())
}
pub struct Scenario {
    _owned: tempfile::TempDir,
    files: OwnedFiles,
    pub root: PathBuf,
    pub source: Arc<SourceAuthority>,
}
fn confined(base: &Path, path: &Path, owned: &Path) -> Result<PathBuf> {
    if path.is_absolute() || path.as_os_str().is_empty() {
        return Err(invalid("scenario path must be relative and owned"));
    }
    let mut output = base.to_owned();
    for component in path.components() {
        match component {
            Component::Normal(name) => output.push(name),
            Component::CurDir => {}
            Component::ParentDir => {
                if output == owned || !output.pop() {
                    return Err(invalid("scenario path escapes owned root"));
                }
            }
            _ => return Err(invalid("invalid scenario component")),
        }
    }
    if !output.starts_with(owned) || output == owned {
        return Err(invalid("scenario path escapes owned root"));
    }
    Ok(output)
}
impl Scenario {
    pub fn new(physical: &Physical) -> SourceResult<Self> {
        let cwd = std::env::current_dir()?;
        let owned = tempfile::Builder::new()
            .prefix("source-case-")
            .tempdir_in(cwd)?;
        let root = owned.path().join("project");
        let files = OwnedFiles::new(owned.path())?;
        files.directory(Path::new("project"))?;
        if physical.files.len() > 128
            || physical.owners.len() > 256
            || physical.files.values().map(Vec::len).sum::<usize>() > 4 * 1024 * 1024
        {
            return Err(source_invalid("scenario source inventory exceeds bound"));
        }
        for (name, bytes) in &physical.files {
            if bytes.len() > 1024 * 1024 {
                return Err(source_invalid("scenario source exceeds1MiB"));
            }
            let target = confined(&root, Path::new(name), owned.path())
                .map_err(|e| source_invalid(e.to_string()))?;
            files.write(
                target.strip_prefix(owned.path()).expect("confined target"),
                bytes,
                true,
            )?;
        }
        for link in &physical.symlinks {
            let path = confined(&root, Path::new(&link.path), owned.path())
                .map_err(|e| source_invalid(e.to_string()))?;
            confined(
                path.parent().expect("owned link"),
                Path::new(&link.target),
                owned.path(),
            )
            .map_err(|e| source_invalid(e.to_string()))?;
            files.symlink(
                Path::new(&link.target),
                path.strip_prefix(owned.path()).expect("confined link"),
                true,
            )?;
        }
        let context = DiscoveryContext {
            cwd: root.clone(),
            forced_root: None,
            home: None,
        };
        let paths = ProjectPaths::at(&root, &context).map_err(|e| source_invalid(e.to_string()))?;
        let source = Arc::new(SourceAuthority::new(&paths)?);
        Ok(Self {
            _owned: owned,
            files,
            root,
            source,
        })
    }
    pub fn catalog(&self, owners: Vec<Owner>) -> SourceResult<Arc<SourceCatalog>> {
        Ok(Arc::new(SourceCatalog::new(
            self.source.clone(),
            owners.into_iter().map(|o| (o.key, o.passages)).collect(),
        )?))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Mutation {
    pub op: String,
    pub path: String,
    pub bytes: Option<Vec<u8>>,
}
impl Scenario {
    pub fn mutate(&self, mutation: &Mutation) -> SourceResult<()> {
        let target = confined(&self.root, Path::new(&mutation.path), self._owned.path())
            .map_err(|e| source_invalid(e.to_string()))?;
        let relative = target
            .strip_prefix(self._owned.path())
            .expect("confined mutation");
        match mutation.op.as_str() {
            "write" => {
                let bytes = mutation
                    .bytes
                    .as_ref()
                    .ok_or_else(|| source_invalid("mutation bytes required"))?;
                if bytes.len() > 1024 * 1024 {
                    return Err(source_invalid("mutation exceeds1MiB"));
                }
                self.files.write(relative, bytes, false)?;
            }
            "delete" => self.files.remove(relative)?,
            "symlink" => {
                let outside = self._owned.path().join("outside.py");
                self.files
                    .write(Path::new("outside.py"), b"outside fixture\n", false)?;
                self.files.remove(relative)?;
                self.files.symlink(&outside, relative, false)?;
            }
            "replace-root" => {
                let bytes = mutation
                    .bytes
                    .as_ref()
                    .ok_or_else(|| source_invalid("mutation bytes required"))?;
                if bytes.len() > 1024 * 1024 {
                    return Err(source_invalid("mutation exceeds1MiB"));
                }
                self.files
                    .rename(Path::new("project"), Path::new("old-project"))?;
                self.files.directory(Path::new("project"))?;
                self.files.write(relative, bytes, true)?;
            }
            _ => return Err(source_invalid("unknown disposable source mutation")),
        }
        Ok(())
    }
    pub fn normalize(&self, message: &str) -> String {
        message
            .replace(&*self.root.to_string_lossy(), "{project}")
            .replace(&*self._owned.path().to_string_lossy(), "{scenario}")
    }
}
