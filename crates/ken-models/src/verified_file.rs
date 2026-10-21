//! Read exactly a declared regular artifact, retaining the verified bytes.
use ring::digest::{Context, SHA256};
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

pub(crate) fn copy_stream<R: Read, W: Write>(
    source: R,
    expected_bytes: u64,
    expected_sha256: &str,
    destination: &mut W,
) -> Result<(), VerificationError> {
    let limit = expected_bytes
        .checked_add(1)
        .ok_or(VerificationError::Invalid("declared size overflow"))?;
    let mut source = source.take(limit);
    let mut buffer = [0_u8; 64 * 1024];
    let mut count = 0_u64;
    let mut digest = Context::new(&SHA256);
    loop {
        let size = match source.read(&mut buffer) {
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            result => result?,
        };
        if size == 0 {
            break;
        }
        count += size as u64;
        if count > expected_bytes {
            return Err(VerificationError::Invalid("artifact exceeds declared size"));
        }
        digest.update(&buffer[..size]);
        destination.write_all(&buffer[..size])?;
    }
    if count != expected_bytes {
        return Err(VerificationError::Invalid(
            "artifact size changed during read",
        ));
    }
    let digest = digest.finish();
    let actual_sha256: String = digest
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    if actual_sha256 != expected_sha256 {
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

    #[test]
    fn streaming_hash_preserves_sha256_across_partial_blocks() {
        struct ShortReads(std::io::Cursor<Vec<u8>>);
        impl Read for ShortReads {
            fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
                let length = buffer.len().min(4093);
                self.0.read(&mut buffer[..length])
            }
        }
        // The standard million-'a' vector is independent of the hash backend.
        let source = ShortReads(std::io::Cursor::new(vec![b'a'; 1_000_000]));
        let mut copied = Vec::new();
        copy_stream(
            source,
            1_000_000,
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
            &mut copied,
        )
        .unwrap();
        assert_eq!(copied, vec![b'a'; 1_000_000]);
    }

    #[test]
    fn real_file_writes_retry_interruptions_and_propagate_storage_failure() {
        struct Writer {
            file: File,
            interrupt: bool,
            remaining: usize,
        }
        impl Write for Writer {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                if self.interrupt {
                    self.interrupt = false;
                    return Err(std::io::ErrorKind::Interrupted.into());
                }
                if self.remaining == 0 {
                    return Err(std::io::Error::other("storage write failed"));
                }
                let n = bytes.len().min(self.remaining);
                let actual = self.file.write(&bytes[..n])?;
                self.remaining -= actual;
                Ok(actual)
            }
            fn flush(&mut self) -> std::io::Result<()> {
                self.file.flush()
            }
        }
        let temp = tempfile::tempdir().unwrap();
        for remaining in [2, 3] {
            let path = temp.path().join(format!("written-{remaining}"));
            let mut writer = Writer {
                file: File::create(&path).unwrap(),
                interrupt: true,
                remaining,
            };
            let result = copy_stream(
                b"abc".as_slice(),
                3,
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                &mut writer,
            );
            assert_eq!(result.is_ok(), remaining == 3);
            assert_eq!(std::fs::read(path).unwrap(), &b"abc"[..remaining]);
        }
    }
}
