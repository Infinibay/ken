//! Bounded, read-only Git observation. No shell, hooks, checkout or mutation.
use super::IngestOptions;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use std::{
    collections::BTreeSet,
    io::{self, Read},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::Instant,
};

pub(super) struct Commit {
    pub sha: String,
    pub ts: i64,
    pub author: String,
    pub subject: String,
    pub files: Vec<String>,
}

pub(super) fn repositories(paths: &ProjectPaths, options: &IngestOptions) -> Vec<String> {
    if options.cancellation.is_cancelled() {
        return Vec::new();
    }
    if let Some(path) = options.only_path.as_deref().filter(|p| !p.is_empty()) {
        let Ok(context) = DiscoveryContext::from_process() else {
            return Vec::new();
        };
        let Ok(resolved) = paths.resolve_inside(Path::new(path), &context) else {
            return Vec::new();
        };
        let Some(mut directory) = resolved.parent() else {
            return Vec::new();
        };
        while directory.starts_with(paths.root()) {
            if directory.join(".git").exists() {
                return vec![
                    directory
                        .strip_prefix(paths.root())
                        .unwrap_or(Path::new(""))
                        .to_string_lossy()
                        .into_owned(),
                ];
            }
            if directory == paths.root() {
                break;
            }
            let Some(parent) = directory.parent() else {
                break;
            };
            directory = parent;
        }
        return Vec::new();
    }
    let mut repos = Vec::new();
    let mut seen = BTreeSet::new();
    discover(
        paths.root(),
        paths.root(),
        0,
        &mut seen,
        &mut repos,
        options,
    );
    repos
}
fn discover(
    root: &Path,
    directory: &Path,
    depth: usize,
    seen: &mut BTreeSet<PathBuf>,
    repos: &mut Vec<String>,
    options: &IngestOptions,
) {
    if options.cancellation.is_cancelled() {
        return;
    }
    let Ok(canonical) = std::fs::canonicalize(directory) else {
        return;
    };
    if !canonical.starts_with(root) || !seen.insert(canonical) {
        return;
    }
    if directory.join(".git").exists() {
        repos.push(
            directory
                .strip_prefix(root)
                .unwrap_or(Path::new(""))
                .to_string_lossy()
                .into_owned(),
        );
        return;
    }
    if depth >= 3 {
        return;
    }
    let Ok(entries) = std::fs::read_dir(directory) else {
        return;
    };
    let mut directories: Vec<_> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .collect();
    directories.sort_by_key(|e| e.file_name());
    for entry in directories {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with('.')
            || [
                "node_modules",
                "dist",
                "build",
                "out",
                "target",
                "vendor",
                "venv",
                "__pycache__",
            ]
            .contains(&name.as_ref())
        {
            continue;
        }
        discover(root, &entry.path(), depth + 1, seen, repos, options);
    }
}
struct Process(Child, bool);
impl Process {
    fn stop(&mut self) {
        if !self.1 {
            return;
        }
        #[cfg(unix)]
        unsafe {
            libc::kill(-(self.0.id() as i32), libc::SIGKILL);
        }
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        self.stop();
    }
}

pub(super) fn log(
    root: &Path,
    range: &str,
    options: &IngestOptions,
) -> std::result::Result<Vec<Commit>, String> {
    if options.cancellation.is_cancelled() {
        return Err("cancelled".into());
    }
    let start = Instant::now();
    let program = ken_core::native_program::git_program()
        .map_err(|error| format!("git unavailable: {error}"))?;
    let mut command = Command::new(program);
    command
        .arg("--no-pager")
        .arg("log")
        .args(["--no-merges", "--find-renames", "--no-color"])
        .arg(format!("--max-count={}", options.max_commits))
        .arg("--pretty=format:\u{1}%H%x1f%ct%x1f%an%x1f%s")
        .arg("--name-only")
        .arg("--end-of-options")
        .arg(range)
        .current_dir(root)
        .env("GIT_OPTIONAL_LOCKS", "0")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let child = command
        .spawn()
        .map_err(|e| format!("git unavailable: {e}"))?;
    let mut process = Process(child, true);
    let mut stdout = process.0.stdout.take().ok_or("git stdout unavailable")?;
    #[cfg(unix)]
    {
        use std::os::fd::AsRawFd;
        let fd = stdout.as_raw_fd();
        // Nonblocking draining keeps cancellation/timeout live while Git is
        // silent and while descendants retain a pipe after the parent exits.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(format!("git pipe: {}", io::Error::last_os_error()));
        }
    }
    #[cfg(not(unix))]
    return Err("bounded Git observation is supported on Unix only".into());
    let mut output = Vec::new();
    let mut exited = None;
    let mut eof = false;
    loop {
        if options.cancellation.is_cancelled() {
            return Err("cancelled".into());
        }
        if start.elapsed() >= options.timeout {
            return Err("git timeout".into());
        }
        let mut bytes = [0u8; 16384];
        // Poll between reads too: a continuously busy stdout must not postpone
        // cancellation or overflow the explicit output bound.
        match stdout.read(&mut bytes) {
            Ok(0) => eof = true,
            Ok(n) => {
                if n > options.max_output_bytes.saturating_sub(output.len()) {
                    return Err("git output limit exceeded".into());
                }
                output.extend_from_slice(&bytes[..n]);
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(format!("git pipe: {e}")),
        }
        if exited.is_none() {
            exited = process.0.try_wait().map_err(|e| format!("git wait: {e}"))?;
        }
        if let Some(status) = exited
            && eof
        {
            if !status.success() {
                return Err(format!("git exited {status}"));
            }
            process.1 = false;
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(2));
    }
    Ok(parse(&String::from_utf8_lossy(&output)))
}
fn parse(text: &str) -> Vec<Commit> {
    let mut commits = Vec::new();
    let mut current: Option<Commit> = None;
    for line in crate::source_lines(text) {
        if let Some(header) = line.strip_prefix('\u{1}') {
            if let Some(commit) = current.take() {
                commits.push(commit);
            }
            let mut fields = header.split('\u{1f}');
            current = Some(Commit {
                sha: fields.next().unwrap_or("").into(),
                ts: fields.next().unwrap_or("").parse().unwrap_or(0),
                author: fields.next().unwrap_or("").into(),
                subject: fields.next().unwrap_or("").into(),
                files: Vec::new(),
            });
        } else if !line.trim().is_empty()
            && let Some(commit) = current.as_mut()
        {
            commit.files.push(crate::normalize(line.trim()));
        }
    }
    if let Some(commit) = current {
        commits.push(commit);
    }
    commits
}
