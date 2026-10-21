//! Shared bounded safetensors metadata checks; tensor engines own decoding.
use crate::{ApiError, MAX_PAYLOAD};
use serde::{
    Deserialize, Deserializer,
    de::{self, Visitor},
};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HeaderTensor {
    dtype: String,
    shape: Vec<u64>,
    data_offsets: [u64; 2],
}

struct Header;
impl<'de> Visitor<'de> for Header {
    type Value = Vec<(u64, u64)>;
    fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("distinct tensor header records")
    }
    fn visit_map<M: de::MapAccess<'de>>(self, mut map: M) -> Result<Vec<(u64, u64)>, M::Error> {
        let mut names = BTreeSet::new();
        let mut ranges = Vec::new();
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
            ranges.push((tensor.data_offsets[0], tensor.data_offsets[1]));
        }
        Ok(ranges)
    }
}

/// Validate floating vector/matrix records and exact contiguous data coverage.
pub fn validate_parameter_header(header: &[u8], data_bytes: u64) -> Result<(), ApiError> {
    let invalid = |message: &str| ApiError::Invalid(message.into());
    if header.len() > MAX_PAYLOAD {
        return Err(invalid("parameter header exceeds bound"));
    }
    let mut parser = serde_json::Deserializer::from_slice(header);
    let mut ranges = parser
        .deserialize_map(Header)
        .map_err(|e| ApiError::Invalid(e.to_string()))?;
    parser.end().map_err(|e| ApiError::Invalid(e.to_string()))?;
    if ranges.is_empty() {
        return Err(invalid("parameter archive is empty"));
    }
    ranges.sort_unstable();
    let mut end = 0;
    for (start, next) in ranges {
        if start != end || next > data_bytes {
            return Err(invalid("parameter offsets do not exactly cover data"));
        }
        end = next;
    }
    if end != data_bytes {
        return Err(invalid("parameter archive data size differs from header"));
    }
    Ok(())
}
