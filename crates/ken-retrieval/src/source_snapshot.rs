//! A physical source version is read through one confined regular-file handle.
use crate::Span;
use ken_core::{project::ProjectPaths, source_reader::SourceFileReader};
use ken_text::unicode::splitlines;
use sha2::{Digest, Sha256};
use std::{
    io,
    path::{Path, PathBuf},
};

#[derive(Debug, thiserror::Error)]
pub enum SourceError {
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Decode(String),
    #[error(transparent)]
    Io(#[from] io::Error),
}
pub type SourceResult<T> = std::result::Result<T, SourceError>;
impl SourceError {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Invalid(_) => "ValueError",
            Self::Decode(_) => "UnicodeDecodeError",
            Self::Io(e) => match e.kind() {
                io::ErrorKind::NotFound => "FileNotFoundError",
                io::ErrorKind::PermissionDenied => "PermissionError",
                _ => "OSError",
            },
        }
    }
}
pub(crate) fn invalid(message: impl Into<String>) -> SourceError {
    SourceError::Invalid(message.into())
}
fn decode_error(bytes: &[u8], error: std::str::Utf8Error) -> SourceError {
    let start = error.valid_up_to();
    let size = error.error_len().unwrap_or(bytes.len() - start);
    let reason = if error.error_len().is_none() {
        "unexpected end of data"
    } else if (0xc2..=0xf4).contains(&bytes[start]) {
        "invalid continuation byte"
    } else {
        "invalid start byte"
    };
    let position = if size == 1 {
        format!("byte 0x{:02x} in position {start}", bytes[start])
    } else {
        format!("bytes in position {start}-{}", start + size - 1)
    };
    SourceError::Decode(format!("'utf-8' codec can't decode {position}: {reason}"))
}
pub struct SourceAuthority {
    reader: SourceFileReader,
    root: PathBuf,
}
impl SourceAuthority {
    pub fn new(paths: &ProjectPaths) -> SourceResult<Self> {
        Ok(Self {
            reader: SourceFileReader::new(paths)?,
            root: paths.root().to_owned(),
        })
    }
    pub(crate) fn location(&self, path: &str) -> PathBuf {
        self.root.join(path)
    }
    pub fn read(&self, path: &str) -> SourceResult<SourceSnapshot> {
        let source = self.reader.open(Path::new(path)).map_err(|error| {
            if error.kind() == io::ErrorKind::PermissionDenied && error.raw_os_error().is_none() {
                invalid("source outside root")
            } else {
                error.into()
            }
        })?;
        let bytes = source.read()?;
        let text = std::str::from_utf8(&bytes).map_err(|error| decode_error(&bytes, error))?;
        Ok(SourceSnapshot {
            hash: format!("{:x}", Sha256::digest(&bytes)),
            lines: splitlines(text).into_iter().map(str::to_owned).collect(),
        })
    }
}
#[derive(Clone, Debug)]
pub struct SourceSnapshot {
    hash: String,
    lines: Vec<String>,
}
impl SourceSnapshot {
    pub fn hash(&self) -> &str {
        &self.hash
    }
    pub fn lines(&self) -> &[String] {
        &self.lines
    }
    pub fn verify(&self, required_hash: &str) -> SourceResult<()> {
        if self.hash != required_hash {
            return Err(invalid("source changed"));
        }
        Ok(())
    }
    pub fn excerpt(&self, span: Span) -> SourceResult<String> {
        if span.start_line == 0
            || span.start_line > span.end_line
            || span.end_line > self.lines.len()
        {
            return Err(invalid("invalid source range"));
        }
        Ok(self.lines[span.start_line - 1..span.end_line].join("\n"))
    }
}
