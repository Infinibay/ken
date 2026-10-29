//! Bounded Git worktree observation, enriched only with indexed facts.
use super::{IndexNavigation, Result};
use ken_core::tool_output::Document;
use ken_text::unicode::splitlines;
use std::{
    io::Read,
    process::{Child, Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

impl IndexNavigation {
    pub fn changed_context(&self) -> Result<Document> {
        let mut command = Command::new("git");
        command
            .args(["status", "--porcelain=v1"])
            .current_dir(self.paths.root());
        let output = collect(command, Duration::from_secs(5)).unwrap_or_default();
        let text = String::from_utf8_lossy(&output)
            .replace("\r\n", "\n")
            .replace('\r', "\n");
        let mut changed = Vec::new();
        for line in splitlines(&text)
            .into_iter()
            .filter(|line| !line.is_empty())
        {
            let status = line.chars().take(2).collect::<String>();
            let path = line.chars().skip(3).collect::<String>();
            // Preserve the original porcelain-v1 quoting/rename interpretation.
            let path = path.split_once(" -> ").map_or(path.as_str(), |(_, to)| to);
            let file = self.file(path)?;
            let (outline, tests) = if let Some(file) = &file {
                let mut outline = self.indexed_symbols(file.id, false)?;
                outline.truncate(8);
                (outline, self.tests_for(file, 8)?)
            } else {
                (Vec::new(), Vec::new())
            };
            changed.push(doc!("status":status,"path":path,"indexed":file.is_some(),"symbols":outline,"tests":tests));
        }
        Ok(doc!("ok":true,"changed":changed))
    }
}

/// Drain stdout while waiting, so a large status cannot deadlock on pipe capacity.
/// The deadline includes draining after process exit. Kill the owned process
/// group on Unix so Git helpers cannot retain the pipe beyond that deadline.
fn collect(mut command: Command, timeout: Duration) -> Option<Vec<u8>> {
    command.stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command.spawn().ok()?;
    let mut output = child.stdout.take()?;
    let (tx, rx) = mpsc::channel();
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = output.read_to_end(&mut bytes).map(|_| bytes);
        let _ = tx.send(result);
    });
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(5)),
            _ => break None,
        }
    };
    let bytes = if status.is_some_and(|s| s.success()) {
        rx.recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .ok()
            .and_then(std::result::Result::ok)
    } else {
        None
    };
    if bytes.is_none() {
        terminate(&mut child);
    }
    let _ = child.wait();
    let _ = reader.join();
    bytes
}
fn terminate(child: &mut Child) {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.kill();
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    #[test]
    fn status_collection_drains_large_output_and_bounds_helper_lifetime() {
        let mut large = Command::new("/bin/sh");
        large.args(["-c", "head -c 200000 /dev/zero"]);
        assert_eq!(
            collect(large, Duration::from_secs(2)).unwrap().len(),
            200000
        );
        let mut hanging = Command::new("/bin/sh");
        hanging.args(["-c", "sleep 30 & exit 0"]);
        let start = Instant::now();
        assert!(collect(hanging, Duration::from_millis(50)).is_none());
        assert!(start.elapsed() < Duration::from_secs(2));
    }
}
