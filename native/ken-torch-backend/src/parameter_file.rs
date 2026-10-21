//! Read one regular inode, reject ambiguous headers, then own decoded tensors.
use crate::{CoreError, invalid};
use ken_native_model_api::MAX_PAYLOAD;
use safetensors::SafeTensors;
use std::{fs::OpenOptions, io::Read, path::Path};
use tch::Tensor;

pub(crate) fn read(path: &Path, maximum: u64) -> Result<Vec<(String, Tensor)>, CoreError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY);
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err(invalid("bounded regular parameter file required"));
    }
    let bound = metadata
        .len()
        .checked_add(1)
        .and_then(|v| usize::try_from(v).ok())
        .ok_or_else(|| invalid("parameter file size overflow"))?;
    let mut bytes = Vec::new();
    bytes
        .try_reserve_exact(bound)
        .map_err(|e| invalid(e.to_string()))?;
    file.take(bound as u64).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() {
        return Err(invalid("parameter file changed during read"));
    }
    validate_header(&bytes)?;
    let archive =
        SafeTensors::deserialize(&bytes).map_err(|e| invalid(format!("parameter archive: {e}")))?;
    archive
        .tensors()
        .into_iter()
        .map(|(name, view)| Ok((name, Tensor::try_from(view)?)))
        .collect()
}

fn validate_header(bytes: &[u8]) -> Result<(), CoreError> {
    let size = u64::from_le_bytes(
        bytes
            .get(..8)
            .ok_or_else(|| invalid("truncated parameter header"))?
            .try_into()
            .map_err(|_| invalid("invalid parameter header"))?,
    );
    let size = usize::try_from(size).map_err(|_| invalid("parameter header size overflow"))?;
    if size > MAX_PAYLOAD {
        return Err(invalid("parameter header exceeds bound"));
    }
    let header = bytes
        .get(8..8 + size)
        .ok_or_else(|| invalid("truncated parameter metadata"))?;
    ken_native_model_api::validate_parameter_header(header, (bytes.len() - 8 - size) as u64)?;
    Ok(())
}
