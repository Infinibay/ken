//! Confined source enumeration; exclusion rules belong to SourceFilter.
use crate::{
    project::{DiscoveryContext, ProjectPaths},
    source_filter::{SourceError, SourceFilter},
};
use std::{
    ffi::OsString,
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
        let mut ancestry: Vec<_> = target
            .ancestors()
            .take_while(|p| p.starts_with(&root))
            .map(Path::to_path_buf)
            .collect();
        ancestry.reverse();
        let mut walk = SourceWalk::empty(root, filter);
        walk.root_handle = Some(
            fs::File::open(&walk.root).map_err(|source| SourceError::Io {
                path: walk.root.clone(),
                source,
            })?,
        );
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
    entries: std::vec::IntoIter<OsString>,
    current: PathBuf,
    root_handle: Option<fs::File>,
    ancestry: Vec<PathBuf>,
}

impl SourceWalk {
    fn empty(root: PathBuf, filter: SourceFilter) -> Self {
        Self {
            root,
            filter,
            pending: Vec::new(),
            entries: Vec::new().into_iter(),
            current: PathBuf::new(),
            root_handle: None,
            ancestry: Vec::new(),
        }
    }

    fn entry(&mut self, name: OsString) -> Result<Option<SourceEntry>, SourceError> {
        let path = self.current.join(name);
        let relative = path
            .strip_prefix(&self.root)
            .map_err(|_| SourceError::OutsideRoot { path: path.clone() })?
            .to_path_buf();
        let metadata = match fs::metadata(&path) {
            Ok(metadata) => metadata,
            // pathlib treats unavailable symlink targets as neither file nor directory.
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    && fs::symlink_metadata(&path).is_ok_and(|m| m.is_symlink()) =>
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

    fn directory_entries(&self, directory: &Directory) -> Result<Vec<OsString>, SourceError> {
        let relative = directory
            .path
            .strip_prefix(&self.root)
            .unwrap_or(&directory.path);
        let canonical = fs::canonicalize(&directory.path).map_err(|source| SourceError::Io {
            path: relative.into(),
            source,
        })?;
        if !canonical.starts_with(&self.root) {
            return Err(SourceError::OutsideRoot {
                path: relative.into(),
            });
        }
        if directory.ancestry.last() != Some(&canonical) {
            return Err(SourceError::Io {
                path: relative.into(),
                source: io::Error::new(
                    io::ErrorKind::InvalidData,
                    "source directory changed during traversal",
                ),
            });
        }
        crate::source_directory::read_names(
            self.root_handle
                .as_ref()
                .expect("nonempty walk owns root handle"),
            canonical
                .strip_prefix(&self.root)
                .expect("confined canonical path"),
        )
        .map_err(|source| SourceError::Io {
            path: relative.into(),
            source,
        })
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
            let entries = self.directory_entries(&directory);
            match entries {
                Ok(mut entries) => {
                    entries.sort();
                    self.entries = entries.into_iter();
                    self.current = directory.path;
                    self.ancestry = directory.ancestry;
                }
                Err(error) => return Some(Err(error)),
            }
        }
    }
}
