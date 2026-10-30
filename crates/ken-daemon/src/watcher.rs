//! Recursive Linux events with a polling reconciliation fallback.
use crate::{
    Error, Result,
    queue::{Action, QueueSender},
};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_filter::SourceFilter,
    source_walk::ProjectSources,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::{CString, OsString},
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::{
            ffi::{OsStrExt, OsStringExt},
            fs::MetadataExt,
        },
    },
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
struct Core {
    root: PathBuf,
    sender: QueueSender,
    filter: Mutex<SourceFilter>,
    generation: AtomicU64,
    closed: AtomicBool,
}
impl Core {
    fn observe(&self, events: Vec<(Action, PathBuf)>) -> Result<()> {
        if self.closed.load(Ordering::Acquire) {
            return Err(Error::Closed);
        }
        let mut changes = Vec::new();
        let mut reload = false;
        let mut dirs = false;
        let mut filter = self.filter.lock().unwrap_or_else(|e| e.into_inner());
        for (action, path) in events {
            let Ok(relative) = path.strip_prefix(&self.root) else {
                continue;
            };
            if relative
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
            {
                continue;
            }
            let relative_text = relative.to_string_lossy().into_owned();
            if relative_text == ".kenignore"
                || relative.file_name().is_some_and(|n| n == ".gitignore")
            {
                reload = true;
                continue;
            }
            if filter.is_ignored(relative, false).map_err(crate::invalid)?
                || filter.is_ignored(relative, true).map_err(crate::invalid)?
            {
                continue;
            }
            if path.is_dir() {
                dirs = true;
            }
            changes.push((action, relative_text));
        }
        if reload {
            *filter = SourceFilter::new(&self.root).map_err(crate::invalid)?;
        }
        drop(filter);
        if reload || dirs || changes.len() >= 512 {
            self.generation.fetch_add(1, Ordering::AcqRel);
            return self.sender.resync();
        }
        for (action, relative) in changes {
            match action {
                Action::Reindex => self.sender.reindex(&relative)?,
                Action::Delete => self.sender.delete(&relative)?,
            }
        }
        Ok(())
    }
}
pub struct FileWatcher {
    core: Arc<Core>,
    worker: Option<JoinHandle<()>>,
}
impl FileWatcher {
    pub fn start(root: &Path, sender: QueueSender) -> Result<Self> {
        let root = root.canonicalize()?;
        let core = Arc::new(Core {
            filter: Mutex::new(SourceFilter::new(&root).map_err(crate::invalid)?),
            root,
            sender,
            generation: AtomicU64::new(0),
            closed: AtomicBool::new(false),
        });
        let thread_core = core.clone();
        let (tx, rx) = mpsc::sync_channel(1);
        let worker = thread::Builder::new()
            .name("ken-watcher".into())
            .spawn(move || match Snapshot::capture(&thread_core.root) {
                Ok(snapshot) => {
                    let fd = unsafe { libc::inotify_init1(libc::IN_NONBLOCK | libc::IN_CLOEXEC) };
                    if fd >= 0 {
                        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
                        match subscribe(&fd, &snapshot.directories) {
                            Ok(watches) => {
                                let _ = tx.send(Ok(()));
                                inotify(thread_core, fd, watches, snapshot);
                            }
                            Err(e) => {
                                eprintln!("ken inotify unavailable, polling: {e}");
                                let _ = tx.send(Ok(()));
                                poll(thread_core, snapshot);
                            }
                        }
                    } else {
                        let _ = tx.send(Ok(()));
                        poll(thread_core, snapshot);
                    }
                }
                Err(error) => {
                    let _ = tx.send(Err(error));
                }
            })?;
        match rx.recv() {
            Ok(Ok(())) => Ok(Self {
                core,
                worker: Some(worker),
            }),
            Ok(Err(error)) => {
                core.closed.store(true, Ordering::Release);
                let _ = worker.join();
                Err(error)
            }
            Err(_) => {
                let _ = worker.join();
                Err(Error::Invalid("watcher startup failed".into()))
            }
        }
    }
    pub fn observe(&mut self, events: Vec<(Action, PathBuf)>) -> Result<()> {
        self.core.observe(events)
    }
    pub fn stop(&mut self) -> Result<()> {
        self.core.closed.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| Error::Invalid("watcher worker panicked".into()))?;
        }
        Ok(())
    }
}
impl Drop for FileWatcher {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}
#[derive(Clone, PartialEq, Eq)]
struct Stamp {
    modified: u128,
    len: u64,
    inode: u64,
}
struct Snapshot {
    files: BTreeMap<PathBuf, Stamp>,
    directories: BTreeSet<PathBuf>,
}
impl Snapshot {
    fn capture(root: &Path) -> Result<Self> {
        let context = DiscoveryContext {
            cwd: root.into(),
            home: None,
            forced_root: None,
        };
        let paths = ProjectPaths::at(root, &context).map_err(crate::invalid)?;
        let mut directories = BTreeSet::from([root.to_owned()]);
        let mut files = BTreeMap::new();
        let sources = ProjectSources::new(paths, context);
        for entry in sources.walk(Path::new(".")).map_err(crate::invalid)? {
            let entry = entry.map_err(crate::invalid)?;
            let path = root.join(&entry.path);
            if entry.is_dir {
                directories.insert(path);
            } else {
                stamp(&path, &mut files)?;
            }
        }
        // Control files remain observable even if a rule excludes dotfiles themselves.
        for directory in &directories {
            stamp_optional(&directory.join(".gitignore"), &mut files)?;
        }
        stamp_optional(&root.join(".kenignore"), &mut files)?;
        Ok(Self { files, directories })
    }
    fn diff(&self, new: &Self) -> Vec<(Action, PathBuf)> {
        let mut result = Vec::new();
        for (path, stamp) in &new.files {
            if self.files.get(path) != Some(stamp) {
                result.push((Action::Reindex, path.clone()));
            }
        }
        for path in self.files.keys() {
            if !new.files.contains_key(path) {
                result.push((Action::Delete, path.clone()));
            }
        }
        result
    }
}
fn stamp(path: &Path, files: &mut BTreeMap<PathBuf, Stamp>) -> Result<()> {
    let meta = std::fs::metadata(path)?;
    if meta.is_file() {
        files.insert(
            path.into(),
            Stamp {
                modified: meta
                    .modified()
                    .unwrap_or(SystemTime::UNIX_EPOCH)
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos(),
                len: meta.len(),
                inode: meta.ino(),
            },
        );
    }
    Ok(())
}
fn stamp_optional(path: &Path, files: &mut BTreeMap<PathBuf, Stamp>) -> Result<()> {
    match stamp(path, files) {
        Err(Error::Io(e)) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        value => value,
    }
}
fn poll(core: Arc<Core>, mut previous: Snapshot) {
    while !core.closed.load(Ordering::Acquire) {
        thread::sleep(Duration::from_millis(200));
        if core.closed.load(Ordering::Acquire) {
            return;
        }
        match Snapshot::capture(&core.root) {
            Ok(next) => {
                let events = previous.diff(&next);
                if !events.is_empty()
                    && let Err(e) = core.observe(events)
                {
                    eprintln!("ken polling event failed: {e}");
                }
                previous = next;
            }
            Err(e) => eprintln!("ken source reconciliation failed: {e}"),
        }
    }
}
fn subscribe(fd: &OwnedFd, directories: &BTreeSet<PathBuf>) -> Result<BTreeMap<i32, PathBuf>> {
    let mut watches = BTreeMap::new();
    let mask = libc::IN_CREATE
        | libc::IN_MODIFY
        | libc::IN_CLOSE_WRITE
        | libc::IN_DELETE
        | libc::IN_MOVED_FROM
        | libc::IN_MOVED_TO
        | libc::IN_ATTRIB
        | libc::IN_DELETE_SELF
        | libc::IN_MOVE_SELF
        | libc::IN_ONLYDIR
        | libc::IN_DONT_FOLLOW;
    for directory in directories {
        let path = CString::new(directory.as_os_str().as_bytes()).map_err(crate::invalid)?;
        let wd = unsafe { libc::inotify_add_watch(fd.as_raw_fd(), path.as_ptr(), mask) };
        if wd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        watches.insert(wd, directory.clone());
    }
    Ok(watches)
}
fn inotify(
    core: Arc<Core>,
    fd: OwnedFd,
    mut watches: BTreeMap<i32, PathBuf>,
    mut previous: Snapshot,
) {
    let mut generation = core.generation.load(Ordering::Acquire);
    let mut bytes = vec![0u8; 64 * 1024];
    let mut ticks = 0usize;
    while !core.closed.load(Ordering::Acquire) {
        let mut pollfd = libc::pollfd {
            fd: fd.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut pollfd, 1, 100) };
        if ready < 0 {
            if std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            eprintln!("ken inotify poll failed");
            poll(core, previous);
            return;
        }
        if core.closed.load(Ordering::Acquire) {
            return;
        }
        let mut events = Vec::new();
        let mut rebuild = false;
        if ready > 0 {
            loop {
                let n =
                    unsafe { libc::read(fd.as_raw_fd(), bytes.as_mut_ptr().cast(), bytes.len()) };
                if n < 0 {
                    let e = std::io::Error::last_os_error();
                    if e.kind() == std::io::ErrorKind::WouldBlock {
                        break;
                    }
                    if e.kind() == std::io::ErrorKind::Interrupted {
                        continue;
                    }
                    eprintln!("ken inotify read failed: {e}");
                    rebuild = true;
                    break;
                }
                if n == 0 {
                    break;
                }
                let mut offset = 0usize;
                while offset + std::mem::size_of::<libc::inotify_event>() <= n as usize {
                    let event = unsafe {
                        std::ptr::read_unaligned(
                            bytes[offset..].as_ptr().cast::<libc::inotify_event>(),
                        )
                    };
                    let start = offset + std::mem::size_of::<libc::inotify_event>();
                    let end = start + event.len as usize;
                    if end > n as usize {
                        rebuild = true;
                        break;
                    }
                    offset = end;
                    if event.mask & libc::IN_Q_OVERFLOW != 0 {
                        rebuild = true;
                        continue;
                    }
                    if event.mask & libc::IN_IGNORED != 0 {
                        continue;
                    }
                    let Some(directory) = watches.get(&event.wd) else {
                        continue;
                    };
                    let name = &bytes[start..end];
                    let name = &name[..name.iter().position(|b| *b == 0).unwrap_or(name.len())];
                    let path = directory.join(OsString::from_vec(name.to_vec()));
                    if event.mask & libc::IN_ISDIR != 0
                        || event.mask & (libc::IN_DELETE_SELF | libc::IN_MOVE_SELF) != 0
                    {
                        rebuild = true;
                    }
                    let action = if event.mask
                        & (libc::IN_DELETE | libc::IN_MOVED_FROM | libc::IN_DELETE_SELF)
                        != 0
                    {
                        Action::Delete
                    } else {
                        Action::Reindex
                    };
                    events.push((action, path));
                }
            }
        }
        if !events.is_empty()
            && let Err(e) = core.observe(events)
        {
            eprintln!("ken watcher event failed: {e}");
        }
        ticks += 1;
        if ticks >= 20 || generation != core.generation.load(Ordering::Acquire) || rebuild {
            ticks = 0;
            match Snapshot::capture(&core.root) {
                Ok(next) => {
                    let diff = previous.diff(&next);
                    if !diff.is_empty()
                        && let Err(e) = core.observe(diff)
                    {
                        eprintln!("ken watcher reconciliation failed: {e}");
                    }
                    if rebuild
                        || generation != core.generation.load(Ordering::Acquire)
                        || next.directories != previous.directories
                    {
                        if rebuild {
                            let _ = core.sender.resync();
                        }
                        for wd in watches.keys() {
                            unsafe { libc::inotify_rm_watch(fd.as_raw_fd(), *wd) };
                        }
                        match subscribe(&fd, &next.directories) {
                            Ok(next_watches) => watches = next_watches,
                            Err(e) => {
                                eprintln!("ken inotify resubscribe failed: {e}");
                                poll(core, next);
                                return;
                            }
                        }
                    }
                    generation = core.generation.load(Ordering::Acquire);
                    previous = next;
                }
                Err(e) => eprintln!("ken watcher rescan failed: {e}"),
            }
        }
    }
}
