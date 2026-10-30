//! Descriptor-confined records, optimistic rule writes and immutable runs.
use super::{
    Result, invalid,
    model::{Rule, valid_id},
};
use serde_json::Value;
use std::{
    ffi::CString,
    fs::{self, File},
    io::{Read, Write},
    os::fd::{AsRawFd, FromRawFd},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::SystemTime,
};
static NEXT: AtomicU64 = AtomicU64::new(0);
const MAX_RECORD_BYTES: usize = 16000000;
struct BoundedWriter<'a> {
    file: &'a mut File,
    written: usize,
    check: &'a mut dyn FnMut() -> Result<()>,
}
impl Write for BoundedWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > MAX_RECORD_BYTES.saturating_sub(self.written) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "check record exceeds 16 MB",
            ));
        }
        (self.check)().map_err(std::io::Error::other)?;
        let count = self.file.write(&bytes[..bytes.len().min(8192)])?;
        self.written += count;
        Ok(count)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        (self.check)().map_err(std::io::Error::other)?;
        self.file.flush()
    }
}
pub struct Store {
    pub root: PathBuf,
    pub base: PathBuf,
}
struct Directory {
    file: File,
}
impl Directory {
    fn root(root: &Path) -> Result<Self> {
        use std::os::unix::fs::OpenOptionsExt;
        Ok(Self {
            file: fs::OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(root)?,
        })
    }
    fn child(&self, name: &str, create: bool) -> Result<Self> {
        let name = cstring(name)?;
        if create {
            let r = unsafe { libc::mkdirat(self.file.as_raw_fd(), name.as_ptr(), 0o700) };
            if r < 0 && std::io::Error::last_os_error().kind() != std::io::ErrorKind::AlreadyExists
            {
                return Err(std::io::Error::last_os_error().into());
            }
        }
        let fd = unsafe {
            libc::openat(
                self.file.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(Self {
            file: unsafe { File::from_raw_fd(fd) },
        })
    }
    fn open(&self, name: &str, flags: i32) -> Result<File> {
        let name = cstring(name)?;
        let fd = unsafe {
            libc::openat(
                self.file.as_raw_fd(),
                name.as_ptr(),
                flags | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK,
                0o600,
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let file = unsafe { File::from_raw_fd(fd) };
        if !file.metadata()?.is_file() {
            return Err(invalid("check record must be a regular file"));
        }
        Ok(file)
    }
    fn entries(&self, check: &mut dyn FnMut() -> Result<()>) -> Result<Vec<(String, SystemTime)>> {
        check()?;
        let mut out = Vec::new();
        for entry in fs::read_dir(format!("/proc/self/fd/{}", self.file.as_raw_fd()))? {
            check()?;
            let entry = entry?;
            let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
                continue;
            };
            if !name.ends_with(".json") {
                continue;
            }
            let key = name.trim_end_matches(".json");
            if !valid_id(key) {
                return Err(invalid("invalid check reference"));
            }
            let file = self.open(&name, libc::O_RDONLY)?;
            out.push((key.to_owned(), file.metadata()?.modified()?));
        }
        Ok(out)
    }
    fn publish<T: serde::Serialize + ?Sized>(
        &self,
        name: &str,
        value: &T,
        immutable: bool,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<()> {
        check()?;
        let temporary = format!(
            ".pending-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        );
        let mut file = self.open(&temporary, libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL)?;
        let outcome = (|| {
            {
                let mut output = BoundedWriter {
                    file: &mut file,
                    written: 0,
                    check: &mut *check,
                };
                serde_json::to_writer_pretty(&mut output, value)?;
                output.write_all(b"\n")?;
                output.flush()?;
            }
            file.sync_all()?;
            let source = cstring(&temporary)?;
            let target = cstring(name)?;
            check()?;
            let result = if immutable {
                unsafe {
                    libc::linkat(
                        self.file.as_raw_fd(),
                        source.as_ptr(),
                        self.file.as_raw_fd(),
                        target.as_ptr(),
                        0,
                    )
                }
            } else {
                unsafe {
                    libc::renameat(
                        self.file.as_raw_fd(),
                        source.as_ptr(),
                        self.file.as_raw_fd(),
                        target.as_ptr(),
                    )
                }
            };
            if result < 0 {
                return Err(std::io::Error::last_os_error().into());
            }
            self.file.sync_all()?;
            Ok(())
        })();
        let temporary = cstring(&temporary)?;
        unsafe { libc::unlinkat(self.file.as_raw_fd(), temporary.as_ptr(), 0) };
        outcome
    }
}
fn cstring(value: &str) -> Result<CString> {
    CString::new(value).map_err(|_| invalid("invalid check reference"))
}
struct Lock(File);
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe { libc::flock(self.0.as_raw_fd(), libc::LOCK_UN) };
    }
}
impl Store {
    pub fn new(root: &Path) -> Result<Self> {
        let root = root.canonicalize()?;
        super::snapshot::confined(&root, ".ken/checks")?;
        Ok(Self {
            base: root.join(".ken/checks"),
            root,
        })
    }
    pub fn path(&self, kind: &str, key: &str) -> Result<PathBuf> {
        if !["rules", "runs"].contains(&kind) || !valid_id(key) {
            return Err(invalid("invalid check reference"));
        }
        super::snapshot::confined(&self.root, &format!(".ken/checks/{kind}/{key}.json"))
    }
    fn directory(&self, kind: Option<&str>, create: bool) -> Result<Directory> {
        let root = Directory::root(&self.root)?;
        let ken = root.child(".ken", create)?;
        let base = ken.child("checks", create)?;
        match kind {
            Some(kind) => base.child(kind, create),
            None => Ok(base),
        }
    }
    fn read_typed<T: serde::de::DeserializeOwned>(
        &self,
        kind: &str,
        key: &str,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<T> {
        check()?;
        self.path(kind, key)?;
        let dir = self.directory(Some(kind), false)?;
        let file = dir.open(&format!("{key}.json"), libc::O_RDONLY)?;
        let mut data = Vec::new();
        let mut reader = file.take(16000001);
        let mut chunk = [0u8; 8192];
        loop {
            check()?;
            let count = reader.read(&mut chunk)?;
            if count == 0 {
                break;
            }
            data.extend_from_slice(&chunk[..count]);
        }
        if data.len() > 16000000 {
            return Err(invalid("check record exceeds 16 MB"));
        }
        check()?;
        let value = serde_json::from_slice(&data)?;
        check()?;
        Ok(value)
    }
    pub fn read(&self, kind: &str, key: &str) -> Result<Value> {
        self.read_checked(kind, key, &mut || Ok(()))
    }
    pub fn read_checked(
        &self,
        kind: &str,
        key: &str,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Value> {
        let value: Value = self.read_typed(kind, key, check)?;
        if !value.is_object() || value["version"] != 1 {
            return Err(invalid("unsupported check record"));
        }
        Ok(value)
    }
    pub fn read_receipt(&self, key: &str) -> Result<super::Receipt> {
        self.read_receipt_checked(key, &mut || Ok(()))
    }
    pub fn read_receipt_checked(
        &self,
        key: &str,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<super::Receipt> {
        let receipt: super::Receipt = self.read_typed("runs", key, check)?;
        if receipt.version != 1 || receipt.run_id != key {
            return Err(invalid("invalid check receipt identity"));
        }
        Ok(receipt)
    }
    pub fn write_receipt(&self, receipt: &super::Receipt) -> Result<()> {
        self.write_receipt_checked(receipt, &mut || Ok(()))
    }
    pub fn write_receipt_checked(
        &self,
        receipt: &super::Receipt,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<()> {
        check()?;
        let _guard = self.lock_checked(check)?;
        self.path("runs", &receipt.run_id)?;
        if receipt.version != 1 {
            return Err(invalid("unsupported check record"));
        }
        self.directory(Some("runs"), true)?.publish(
            &format!("{}.json", receipt.run_id),
            receipt,
            true,
            check,
        )
    }
    pub fn latest_receipt(&self) -> Result<Option<super::Receipt>> {
        self.run_ids()?
            .first()
            .map(|id| self.read_receipt(id))
            .transpose()
    }

    pub fn rules(&self) -> Result<Vec<Value>> {
        self.rules_checked(&mut || Ok(()))
    }
    pub fn rules_checked(&self, check: &mut dyn FnMut() -> Result<()>) -> Result<Vec<Value>> {
        check()?;
        let dir = match self.directory(Some("rules"), false) {
            Ok(dir) => dir,
            Err(super::Error::Io(e)) if e.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Vec::new());
            }
            Err(e) => return Err(e),
        };
        let mut entries = dir.entries(check)?;
        entries.sort_by(|a, b| a.0.cmp(&b.0));
        let mut out = Vec::new();
        for (key, _) in entries {
            check()?;
            let record = self.read_checked("rules", &key, check)?;
            let rule = Rule::read(&record["definition"])?;
            if rule.id != key {
                return Err(invalid("rule id does not match filename"));
            }
            if !record["enabled"].is_boolean()
                || !record["automatic"].is_boolean()
                || record.get("validation").is_none()
            {
                return Err(invalid("invalid rule record"));
            }
            out.push(record);
        }
        Ok(out)
    }
    pub fn run_ids(&self) -> Result<Vec<String>> {
        self.run_ids_checked(&mut || Ok(()))
    }
    pub fn run_ids_checked(&self, check: &mut dyn FnMut() -> Result<()>) -> Result<Vec<String>> {
        check()?;
        let dir = match self.directory(Some("runs"), false) {
            Ok(dir) => dir,
            Err(super::Error::Io(e)) if e.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Vec::new());
            }
            Err(e) => return Err(e),
        };
        let mut entries = dir.entries(check)?;
        entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| b.0.cmp(&a.0)));
        Ok(entries.into_iter().map(|(id, _)| id).collect())
    }
    pub fn latest(&self) -> Result<Option<Value>> {
        self.run_ids()?
            .first()
            .map(|id| self.read("runs", id))
            .transpose()
    }
    pub fn write_run(&self, key: &str, value: &Value) -> Result<()> {
        self.path("runs", key)?;
        if value["version"] != 1 {
            return Err(invalid("unsupported check record"));
        }
        self.directory(Some("runs"), true)?.publish(
            &format!("{key}.json"),
            value,
            true,
            &mut || Ok(()),
        )
    }
    fn lock_checked(&self, check: &mut dyn FnMut() -> Result<()>) -> Result<Lock> {
        check()?;
        let dir = self.directory(None, true)?;
        let file = dir.open(".lock", libc::O_RDWR | libc::O_CREAT)?;
        loop {
            check()?;
            if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
                return Ok(Lock(file));
            }
            let e = std::io::Error::last_os_error();
            if !matches!(
                e.kind(),
                std::io::ErrorKind::Interrupted | std::io::ErrorKind::WouldBlock
            ) {
                return Err(e.into());
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }
    pub fn save_rule(&self, record: &Value, previous: Option<&Value>) -> Result<()> {
        self.save_rule_checked(record, previous, &mut || Ok(()))
    }
    pub fn save_rule_checked(
        &self,
        record: &Value,
        previous: Option<&Value>,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<()> {
        check()?;
        let rule = Rule::read(&record["definition"])?;
        if record["version"] != 1 {
            return Err(invalid("unsupported check record"));
        }
        let _guard = self.lock_checked(check)?;
        self.path("rules", &rule.id)?;
        let current = match self.read_checked("rules", &rule.id, check) {
            Ok(r) => Some(r),
            Err(super::Error::Io(e)) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => return Err(e),
        };
        if current.as_ref() != previous {
            return Err(invalid(
                "rule changed concurrently; read it before retrying",
            ));
        }
        self.directory(Some("rules"), true)?.publish(
            &format!("{}.json", rule.id),
            record,
            false,
            check,
        )
    }
}
