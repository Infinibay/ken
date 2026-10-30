use super::{
    Result, invalid,
    model::{digest, relative},
};
use ken_knowledge::dependencies::{Budget, Fingerprints};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
const EXTENSIONS: &[&str] = &[
    "py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "java", "cs", "cpp", "hpp", "cc", "go",
    "rs", "rb", "rake", "gemspec", "c", "h", "kt", "swift", "scala", "dart",
];
pub fn capture_sources(root: &Path, scope: &str, budget: Duration) -> Result<Value> {
    capture_sources_checked(root, scope, budget, &mut || Ok(()))
}
pub fn capture_sources_checked(
    root: &Path,
    scope: &str,
    budget: Duration,
    control: &mut dyn FnMut() -> Result<()>,
) -> Result<Value> {
    let started = Instant::now();
    control()?;
    if budget.is_zero() {
        return Err(invalid("source inventory budget exhausted"));
    }
    let root = root.canonicalize()?;
    let scope = relative(scope)?;
    let target = confined(&root, &scope)?;
    let mut filter =
        ken_core::source_filter::SourceFilter::new(&root).map_err(|e| invalid(e.to_string()))?;
    let mut files = Vec::new();
    let mut entries = 0;
    if target.is_file() {
        files.push(target);
    } else if target.is_dir() {
        walk(
            &root,
            &target,
            &mut filter,
            InventoryTime {
                start: started,
                budget,
            },
            &mut entries,
            &mut files,
            control,
        )?;
    } else {
        return Err(invalid("rule scope is missing"));
    }
    files.sort();
    let mut fp = Fingerprints::new(
        &root,
        Budget {
            max_files: 4000,
            max_bytes: 128000000,
            max_entries: 30000,
            duration: budget.saturating_sub(started.elapsed()),
        },
    )
    .map_err(|e| invalid(e.to_string()))?;
    let mut manifest = Vec::new();
    for file in files {
        control()?;
        if started.elapsed() > budget {
            return Err(invalid("source inventory budget exhausted"));
        }
        let extension = file
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_lowercase();
        if EXTENSIONS.contains(&extension.as_str()) {
            let path = file
                .strip_prefix(&root)
                .map_err(|_| invalid("source path escapes project root"))?
                .to_string_lossy()
                .into_owned();
            let item = fp
                .snapshot_checked(&json!({"path":path}), &mut || {
                    control().map_err(|error| ken_knowledge::Error::Invalid(error.to_string()))
                })
                .map_err(|e| invalid(e.to_string()))?;
            manifest.push(json!([item["path"], item["sha256"]]));
        }
    }
    control()?;
    if started.elapsed() >= budget {
        return Err(invalid("source inventory budget exhausted"));
    }
    Ok(json!({"scope":scope,"sha256":digest(&json!(manifest)),"manifest":manifest}))
}
#[derive(Clone, Copy)]
struct InventoryTime {
    start: Instant,
    budget: Duration,
}

fn walk(
    root: &Path,
    dir: &Path,
    filter: &mut ken_core::source_filter::SourceFilter,
    time: InventoryTime,
    entries: &mut usize,
    files: &mut Vec<PathBuf>,
    control: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    control()?;
    if time.start.elapsed() >= time.budget {
        return Err(invalid("source inventory budget exhausted"));
    }
    let mut dirs = Vec::new();
    for entry in fs::read_dir(dir)? {
        control()?;
        let entry = entry?;
        let path = entry.path();
        let relative = path
            .strip_prefix(root)
            .map_err(|_| invalid("source path escapes project root"))?;
        let meta = fs::symlink_metadata(&path)?;
        let is_dir = meta.is_dir() || (meta.file_type().is_symlink() && path.is_dir());
        if is_dir {
            if filter
                .is_ignored(relative, true)
                .map_err(|e| invalid(e.to_string()))?
            {
                continue;
            }
            *entries += 1;
            if meta.file_type().is_symlink() {
                return Err(invalid("symlink directory makes source coverage unknown"));
            }
            dirs.push(path);
        } else {
            *entries += 1;
            if !filter
                .is_ignored(relative, false)
                .map_err(|e| invalid(e.to_string()))?
            {
                files.push(path);
            }
        }
        if *entries > 30000 {
            return Err(invalid("source inventory exceeds 30000 entries"));
        }
    }
    dirs.sort();
    for dir in dirs {
        walk(root, &dir, filter, time, entries, files, control)?;
    }
    Ok(())
}
pub(super) fn confined(root: &Path, relative: &str) -> Result<PathBuf> {
    let mut path = root.to_path_buf();
    for part in Path::new(relative).components() {
        path.push(part);
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.file_type().is_symlink() => {
                return Err(invalid("symlink dependencies are not supported"));
            }
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
    }
    Ok(path)
}
