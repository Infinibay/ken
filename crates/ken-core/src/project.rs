//! Project identity and canonical, confined paths. Environment is captured once.
use std::{
    collections::HashMap,
    env,
    ffi::OsString,
    fs, io,
    path::{Component, Path, PathBuf},
};
use thiserror::Error;

#[derive(Debug, Clone)]
pub struct DiscoveryContext {
    pub cwd: PathBuf,
    pub forced_root: Option<OsString>,
    pub home: Option<PathBuf>,
}

impl DiscoveryContext {
    pub fn from_process() -> Result<Self, ProjectError> {
        Ok(Self {
            cwd: env::current_dir().map_err(|source| ProjectError::Io {
                path: PathBuf::from("."),
                source,
            })?,
            forced_root: env::var_os("KEN_PROJECT_ROOT"),
            home: env::var_os("HOME").map(PathBuf::from),
        })
    }
}

#[derive(Debug, Error)]
pub enum ProjectError {
    #[error("cannot resolve {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("cannot determine home directory: {path}")]
    Home { path: PathBuf },
    #[error("path escapes project root: {path}")]
    EscapesRoot { path: PathBuf },
}

#[derive(Debug, Clone)]
pub struct ProjectPaths {
    root: PathBuf,
}

impl ProjectPaths {
    pub fn at(root: &Path, context: &DiscoveryContext) -> Result<Self, ProjectError> {
        Ok(Self {
            root: resolve_start(root, context)?,
        })
    }
    /// Hold the canonical project root for component-relative confined access.
    pub fn open_root(&self) -> io::Result<std::fs::File> {
        crate::source_handles::open_root(&self.root)
    }
    pub fn root(&self) -> &Path {
        &self.root
    }
    pub fn meta(&self) -> PathBuf {
        self.root.join(".ken/meta.json")
    }
    pub fn db(&self) -> PathBuf {
        self.root.join(".ken/ken.db")
    }
    pub fn vectors(&self) -> PathBuf {
        self.root.join(".ken/vectors")
    }
    pub fn port(&self) -> PathBuf {
        self.root.join(".ken/daemon.port")
    }
    pub fn pid(&self) -> PathBuf {
        self.root.join(".ken/daemon.pid")
    }
    pub fn log(&self) -> PathBuf {
        self.root.join(".ken/daemon.log")
    }
    pub fn resolve_inside(
        &self,
        path: &Path,
        context: &DiscoveryContext,
    ) -> Result<PathBuf, ProjectError> {
        let supplied = expand_home(path, context)?;
        let resolved = canonical(&self.root.join(supplied))?;
        if !resolved.starts_with(&self.root) {
            return Err(ProjectError::EscapesRoot { path: path.into() });
        }
        Ok(resolved)
    }
}

pub fn locate_project(
    start: &Path,
    context: &DiscoveryContext,
) -> Result<Option<ProjectPaths>, ProjectError> {
    if let Some(forced) = context
        .forced_root
        .as_ref()
        .filter(|value| !value.is_empty())
    {
        let paths = ProjectPaths::at(&expand_home(Path::new(forced), context)?, context)?;
        return Ok(is_file(&paths.meta())?.then_some(paths));
    }
    let resolved = resolve_start(start, context)?;
    for root in resolved.ancestors() {
        let paths = ProjectPaths { root: root.into() };
        if is_file(&paths.meta())? {
            return Ok(Some(paths));
        }
    }
    Ok(None)
}

pub(crate) fn is_file(path: &Path) -> Result<bool, ProjectError> {
    metadata_if_present(path)
        .map(|metadata| metadata.is_some_and(|info| info.is_file()))
        .map_err(|source| ProjectError::Io {
            path: path.into(),
            source,
        })
}

pub(crate) fn path_exists(path: &Path) -> io::Result<bool> {
    metadata_if_present(path).map(|metadata| metadata.is_some())
}

// Match pathlib's existence checks, including unavailable symlink targets.
// Permission and other IO errors remain explicit rather than becoming absence.
fn metadata_if_present(path: &Path) -> io::Result<Option<fs::Metadata>> {
    if path.as_os_str().as_encoded_bytes().contains(&0) {
        return Ok(None);
    }
    match fs::metadata(path) {
        Ok(info) => Ok(Some(info)),
        Err(error) if unavailable_path(&error) => Ok(None),
        Err(error) => Err(error),
    }
}

