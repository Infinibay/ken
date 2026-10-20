//! Read exactly a declared regular artifact, retaining the verified bytes.
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    io::{Read, Write},
    path::Path,
};

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
    let mut bytes = Vec::new();
    copy(path, expected_bytes, expected_sha256, &mut bytes)?;
    Ok(bytes)
}

pub(crate) fn open_regular(path: &Path, expected_bytes: u64) -> Result<File, VerificationError> {
    expected_bytes
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
    Ok(file)
}

/// Copy and hash the same opened regular inode with a fixed memory bound.
pub(crate) fn copy<W: Write>(
    path: &Path,
    expected_bytes: u64,
    expected_sha256: &str,
    destination: &mut W,
) -> Result<(), VerificationError> {
    let file = open_regular(path, expected_bytes)?;
    copy_stream(
        file.take(expected_bytes + 1),
        expected_bytes,
        expected_sha256,
        destination,
    )
}

fn copy_stream<R: Read, W: Write>(
    mut source: R,
    expected_bytes: u64,
    expected_sha256: &str,
    destination: &mut W,
) -> Result<(), VerificationError> {
    let mut buffer = [0_u8; 64 * 1024];
    let mut count = 0_u64;
    let mut digest = Sha256::new();
    loop {
        let size = match source.read(&mut buffer) {
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            result => result?,
        };
        if size == 0 {
            break;
        }
        count += size as u64;
        digest.update(&buffer[..size]);
        destination.write_all(&buffer[..size])?;
    }
    if count != expected_bytes {
        return Err(VerificationError::Invalid(
            "artifact size changed during read",
        ));
    }
    if format!("{:x}", digest.finalize()) != expected_sha256 {
        return Err(VerificationError::Invalid("artifact hash mismatch"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct InterruptedRead(File, bool);

    impl Read for InterruptedRead {
        fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
            if !self.1 {
                self.1 = true;
                return Err(std::io::ErrorKind::Interrupted.into());
            }
            self.0.read(buffer)
        }
    }

    #[test]
    fn an_interrupted_regular_file_read_is_retried() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("weights");
        std::fs::write(&path, b"abc").unwrap();
        let source = InterruptedRead(open_regular(&path, 3).unwrap(), false);
        let mut copied = Vec::new();
        copy_stream(
            source.take(4),
            3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            &mut copied,
        )
        .unwrap();
        assert_eq!(copied, b"abc");
    }
}
