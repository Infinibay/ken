//! One immutable source capture owns limits, omission evidence and content keys.
use crate::{BuildError, Result};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_filter::SourceError,
    source_reader::SourceFileReader,
    source_walk::ProjectSources,
};
use ken_program::IR_VERSION;
use ken_store::artifact_cache::ArtifactCache;
use ken_syntax::Language;
use serde::Serialize;
use std::{
    fs,
    path::{Path, PathBuf},
};
#[derive(Clone, Copy, Debug)]
pub struct ScanLimits {
    pub max_files: Option<usize>,
    pub max_file_bytes: u64,
}
impl Default for ScanLimits {
    fn default() -> Self {
        Self {
            max_files: None,
            max_file_bytes: 2_000_000,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Skipped {
    pub path: String,
    pub reason: String,
}
pub struct ManifestSource {
    path: String,
    key: String,
    language: Language,
    content: Vec<u8>,
}
impl ManifestSource {
    pub fn path(&self) -> &str {
        &self.path
    }
    pub fn key(&self) -> &str {
        &self.key
    }
    pub fn language(&self) -> Language {
        self.language
    }
    pub fn content(&self) -> &[u8] {
        &self.content
    }
}
pub struct SourceManifest {
    pub(crate) root: PathBuf,
    pub(crate) revision: String,
    pub(crate) entries: Vec<ManifestSource>,
    pub(crate) skipped: Vec<Skipped>,
    pub(crate) graph_key: String,
}
impl SourceManifest {
    pub fn entries(&self) -> &[ManifestSource] {
        &self.entries
    }
    pub fn skipped(&self) -> &[Skipped] {
        &self.skipped
    }
    pub fn graph_key(&self) -> &str {
        &self.graph_key
    }
    pub(crate) fn capture(
        paths: &ProjectPaths,
        context: &DiscoveryContext,
        scope: &Path,
        revision: &str,
        limits: ScanLimits,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<Self> {
        Self::capture_sources(paths, context, scope, None, revision, limits, check)
    }
    pub(crate) fn capture_sources(
        paths: &ProjectPaths,
        context: &DiscoveryContext,
        scope: &Path,
        source_paths: Option<&[String]>,
        revision: &str,
        limits: ScanLimits,
        check: &mut impl FnMut() -> Result<()>,
    ) -> Result<Self> {
        if limits.max_files == Some(0) || limits.max_file_bytes == 0 {
            return Err(BuildError::Invalid("scan limits must be positive"));
        }
        check()?;
        let target = paths.resolve_inside(scope, context)?;
        let metadata = match fs::metadata(&target) {
            Ok(m) => m,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                return Err(BuildError::Missing(scope.into()));
            }
            Err(e) => return Err(e.into()),
        };
        let directory = metadata.is_dir();
        let mut considered = vec![];
        let mut skipped = vec![];
        if let Some(sources) = source_paths {
            if sources.len() > 4000 {
                return Err(BuildError::Invalid(
                    "explicit source inventory exceeds 4000 files",
                ));
            }
            for item in sources {
                check()?;
                let selected = paths.resolve_inside(Path::new(item), context)?;
                if !fs::metadata(&selected)?.is_file()
                    || (directory && !selected.starts_with(&target))
                    || (!directory && selected != target)
                {
                    return Err(BuildError::Invalid(
                        "explicit source files must exist inside the analysis scope",
                    ));
                }
                considered.push(
                    selected
                        .strip_prefix(paths.root())
                        .map_err(|_| BuildError::Invalid("source path escapes root"))?
                        .to_path_buf(),
                );
            }
        } else if directory {
            for entry in ProjectSources::new(paths.clone(), context.clone()).walk(&target)? {
                check()?;
                match entry {
                    Ok(e) if !e.is_dir => considered.push(e.path),
                    Ok(_) => {}
                    Err(SourceError::OutsideRoot { path }) => skipped.push(Skipped {
                        path: path.to_string_lossy().into(),
                        reason: "symlink escapes project".into(),
                    }),
                    Err(SourceError::Cycle { path }) => skipped.push(Skipped {
                        path: path.to_string_lossy().into(),
                        reason: "symlink cycle".into(),
                    }),
                    Err(SourceError::Io { path, source }) => skipped.push(Skipped {
                        path: path.to_string_lossy().into(),
                        reason: source.to_string(),
                    }),
                    Err(e) => return Err(e.into()),
                }
            }
        } else {
            considered.push(
                target
                    .strip_prefix(paths.root())
                    .map_err(|_| BuildError::Invalid("source path escapes root"))?
                    .into(),
            );
        }
        considered.sort();
        considered.dedup();
        let reader = SourceFileReader::new(paths)?;
        let mut entries = vec![];
        for relative in considered {
            check()?;
            let Some(name) = relative.to_str() else {
                skipped.push(Skipped {
                    path: relative.to_string_lossy().into(),
                    reason: "non-UTF8 source path".into(),
                });
                continue;
            };
            let absolute = match paths.resolve_inside(&relative, context) {
                Ok(p) => p,
                Err(_) => {
                    skipped.push(Skipped {
                        path: name.into(),
                        reason: "symlink escapes project".into(),
                    });
                    continue;
                }
            };
            if directory && !absolute.starts_with(&target) {
                continue;
            }
            let suffix = relative
                .extension()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_ascii_lowercase();
            let language = match suffix.as_str() {
                "py" | "pyi" => Language::Python,
                "js" | "jsx" | "mjs" | "cjs" => Language::JavaScript,
                "ts" | "tsx" => Language::TypeScript,
                "java" => Language::Java,
                "cs" => Language::CSharp,
                "cpp" | "hpp" | "cc" => Language::Cpp,
                "go" => Language::Go,
                "rs" => Language::Rust,
                "rb" | "rake" | "gemspec" => Language::Ruby,
                _ => {
                    if matches!(
                        suffix.as_str(),
                        "c" | "h" | "kt" | "dart" | "php" | "swift" | "scala"
                    ) {
                        skipped.push(Skipped {
                            path: name.into(),
                            reason: "no structural frontend".into(),
                        });
                    }
                    continue;
                }
            };
            if limits.max_files.is_some_and(|max| entries.len() >= max) {
                skipped.push(Skipped {
                    path: name.into(),
                    reason: "max_files".into(),
                });
                continue;
            }
            let mut stopped = None;
            let read = (|| {
                let file = reader.open(&absolute)?;
                if file.metadata()?.len() > limits.max_file_bytes {
                    return Ok(None);
                }
                file.read_bounded_checked(limits.max_file_bytes, &mut || match check() {
                    Ok(()) => Ok(()),
                    Err(error) => {
                        stopped = Some(error);
                        Err(std::io::Error::other("source capture interrupted"))
                    }
                })
            })();
            if let Some(error) = stopped {
                return Err(error);
            }
            let content = match read {
                Ok(Some(b)) => b,
                Ok(None) => {
                    skipped.push(Skipped {
                        path: name.into(),
                        reason: "max_file_bytes".into(),
                    });
                    continue;
                }
                Err(e) => {
                    skipped.push(Skipped {
                        path: name.into(),
                        reason: e.to_string(),
                    });
                    continue;
                }
            };
            let key = ArtifactCache::key([
                b"unit".as_slice(),
                IR_VERSION.as_bytes(),
                revision.as_bytes(),
                name.as_bytes(),
                language.as_str().as_bytes(),
                &content,
            ]);
            entries.push(ManifestSource {
                path: name.into(),
                key,
                language,
                content,
            });
        }
        skipped.sort_by(|a, b| a.path.cmp(&b.path));
        let graph_key = ArtifactCache::key(
            [
                b"project".as_slice(),
                IR_VERSION.as_bytes(),
                revision.as_bytes(),
            ]
            .into_iter()
            .chain(entries.iter().map(|e| e.key.as_bytes())),
        );
        // Lowering identity belongs to the frontend. Linked-result identity also
        // includes the native engine, even for a custom frontend with a stable IR.
        let graph_key = ArtifactCache::key([
            b"native-project-graph/1".as_slice(),
            crate::IMPLEMENTATION_FINGERPRINT.as_bytes(),
            graph_key.as_bytes(),
        ]);
        Ok(Self {
            root: paths.root().into(),
            revision: revision.into(),
            entries,
            skipped,
            graph_key,
        })
    }
}
