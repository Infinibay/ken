//! Read one regular inode, reject ambiguous headers, then own decoded tensors.
use crate::{CoreError, invalid};
use ken_native_model_api::MAX_PAYLOAD;
use safetensors::SafeTensors;
use serde::{
    Deserialize,
    de::{self, Visitor},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::OpenOptions,
    io::Read,
    path::Path,
};
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeaderTensor {
    dtype: String,
    shape: Vec<u64>,
    data_offsets: [u64; 2],
}

struct Header;
impl<'de> Visitor<'de> for Header {
    type Value = ();
    fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("distinct tensor header records")
    }
    fn visit_map<M: de::MapAccess<'de>>(self, mut map: M) -> Result<(), M::Error> {
        let mut names = BTreeSet::new();
        while let Some(name) = map.next_key::<String>()? {
            if !names.insert(name.clone()) {
                return Err(de::Error::custom("duplicate parameter header name"));
            }
            if name == "__metadata__" {
                map.next_value::<BTreeMap<String, String>>()?;
                continue;
            }
            let tensor = map.next_value::<HeaderTensor>()?;
            let width = match tensor.dtype.as_str() {
                "F32" => 4_u64,
                "F16" | "BF16" => 2,
                _ => return Err(de::Error::custom("unsupported parameter dtype")),
            };
            let expected = tensor
                .shape
                .iter()
                .try_fold(width, |n, &size| n.checked_mul(size));
            if tensor.shape.is_empty()
                || tensor.shape.len() > 2
                || tensor.shape.contains(&0)
                || expected.is_none()
                || tensor.data_offsets[1].checked_sub(tensor.data_offsets[0]) != expected
            {
                return Err(de::Error::custom("invalid parameter header shape/offsets"));
            }
        }
        Ok(())
    }
}

fn validate_header(bytes: &[u8]) -> Result<(), CoreError> {
    use serde::Deserializer;
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
    let mut parser = serde_json::Deserializer::from_slice(header);
    parser.deserialize_map(Header)?;
    parser.end()?;
    Ok(())
}
