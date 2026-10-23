//! Project-owned exclusion barriers and independently scoped Git decisions.
use crate::source_patterns::SourcePatterns;
use std::{
    collections::BTreeMap,
    fs, io,
    path::{Component, Path, PathBuf},
};
use thiserror::Error;

const ALWAYS_IGNORE: &[&str] = &[
    ".ken/",
    ".git/",
    ".hg/",
    ".svn/",
    ".claude/",
    ".agents/skills/",
    ".opencode/skills/",
    ".dsh/skills/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "node_modules/",
    "target/",
    "dist/",
    "build/",
    ".DS_Store",
];

#[derive(Debug, Error)]
pub enum SourceError {
    #[error("cannot inspect source {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("invalid source rules at {path}: {reason}")]
    Rules { path: PathBuf, reason: String },
    #[error("source path escapes project root: {path}")]
    OutsideRoot { path: PathBuf },
    #[error("source directory cycle: {path}")]
    Cycle { path: PathBuf },
    #[error(transparent)]
    Project(#[from] crate::project::ProjectError),
}

pub struct SourceFilter {
    root: PathBuf,
    builtins: SourcePatterns,
    project: SourcePatterns,
    git: BTreeMap<PathBuf, SourcePatterns>,
}

fn io_error(path: &Path, source: io::Error) -> SourceError {
    SourceError::Io {
        path: path.into(),
        source,
    }
}

fn compile(path: &Path, text: &str) -> Result<SourcePatterns, SourceError> {
    SourcePatterns::compile(text).map_err(|reason| SourceError::Rules {
        path: path.into(),
        reason,
    })
}

impl SourceFilter {
    pub fn new(root: &Path) -> Result<Self, SourceError> {
        let root = fs::canonicalize(root).map_err(|e| io_error(root, e))?;
        let builtins = compile(&root.join("<builtins>"), &ALWAYS_IGNORE.join("\n"))?;
        let mut filter = Self {
            root,
            builtins,
            project: SourcePatterns::default(),
            git: BTreeMap::new(),
        };
        filter.project = filter.read_rules(&filter.root.join(".kenignore"))?;
        Ok(filter)
    }

    fn read_rules(&self, path: &Path) -> Result<SourcePatterns, SourceError> {
        let canonical = match fs::canonicalize(path) {
            Ok(path) => path,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(SourcePatterns::default()),
            Err(e) => return Err(io_error(path, e)),
        };
        if !canonical.starts_with(&self.root) {
            return Err(SourceError::OutsideRoot { path: path.into() });
        }
        let raw = fs::read(&canonical).map_err(|e| io_error(path, e))?;
        compile(path, &String::from_utf8_lossy(&raw))
    }

    pub fn is_ignored(&mut self, relative: &Path, is_dir: bool) -> Result<bool, SourceError> {
        if relative
            .components()
            .any(|c| !matches!(c, Component::Normal(_) | Component::CurDir))
        {
            return Err(SourceError::OutsideRoot {
                path: relative.into(),
            });
        }
        let mut identity = relative.to_string_lossy().into_owned();
        if is_dir {
            identity.push('/');
        }
        if self.builtins.decision(&identity) == Some(true)
            || self.project.decision(&identity) == Some(true)
        {
            return Ok(true);
        }
        let mut bases = vec![PathBuf::new()];
        if let Some(parent) = relative.parent() {
            let mut current = PathBuf::new();
            for part in parent
                .components()
                .filter(|c| matches!(c, Component::Normal(_)))
            {
                current.push(part);
                bases.push(current.clone());
            }
        }
        let mut ignored = false;
        for base in bases {
            if !self.git.contains_key(&base) {
                let spec = self.read_rules(&self.root.join(&base).join(".gitignore"))?;
                self.git.insert(base.clone(), spec);
            }
            let local = relative.strip_prefix(&base).expect("ancestor base");
            let mut local = local.to_string_lossy().into_owned();
            if is_dir {
                local.push('/');
            }
            if let Some(result) = self.git[&base].decision(&local) {
                ignored = result;
            }
        }
        Ok(ignored)
    }
}
