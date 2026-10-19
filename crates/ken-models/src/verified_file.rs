//! Read exactly a declared regular artifact, retaining the verified bytes.
use sha2::{Digest, Sha256};
use std::{fs::OpenOptions, io::Read, path::Path};

#[derive(Debug, thiserror::Error)]
pub(crate) enum VerificationError {
    #[error("{0}")]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Invalid(&'static str),
}

pub(crate) fn read(
    path: &Path,
    expected_bytes: u64,
    expected_sha256: &str,
) -> Result<Vec<u8>, VerificationError> {
    let limit = expected_bytes
        .checked_add(1)
        .ok_or(VerificationError::Invalid("declared size overflow"))?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // Check the opened inode rather than a pre-open path. Nonblocking
        // prevents a swapped-in FIFO from waiting before that check.
        options.custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY);
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(VerificationError::Invalid("regular artifact required"));
    }
    if metadata.len() != expected_bytes {
        return Err(VerificationError::Invalid("artifact size mismatch"));
    }
    let mut bytes = Vec::new();
    file.take(limit).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != expected_bytes {
        return Err(VerificationError::Invalid(
            "artifact size changed during read",
        ));
    }
    if format!("{:x}", Sha256::digest(&bytes)) != expected_sha256 {
        return Err(VerificationError::Invalid("artifact hash mismatch"));
    }
    Ok(bytes)
}
