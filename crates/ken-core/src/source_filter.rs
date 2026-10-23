//! Project-owned exclusion barriers and independently scoped Git decisions.
use ignore::gitignore::{Gitignore, GitignoreBuilder};
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
    #[error("invalid source rules at {path}: {source}")]
    Rules {
        path: PathBuf,
        #[source]
        source: ignore::Error,
    },
    #[error("source path escapes project root: {path}")]
    OutsideRoot { path: PathBuf },
    #[error(transparent)]
    Project(#[from] crate::project::ProjectError),
}

pub struct SourceFilter {
    root: PathBuf,
    builtins: Gitignore,
    project: Gitignore,
    git: BTreeMap<PathBuf, Gitignore>,
}

fn io_error(path: &Path, source: io::Error) -> SourceError {
    SourceError::Io {
        path: path.into(),
        source,
    }
}

fn compile(root: &Path, path: &Path, text: &str) -> Result<Gitignore, SourceError> {
    let mut builder = GitignoreBuilder::new(root);
    builder.allow_unclosed_class(false);
    // Python str.splitlines includes these Unicode separators, unlike Rust lines().
    for line in text.split(|c| {
        matches!(
            c,
            '\n' | '\r'
                | '\x0b'
                | '\x0c'
                | '\x1c'
                | '\x1d'
                | '\x1e'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        )
    }) {
        match builder.add_line(Some(path.into()), line) {
            Ok(_) => {}
            // pathspec1.1.1 discards malformed ranges. ignore0.4.33 exposes
            // the underlying globset error as text, so keep this adaptation
            // narrowly bound to the two pinned character-class failures.
            Err(ignore::Error::Glob { err, .. })
                if err == "unclosed character class; missing ']'"
                    || err.starts_with("invalid range; ") => {}
            Err(source) => {
                return Err(SourceError::Rules {
                    path: path.into(),
                    source,
                });
            }
        }
    }
    builder.build().map_err(|source| SourceError::Rules {
        path: path.into(),
        source,
    })
}

impl SourceFilter {
    pub fn new(root: &Path) -> Result<Self, SourceError> {
        let root = fs::canonicalize(root).map_err(|e| io_error(root, e))?;
        let builtins = compile(&root, &root.join("<builtins>"), &ALWAYS_IGNORE.join("\n"))?;
        let mut filter = Self {
            root,
            builtins,
            project: Gitignore::empty(),
            git: BTreeMap::new(),
        };
        filter.project = filter.read_rules(&filter.root.join(".kenignore"))?;
        Ok(filter)
    }

    fn read_rules(&self, path: &Path) -> Result<Gitignore, SourceError> {
        let canonical = match fs::canonicalize(path) {
            Ok(path) => path,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Gitignore::empty()),
            Err(e) => return Err(io_error(path, e)),
        };
        if !canonical.starts_with(&self.root) {
            return Err(SourceError::OutsideRoot { path: path.into() });
        }
        let raw = fs::read(&canonical).map_err(|e| io_error(path, e))?;
        compile(
            path.parent().unwrap_or(&self.root),
            path,
            &String::from_utf8_lossy(&raw),
        )
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
        let full = self.root.join(relative);
        if self
            .builtins
            .matched_path_or_any_parents(&full, is_dir)
            .is_ignore()
            || self
                .project
                .matched_path_or_any_parents(&full, is_dir)
                .is_ignore()
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
            let result = self.git[&base].matched_path_or_any_parents(&full, is_dir);
            if !result.is_none() {
                ignored = result.is_ignore();
            }
        }
        Ok(ignored)
    }
}
