//! One bounded native child, with simultaneous nonblocking pipe progress.
use crate::{Error, Result, WorkerControl, WorkerLimits, WorkerProgram};
use std::{
    io::{Read, Write},
    os::{fd::AsRawFd, unix::process::CommandExt},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};
struct ChildOwner {
    child: Child,
    group: i32,
    reaped: bool,
    finished: bool,
}
impl ChildOwner {
    fn stop(&mut self) {
        if self.group > 0 {
            unsafe { libc::kill(-self.group, libc::SIGKILL) };
            self.group = 0;
        }
        let _ = self.child.kill();
        if !self.reaped {
            let _ = self.child.wait();
            self.reaped = true;
        }
    }
}
impl Drop for ChildOwner {
    fn drop(&mut self) {
        if !self.finished {
            self.stop();
        }
    }
}
fn nonblocking(fd: i32) -> Result<()> {
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}
fn read_pipe(
    reader: &mut impl Read,
    output: &mut Vec<u8>,
    maximum: usize,
    tail: bool,
) -> Result<bool> {
    let mut buffer = [0u8; 8192];
    for _ in 0..8 {
        match reader.read(&mut buffer) {
            Ok(0) => return Ok(true),
            Ok(n) => {
                if tail {
                    if maximum == 0 {
                        continue;
                    }
                    if n >= maximum {
                        output.clear();
                        output.extend_from_slice(&buffer[n - maximum..n]);
                    } else {
                        let excess = output.len().saturating_add(n).saturating_sub(maximum);
                        if excess > 0 {
                            drop(output.drain(..excess));
                        }
                        output.extend_from_slice(&buffer[..n]);
                    }
                } else {
                    if n > maximum.saturating_sub(output.len()) {
                        return Err(Error::Worker(
                            "query worker response exceeds configured byte limit".into(),
                        ));
                    }
                    output.extend_from_slice(&buffer[..n]);
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => return Ok(false),
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Ok(false)
}
pub(crate) fn invoke(
    program: &WorkerProgram,
    limits: &WorkerLimits,
    input: &[u8],
    deadline: Instant,
    control: &WorkerControl,
) -> Result<Vec<u8>> {
    if input.len() > limits.max_request_bytes {
        return Err(Error::Worker(
            "query worker request exceeds configured byte limit".into(),
        ));
    }
    if control.cancellation.is_cancelled() {
        return Err(Error::Cancelled);
    }
    if Instant::now() >= deadline {
        return Err(Error::Timeout);
    }
    let directory = program
        .executable
        .parent()
        .ok_or_else(|| Error::Invalid("query worker has no trusted directory".into()))?;
    let child = Command::new(&program.executable)
        .args(&program.arguments)
        .current_dir(directory)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()?;
    let group = i32::try_from(child.id())
        .map_err(|_| Error::Worker("invalid native worker process id".into()))?;
    let mut child = ChildOwner {
        child,
        group,
        reaped: false,
        finished: false,
    };
    let mut stdin = child.child.stdin.take();
    let mut stdout = child
        .child
        .stdout
        .take()
        .ok_or_else(|| Error::Worker("query worker stdout unavailable".into()))?;
    let mut stderr = child
        .child
        .stderr
        .take()
        .ok_or_else(|| Error::Worker("query worker stderr unavailable".into()))?;
    if let Some(stdin) = &stdin {
        nonblocking(stdin.as_raw_fd())?;
    }
    nonblocking(stdout.as_raw_fd())?;
    nonblocking(stderr.as_raw_fd())?;
    let (mut written, mut out, mut errors, mut output_done, mut error_done, mut status) =
        (0, Vec::new(), Vec::new(), false, false, None);
    loop {
        if control.cancellation.is_cancelled() {
            child.stop();
            return Err(Error::Cancelled);
        }
        if Instant::now() >= deadline {
            child.stop();
            return Err(Error::Timeout);
        }
        if let Some(writer) = &mut stdin {
            match writer.write(&input[written..]) {
                Ok(n) => {
                    written += n;
                    if written == input.len() {
                        stdin.take();
                    }
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) => {}
                Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => {
                    stdin.take();
                }
                Err(error) => return Err(error.into()),
            }
        }
        if !output_done {
            output_done = read_pipe(&mut stdout, &mut out, limits.max_response_bytes, false)?;
        }
        if !error_done {
            error_done = read_pipe(&mut stderr, &mut errors, limits.max_stderr_bytes, true)?;
        }
        if status.is_none() {
            status = child.child.try_wait()?;
            if status.is_some() {
                child.reaped = true;
            }
        }
        if let Some(status) = status
            && output_done
            && error_done
        {
            if Instant::now() >= deadline {
                return Err(Error::Timeout);
            }
            if !status.success() {
                return Err(Error::Worker(format!(
                    "query worker exited {}: {}",
                    status
                        .code()
                        .map(|n| n.to_string())
                        .unwrap_or_else(|| "by signal".into()),
                    String::from_utf8_lossy(&errors)
                )));
            }
            child.stop();
            child.finished = true;
            return Ok(out);
        }
        std::thread::sleep(
            deadline
                .saturating_duration_since(Instant::now())
                .min(Duration::from_millis(3)),
        );
    }
}