fn unavailable_path(error: &io::Error) -> bool {
    if matches!(
        error.kind(),
        io::ErrorKind::NotFound | io::ErrorKind::NotADirectory
    ) {
        return true;
    }
    #[cfg(unix)]
    {
        matches!(error.raw_os_error(), Some(libc::ELOOP) | Some(libc::EBADF))
    }
    #[cfg(not(unix))]
    {
        false
    }
}

pub(crate) fn resolve_start(
    path: &Path,
    context: &DiscoveryContext,
) -> Result<PathBuf, ProjectError> {
    canonical(&context.cwd.join(path))
}
fn canonical(path: &Path) -> Result<PathBuf, ProjectError> {
    resolve_components(path).map_err(|source| ProjectError::Io {
        path: path.into(),
        source,
    })
}

// Resolve links before processing the following `..`, even when their targets
// do not exist. A work stack also resolves links inside link targets without
// recursion or an arbitrary maximum chain length. Links are active until their
// target is complete; completed targets are reused within this resolution so
// shared acyclic targets do not expand exponentially.
fn resolve_components(path: &Path) -> io::Result<PathBuf> {
    enum Pending {
        Part(OsString),
        FinishLink(PathBuf),
    }
    enum LinkResolution {
        Active,
        Complete(PathBuf),
    }
    let parts = |p: &Path| {
        p.components()
            .rev()
            .map(|c| Pending::Part(c.as_os_str().to_owned()))
            .collect::<Vec<_>>()
    };
    let mut pending = parts(path);
    let mut links = HashMap::new();
    let mut resolved = PathBuf::new();
    while let Some(next) = pending.pop() {
        let raw = match next {
            Pending::FinishLink(link) => {
                links.insert(link, LinkResolution::Complete(resolved.clone()));
                continue;
            }
            Pending::Part(raw) => raw,
        };
        match Path::new(&raw).components().next() {
            Some(Component::CurDir) | None => continue,
            Some(Component::ParentDir) => {
                resolved.pop();
            }
            Some(Component::RootDir | Component::Prefix(_)) => resolved.push(raw),
            Some(Component::Normal(_)) => {
                let candidate = resolved.join(&raw);
                match fs::symlink_metadata(&candidate) {
                    Ok(meta) if meta.is_symlink() => {
                        match links.get(&candidate) {
                            Some(LinkResolution::Active) => {
                                return Err(io::Error::other("symbolic link cycle"));
                            }
                            Some(LinkResolution::Complete(target)) => {
                                resolved = target.clone();
                                continue;
                            }
                            None => {}
                        }
                        links.insert(candidate.clone(), LinkResolution::Active);
                        let target = fs::read_link(&candidate)?;
                        pending.push(Pending::FinishLink(candidate));
                        pending.extend(parts(&target));
                    }
                    Ok(_) => resolved.push(raw),
                    Err(e)
                        if matches!(
                            e.kind(),
                            io::ErrorKind::NotFound | io::ErrorKind::NotADirectory
                        ) =>
                    {
                        resolved.push(raw)
                    }
                    Err(e) => return Err(e),
                }
            }
        }
    }
    Ok(resolved)
}

fn expand_home(path: &Path, context: &DiscoveryContext) -> Result<PathBuf, ProjectError> {
    let mut components = path.components();
    let Some(Component::Normal(first)) = components.next() else {
        return Ok(path.into());
    };
    let Some(user) = first.as_encoded_bytes().strip_prefix(b"~") else {
        return Ok(path.into());
    };
    let home = if user.is_empty() {
        context.home.clone().or_else(|| account_home(None))
    } else {
        let name = first
            .to_str()
            .and_then(|s| s.strip_prefix('~'))
            .ok_or_else(|| ProjectError::Home { path: path.into() })?;
        account_home(Some(name))
    }
    .ok_or_else(|| ProjectError::Home { path: path.into() })?;
    Ok(home.join(components.as_path()))
}

#[cfg(unix)]
fn account_home(name: Option<&str>) -> Option<PathBuf> {
    use uzers::os::unix::UserExt;
    let user = match name {
        Some(name) => uzers::get_user_by_name(name),
        None => uzers::get_user_by_uid(uzers::get_current_uid()),
    }?;
    Some(user.home_dir().into())
}
#[cfg(not(unix))]
fn account_home(_: Option<&str>) -> Option<PathBuf> {
    None
}
