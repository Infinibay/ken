//! Validate archive structure, then load the pinned inode with libtorch's native reader.
use crate::{CoreError, invalid};
use std::{collections::BTreeSet, fs::OpenOptions, os::fd::AsRawFd, path::Path};
use tch::{Device, Tensor};

pub(crate) fn read(
    path: &Path,
    maximum: u64,
    parameters: usize,
) -> Result<Vec<(String, Tensor)>, CoreError> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err(invalid("bounded regular parameter archive required"));
    }
    {
        let mut archive = zip::ZipArchive::new(file.try_clone()?)
            .map_err(|e| invalid(format!("parameter ZIP: {e}")))?;
        if archive.is_empty() || archive.len() > parameters.saturating_add(32) {
            return Err(invalid("unexpected parameter archive record count"));
        }
        let mut names = BTreeSet::new();
        let mut total = 0_u64;
        let mut root = None;
        let mut pickle = false;
        for index in 0..archive.len() {
            let entry = archive
                .by_index_raw(index)
                .map_err(|e| invalid(e.to_string()))?;
            let name = std::str::from_utf8(entry.name_raw()).map_err(|e| invalid(e.to_string()))?;
            let parts: Vec<_> = name.split('/').collect();
            if name.contains(['\\', '\0'])
                || parts.len() < 2
                || parts
                    .iter()
                    .any(|p| p.is_empty() || *p == "." || *p == "..")
                || !entry.is_file()
                || !names.insert(name.to_owned())
                || entry.compression() != zip::CompressionMethod::Stored
            {
                return Err(invalid(
                    "invalid, compressed or duplicate parameter ZIP name",
                ));
            }
            match &root {
                None => root = Some(parts[0].to_owned()),
                Some(expected) if expected != parts[0] => {
                    return Err(invalid("multiple parameter archive roots"));
                }
                _ => {}
            }
            total = total
                .checked_add(entry.size())
                .ok_or_else(|| invalid("parameter archive size overflow"))?;
            if total > maximum
                || entry
                    .data_start()
                    .checked_add(entry.size())
                    .is_none_or(|end| end > metadata.len())
            {
                return Err(invalid("parameter archive record exceeds file bound"));
            }
            if parts[1..] == ["data.pkl"] {
                if entry.size() > ken_native_model_api::MAX_PAYLOAD as u64 {
                    return Err(invalid("parameter archive metadata exceeds bound"));
                }
                pickle = true;
            }
        }
        if !pickle {
            return Err(invalid("missing parameter archive metadata"));
        }
    }
    // /dev/fd reopens the held regular inode on both supported Unix platforms.
    // No original pathname race, extraction, Python, or extra whole-file buffer.
    let tensors =
        Tensor::loadz_multi_with_device(format!("/dev/fd/{}", file.as_raw_fd()), Device::Cpu)?;
    if file.metadata()?.len() != metadata.len() {
        return Err(invalid("parameter archive changed during read"));
    }
    Ok(tensors)
}
