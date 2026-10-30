//! Bounded dependency equality, never a truth or completeness checker.
use crate::{Result, invalid, wire};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, File, Metadata},
    io::Read,
    path::{Component, Path, PathBuf},
    time::{Duration, Instant},
};
#[derive(Clone, Copy, Debug)]
pub struct Budget {
    pub max_files: usize,
    pub max_bytes: usize,
    pub max_entries: usize,
    pub duration: Duration,
}
impl Default for Budget {
    fn default() -> Self {
        Self {
            max_files: 256,
            max_bytes: 16 * 1024 * 1024,
            max_entries: 10000,
            duration: Duration::from_millis(200),
        }
    }
}
pub struct Fingerprints {
    root: PathBuf,
    budget: Budget,
    files: usize,
    bytes: usize,
    entries: usize,
    started: Instant,
    cache: BTreeMap<String, String>,
}
impl Fingerprints {
    pub fn new(root: &Path, budget: Budget) -> Result<Self> {
        Ok(Self {
            root: root.canonicalize()?,
            budget,
            files: 0,
            bytes: 0,
            entries: 0,
            started: Instant::now(),
            cache: BTreeMap::new(),
        })
    }
    fn check(&self, control: &mut dyn FnMut() -> Result<()>) -> Result<()> {
        control()?;
        if self.started.elapsed() > self.budget.duration {
            Err(invalid("dependency check budget exhausted"))
        } else {
            Ok(())
        }
    }
    fn path(&self, value: &str) -> Result<PathBuf> {
        if value.trim().is_empty() {
            return Err(invalid("dependency path must be nonempty"));
        }
        let raw = Path::new(value);
        if raw.components().any(|c| c == Component::ParentDir) {
            return Err(invalid(
                "dependency paths cannot traverse parent directories",
            ));
        }
        let candidate = if raw.is_absolute() {
            raw.to_path_buf()
        } else {
            self.root.join(raw)
        };
        let candidate = candidate.components().collect::<PathBuf>();
        let rel = candidate
            .strip_prefix(&self.root)
            .map_err(|_| invalid("dependencies must stay inside the project"))?;
        let mut current = self.root.clone();
        for part in rel.components() {
            current.push(part);
            match fs::symlink_metadata(&current) {
                Ok(m) if m.file_type().is_symlink() => {
                    return Err(invalid("symlink dependencies are not supported"));
                }
                Ok(_) => {}
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(e) => return Err(e.into()),
            }
        }
        Ok(candidate)
    }
    pub fn snapshot(&mut self, spec: &Value) -> Result<Value> {
        self.snapshot_checked(spec, &mut || Ok(()))
    }
    /// Cooperative control over the same dependency admission/read/hash pipeline.
    pub fn snapshot_checked(
        &mut self,
        spec: &Value,
        control: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Value> {
        self.check(control)?;
        wire::fields(
            spec,
            &["kind", "path", "pattern", "sha256"],
            "dependency fields: kind, path, pattern, sha256",
        )?;
        let kind = spec.get("kind").unwrap_or(&Value::Null).as_str().unwrap_or(
            if spec.get("kind").is_none() {
                "file"
            } else {
                ""
            },
        );
        if kind != "file" && kind != "tree" {
            return Err(invalid("dependency kind must be file or tree"));
        }
        let path = self.path(
            spec["path"]
                .as_str()
                .ok_or_else(|| invalid("dependency path must be nonempty"))?,
        )?;
        let relative = path
            .strip_prefix(&self.root)
            .map_err(|_| invalid("dependencies must stay inside the project"))?
            .to_string_lossy()
            .replace('\\', "/");
        let relative = if relative.is_empty() {
            ".".to_owned()
        } else {
            relative
        };
        let mut clean = json!({"kind":kind,"path":relative});
        if kind == "tree" {
            let pattern = spec
                .get("pattern")
                .map_or(Some("*"), Value::as_str)
                .ok_or_else(|| invalid("tree pattern must contain 1..256 characters"))?;
            if pattern.is_empty() || pattern.chars().count() > 256 {
                return Err(invalid("tree pattern must contain 1..256 characters"));
            }
            clean["pattern"] = json!(pattern);
        } else if spec.get("pattern").is_some() {
            return Err(invalid("pattern only applies to tree dependencies"));
        }
        let key = wire::json(&clean);
        let digest = if let Some(hash) = self.cache.get(&key) {
            hash.clone()
        } else {
            self.check(control)?;
            let h = if kind == "tree" {
                self.tree(&path, clean["pattern"].as_str().unwrap(), control)?
            } else {
                self.file(&path, control)?
            };
            self.cache.insert(key, h.clone());
            h
        };
        self.check(control)?;
        clean["sha256"] = json!(digest);
        Ok(clean)
    }
    fn file(&mut self, path: &Path, control: &mut dyn FnMut() -> Result<()>) -> Result<String> {
        self.check(control)?;
        if self.files >= self.budget.max_files {
            return Err(invalid("dependency file budget exhausted"));
        }
        self.files += 1;
        let meta = fs::symlink_metadata(path)
            .map_err(|_| invalid("dependency file missing or unsupported"))?;
        if !meta.is_file() || meta.file_type().is_symlink() {
            return Err(invalid("dependency file missing or unsupported"));
        }
        let mut file = File::open(path)?;
        let before = file.metadata()?;
        let remaining = self.budget.max_bytes.saturating_sub(self.bytes);
        use sha2::Digest;
        let mut hash = sha2::Sha256::new();
        let mut limited =
            std::io::Read::by_ref(&mut file).take((remaining as u64).saturating_add(1));
        let mut chunk = [0u8; 8192];
        loop {
            self.check(control)?;
            let count = limited.read(&mut chunk)?;
            if count == 0 {
                break;
            }
            self.bytes += count;
            if self.bytes > self.budget.max_bytes {
                return Err(invalid("dependency byte budget exhausted"));
            }
            hash.update(&chunk[..count]);
        }
        let after = file.metadata()?;
        let current = fs::metadata(path)?;
        if stamp(&before) != stamp(&after) || stamp(&after) != stamp(&current) {
            return Err(invalid("dependency changed during inspection"));
        }
        self.check(control)?;
        Ok(format!("{:x}", hash.finalize()))
    }
    fn tree(
        &mut self,
        path: &Path,
        pattern: &str,
        control: &mut dyn FnMut() -> Result<()>,
    ) -> Result<String> {
        if !path.is_dir() {
            return Err(invalid("dependency directory missing"));
        }
        let mut entries = Vec::new();
        let mut directories = Vec::new();
        self.walk(path, path, pattern, &mut entries, &mut directories, control)?;
        for (p, prior) in directories {
            self.check(control)?;
            if stamp(&fs::metadata(p)?) != prior {
                return Err(invalid("dependency tree changed during inspection"));
            }
        }
        entries.sort();
        use sha2::Digest;
        let data = wire::json_ascii(&json!(entries));
        let mut hash = sha2::Sha256::new();
        for chunk in data.as_bytes().chunks(8192) {
            self.check(control)?;
            hash.update(chunk);
        }
        Ok(format!("{:x}", hash.finalize()))
    }
    fn walk(
        &mut self,
        root: &Path,
        dir: &Path,
        pattern: &str,
        entries: &mut Vec<(String, String)>,
        directories: &mut Vec<(PathBuf, Stamp)>,
        control: &mut dyn FnMut() -> Result<()>,
    ) -> Result<()> {
        self.check(control)?;
        directories.push((dir.to_path_buf(), stamp(&fs::metadata(dir)?)));
        let mut files = Vec::new();
        let mut dirs = Vec::new();
        for item in fs::read_dir(dir)? {
            self.check(control)?;
            let item = item?;
            self.entries += 1;
            if self.entries > self.budget.max_entries {
                return Err(invalid("dependency tree budget exhausted"));
            }
            let path = item.path();
            let meta = fs::symlink_metadata(&path)?;
            if meta.file_type().is_symlink() && path.is_dir() {
                return Err(invalid("symlink directories make tree coverage unknown"));
            }
            if meta.is_dir() {
                dirs.push(path)
            } else {
                files.push(path)
            }
        }
        files.sort();
        for file in files {
            let rel = file
                .strip_prefix(root)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            if path_matches(&rel, pattern) {
                entries.push((rel, self.file(&file, control)?));
            }
        }
        for sub in dirs {
            self.walk(root, &sub, pattern, entries, directories, control)?;
        }
        Ok(())
    }
}
#[cfg(unix)]
type Stamp = (u64, u64, i64, i64, i64, i64);
#[cfg(unix)]
fn stamp(m: &Metadata) -> Stamp {
    use std::os::unix::fs::MetadataExt;
    (
        m.ino(),
        m.len(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    )
}
#[cfg(not(unix))]
type Stamp = (u64, Option<std::time::SystemTime>);
#[cfg(not(unix))]
fn stamp(m: &Metadata) -> Stamp {
    (m.len(), m.modified().ok())
}
/// PurePosixPath.match uses right-aligned path components; '*' never crosses '/'.
fn path_matches(path: &str, pattern: &str) -> bool {
    let p = path.split('/').collect::<Vec<_>>();
    let pat = pattern.split('/').collect::<Vec<_>>();
    if pat.len() > p.len() {
        return false;
    }
    if pattern.starts_with('/') {
        return false;
    }
    p[p.len() - pat.len()..]
        .iter()
        .zip(pat)
        .all(|(part, glob)| glob_match(part, glob))
}
fn glob_match(text: &str, pattern: &str) -> bool {
    let mut source = String::from(r"\A(?s:");
    let mut chars = pattern.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '*' => source.push_str(".*"),
            '?' => source.push('.'),
            '[' => {
                let mut class = String::new();
                if chars.peek() == Some(&'!') {
                    chars.next();
                    class.push('^');
                } else if chars.peek() == Some(&'^') {
                    class.push('\\');
                }
                if chars.peek() == Some(&']') {
                    class.push(']');
                    chars.next();
                }
                let mut closed = false;
                for c in chars.by_ref() {
                    if c == ']' {
                        closed = true;
                        break;
                    }
                    if c == '\\' {
                        class.push('\\');
                    }
                    class.push(c);
                }
                if closed {
                    source.push('[');
                    source.push_str(&class);
                    source.push(']');
                } else {
                    source.push_str("\\[");
                    source.push_str(&regex::escape(&class));
                }
            }
            _ => source.push_str(&regex::escape(&ch.to_string())),
        }
    }
    source.push_str(r")\z");
    regex::Regex::new(&source).is_ok_and(|r| r.is_match(text))
}
pub fn capture(specs: &Value, root: &Path) -> Result<Value> {
    let specs = specs
        .as_array()
        .ok_or_else(|| invalid("dependencies must be an array"))?;
    let mut fp = Fingerprints::new(
        root,
        Budget {
            duration: Duration::from_secs(2),
            ..Default::default()
        },
    )?;
    let mut snapshots: Vec<(String, Value)> = Vec::new();
    for spec in specs {
        let snapshot = fp.snapshot(spec)?;
        if spec.get("sha256").is_some_and(|h| h != &snapshot["sha256"]) {
            return Err(invalid(format!(
                "dependency changed before recording: {}",
                snapshot["path"].as_str().unwrap()
            )));
        }
        let mut key = snapshot.clone();
        key.as_object_mut().unwrap().remove("sha256");
        let key = wire::json(&key);
        if let Some(existing) = snapshots.iter_mut().find(|(k, _)| k == &key) {
            existing.1 = snapshot;
        } else {
            snapshots.push((key, snapshot));
        }
    }
    Ok(json!(
        snapshots.into_iter().map(|(_, v)| v).collect::<Vec<_>>()
    ))
}
fn declarations(deps: &Value) -> std::result::Result<&[Value], Value> {
    let Some(specs) = deps
        .as_array()
        .filter(|s| s.len() <= 48 && s.iter().all(Value::is_object))
    else {
        return Err(json!({"state":"unknown","issues":["invalid dependency declarations"]}));
    };
    if specs.is_empty() {
        return Err(json!({"state":"untracked","issues":["no declared dependencies"]}));
    }
    Ok(specs)
}
pub fn assess(deps: &Value, root: Option<&Path>, budget: Budget) -> Value {
    if let Err(result) = declarations(deps) {
        return result;
    }
    let mut fp = match root {
        Some(root) => match Fingerprints::new(root, budget) {
            Ok(fp) => Some(fp),
            Err(e) => return json!({"state":"unknown","issues":[e.to_string()]}),
        },
        None => None,
    };
    assess_with_fingerprints(deps, fp.as_mut())
}
/// Share one bounded fingerprint cache across a selected batch of findings.
pub fn assess_with_fingerprints(deps: &Value, fingerprints: Option<&mut Fingerprints>) -> Value {
    let specs = match declarations(deps) {
        Ok(specs) => specs,
        Err(result) => return result,
    };
    let Some(fp) = fingerprints else {
        return json!({"state":"unknown","issues":["project root unavailable"]});
    };
    let mut changed = Vec::new();
    let mut unavailable = Vec::new();
    for spec in specs {
        match fp.snapshot(spec) {
            Ok(current) => {
                if current["sha256"] != spec["sha256"] {
                    changed.push(spec["path"].as_str().unwrap_or("?").to_owned());
                }
            }
            Err(e) => unavailable.push(format!("{}: {e}", spec["path"].as_str().unwrap_or("?"))),
        }
    }
    let state = if !changed.is_empty() {
        "stale"
    } else if !unavailable.is_empty() {
        "unknown"
    } else {
        "unchanged"
    };
    changed.extend(unavailable);
    json!({"state":state,"issues":changed,"scope":"declared dependencies only; not a truth or coverage check"})
}
