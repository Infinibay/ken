//! Bound physical frames independently of JSON parsing and request execution.
use std::io::{self, BufRead};
pub(super) const MAX_FRAME: usize = 8 * 1024 * 1024;
pub(super) enum Frame {
    Bytes(Vec<u8>),
    Oversized,
}
pub(super) fn read(input: &mut impl BufRead) -> io::Result<Option<Frame>> {
    let mut bytes = Vec::new();
    let mut oversized = false;
    loop {
        let buffer = input.fill_buf()?;
        if buffer.is_empty() {
            return Ok(if oversized {
                Some(Frame::Oversized)
            } else if bytes.is_empty() {
                None
            } else {
                Some(Frame::Bytes(bytes))
            });
        }
        let newline = buffer.iter().position(|&b| b == b'\n');
        let count = newline.unwrap_or(buffer.len());
        if !oversized {
            if count > MAX_FRAME - bytes.len() {
                bytes.clear();
                oversized = true;
            } else {
                bytes.extend_from_slice(&buffer[..count]);
            }
        }
        input.consume(count + usize::from(newline.is_some()));
        if newline.is_some() {
            return Ok(Some(if oversized {
                Frame::Oversized
            } else {
                Frame::Bytes(bytes)
            }));
        }
    }
}
