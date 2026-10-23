//! Confined source enumeration; exclusion rules belong to SourceFilter.
use crate::{
    project::{DiscoveryContext, ProjectPaths},
    source_filter::{SourceError, SourceFilter},
};
use std::{
    fs, io,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct SourceEntry {
    pub path: PathBuf,
    pub is_dir: bool,
}

pub struct ProjectSources {
    paths: ProjectPaths,
    context: DiscoveryContext,
}

impl ProjectSources {
    pub fn new(paths: ProjectPaths, context: DiscoveryContext) -> Self {
        Self { paths, context }
    }

    pub fn walk(&self, scope: &Path) -> Result<SourceWalk, SourceError> {
        let target = self.paths.resolve_inside(scope, &self.context)?;
        let root = self.paths.root().to_path_buf();
        // Each walk owns a fresh rule cache; later walks see edited rules.
        let mut filter = SourceFilter::new(&root)?;
        let mut ancestor = PathBuf::new();
        for part in target
            .strip_prefix(&root)
            .map_err(|_| SourceError::OutsideRoot {
                path: target.clone(),
            })?
            .components()
        {
            ancestor.push(part);
            if filter.is_ignored(&ancestor, true)? {
                return Ok(SourceWalk::empty(root, filter));
            }
        }
        let metadata = match fs::metadata(&target) {
            Ok(metadata) => metadata,
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::NotFound | io::ErrorKind::NotADirectory
                ) =>
            {
                return Ok(SourceWalk::empty(root, filter));
            }
            Err(source) => {
                return Err(SourceError::Io {
                    path: target,
                    source,
                });
            }
        };
        if !metadata.is_dir() {
            return Ok(SourceWalk::empty(root, filter));
        }
        let ancestry = target
            .ancestors()
            .take_while(|p| p.starts_with(&root))
            .map(Path::to_path_buf)
            .collect();
        let mut walk = SourceWalk::empty(root, filter);
        walk.pending.push(Directory {
            path: target,
            ancestry,
        });
        Ok(walk)
    }
}

struct Directory {
    path: PathBuf,
    ancestry: Vec<PathBuf>,
}

pub struct SourceWalk {
    root: PathBuf,
    filter: SourceFilter,
    pending: Vec<Directory>,
    entries: std::vec::IntoIter<fs::DirEntry>,
    ancestry: Vec<PathBuf>,
}

impl SourceWalk {
    fn empty(root: PathBuf, filter: SourceFilter) -> Self {
        Self {
            root,
            filter,
            pending: Vec::new(),
            entries: Vec::new().into_iter(),
            ancestry: Vec::new(),
        }
    }

    fn entry(&mut self, entry: fs::DirEntry) -> Result<Option<SourceEntry>, SourceError> {
        let path = entry.path();
        let relative = path
            .strip_prefix(&self.root)
            .map_err(|_| SourceError::OutsideRoot { path: path.clone() })?
            .to_path_buf();
        let metadata = match fs::metadata(&path) {
            Ok(metadata) => metadata,
            // pathlib treats unavailable symlink targets as neither file nor directory.
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    && entry.file_type().is_ok_and(|t| t.is_symlink()) =>
            {
                return Ok(None);
            }
            Err(source) => {
                return Err(SourceError::Io {
                    path: relative,
                    source,
                });
            }
        };
        let is_dir = metadata.is_dir();
        if self.filter.is_ignored(&relative, is_dir)? {
            return Ok(None);
        }
        let canonical = fs::canonicalize(&path).map_err(|source| SourceError::Io {
            path: relative.clone(),
            source,
        })?;
        if !canonical.starts_with(&self.root) {
            return Err(SourceError::OutsideRoot { path: relative });
        }
        if is_dir {
            if self.ancestry.contains(&canonical) {
                return Err(SourceError::Cycle { path: relative });
            }
            let mut ancestry = self.ancestry.clone();
            ancestry.push(canonical);
            self.pending.push(Directory { path, ancestry });
        } else if !metadata.is_file() {
            return Ok(None);
        }
        Ok(Some(SourceEntry {
            path: relative,
            is_dir,
        }))
    }
}

impl Iterator for SourceWalk {
    type Item = Result<SourceEntry, SourceError>;
    fn next(&mut self) -> Option<Self::Item> {
        loop {
            if let Some(entry) = self.entries.next() {
                match self.entry(entry) {
                    Ok(None) => continue,
                    Ok(Some(entry)) => return Some(Ok(entry)),
                    Err(error) => return Some(Err(error)),
                }
            }
            let directory = self.pending.pop()?;
            let entries = fs::read_dir(&directory.path)
                .and_then(|entries| entries.collect::<io::Result<Vec<_>>>());
            match entries {
                Ok(mut entries) => {
                    entries.sort_by_key(|entry| entry.file_name());
                    self.entries = entries.into_iter();
                    self.ancestry = directory.ancestry;
                }
                Err(source) => {
                    return Some(Err(SourceError::Io {
                        path: directory.path,
                        source,
                    }));
                }
            }
        }
    }
}
