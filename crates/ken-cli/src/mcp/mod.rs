//! Pinned SDK-compatible stdio negotiation with caller-owned native tool services.
mod framing;
mod protocol;
mod transport;
use crate::tools::{ToolService, definitions};
use ken_core::project::{DiscoveryContext, ProjectPaths, locate_project};
use ken_query::execution::Cancellation;
use serde_json::{Value, value::RawValue};
use std::{
    fs::File,
    io,
    os::fd::FromRawFd,
    path::{Path, PathBuf},
};
pub use transport::serve_transport;
/// A tool owner stays on the caller thread; models and SQLite need not be Send.
pub trait ToolHandler {
    fn definitions(&self) -> Vec<Value>;
    fn call(
        &mut self,
        name: &str,
        arguments: &RawValue,
        cancellation: Cancellation,
    ) -> Result<String, String>;
}
struct NativeTools(ToolService);
impl ToolHandler for NativeTools {
    fn definitions(&self) -> Vec<Value> {
        definitions()
    }
    fn call(
        &mut self,
        name: &str,
        arguments: &RawValue,
        cancellation: Cancellation,
    ) -> Result<String, String> {
        self.0
            .call_with_control(name, arguments, cancellation)
            .map(|reply| reply.into_text())
    }
}
pub fn run(
    start: &Path,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<(), Box<dyn std::error::Error>> {
    let paths = match locate_project(start, context)? {
        Some(paths) => paths,
        None => ProjectPaths::at(start, context)?,
    };
    if !paths.meta().is_file() {
        return Err(
            io::Error::other(format!("no .ken project at {}", paths.root().display())).into(),
        );
    }
    let mut tools = NativeTools(ToolService::new(paths, installation));
    fn duplicate(fd: i32) -> io::Result<File> {
        let owned = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 3) };
        if owned < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(unsafe { File::from_raw_fd(owned) })
        }
    }
    serve_transport(duplicate(0)?, duplicate(1)?, &mut tools)?;
    Ok(())
}
