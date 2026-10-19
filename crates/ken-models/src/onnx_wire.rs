//! Bounded protobuf fields; untouched ONNX payloads keep their original bytes.
use crate::ModelError;

fn invalid(message: &str) -> ModelError {
    ModelError::Weights(format!("ONNX wire: {message}"))
}

#[derive(Clone, Copy)]
pub(crate) struct Field<'a> {
    pub tag: u32,
    pub wire: u8,
    pub payload: &'a [u8],
    pub raw: &'a [u8],
}

fn read_varint(bytes: &[u8], position: &mut usize) -> Result<u64, ModelError> {
    let mut value = 0;
    for index in 0..10 {
        let byte = *bytes
            .get(*position)
            .ok_or_else(|| invalid("truncated varint"))?;
        *position += 1;
        if index == 9 && byte > 1 {
            return Err(invalid("overflowing varint"));
        }
        value |= u64::from(byte & 127) << (index * 7);
        if byte & 128 == 0 {
            return Ok(value);
        }
    }
    Err(invalid("overlong varint"))
}

pub(crate) fn fields(bytes: &[u8]) -> Result<Vec<Field<'_>>, ModelError> {
    let mut result = Vec::new();
    let mut position = 0;
    while position < bytes.len() {
        if result.len() >= 1_000_000 {
            return Err(invalid("message field budget exceeded"));
        }
        let start = position;
        let key = read_varint(bytes, &mut position)?;
        let tag = u32::try_from(key >> 3).map_err(|_| invalid("invalid field number"))?;
        if tag == 0 || tag > 0x1fff_ffff {
            return Err(invalid("invalid field number"));
        }
        let wire = (key & 7) as u8;
        let begin;
        match wire {
            0 => {
                begin = position;
                read_varint(bytes, &mut position)?;
            }
            1 | 5 => {
                begin = position;
                position = position
                    .checked_add(if wire == 1 { 8 } else { 4 })
                    .ok_or_else(|| invalid("offset overflow"))?;
            }
            2 => {
                let length = usize::try_from(read_varint(bytes, &mut position)?)
                    .map_err(|_| invalid("length overflow"))?;
                begin = position;
                position = position
                    .checked_add(length)
                    .ok_or_else(|| invalid("offset overflow"))?;
            }
            _ => return Err(invalid("unsupported group or wire type")),
        }
        let payload = bytes
            .get(begin..position)
            .ok_or_else(|| invalid("truncated payload"))?;
        result.push(Field {
            tag,
            wire,
            payload,
            raw: &bytes[start..position],
        });
    }
    Ok(result)
}

pub(crate) fn number(field: Field<'_>) -> Result<u64, ModelError> {
    if field.wire != 0 {
        return Err(invalid("integer field required"));
    }
    read_varint(field.payload, &mut 0)
}
pub(crate) fn text(field: Field<'_>) -> Result<&str, ModelError> {
    if field.wire != 2 {
        return Err(invalid("string field required"));
    }
    std::str::from_utf8(field.payload).map_err(|_| invalid("invalid UTF8 name"))
}
pub(crate) fn message(field: Field<'_>) -> Result<Vec<Field<'_>>, ModelError> {
    if field.wire != 2 {
        return Err(invalid("message field required"));
    }
    fields(field.payload)
}
pub(crate) fn unique<'a>(fields: &[Field<'a>], tag: u32) -> Result<Field<'a>, ModelError> {
    let mut matching = fields.iter().filter(|field| field.tag == tag);
    let field = matching
        .next()
        .ok_or_else(|| invalid("required field missing"))?;
    if matching.next().is_some() {
        return Err(invalid("duplicate singular field"));
    }
    Ok(*field)
}
fn varint(mut value: u64, output: &mut Vec<u8>) {
    while value >= 128 {
        output.push((value as u8 & 127) | 128);
        value >>= 7;
    }
    output.push(value as u8);
}
pub(crate) fn integer(tag: u32, value: u64) -> Vec<u8> {
    let mut out = Vec::new();
    varint(u64::from(tag) << 3, &mut out);
    varint(value, &mut out);
    out
}
pub(crate) fn bytes(tag: u32, value: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    varint((u64::from(tag) << 3) | 2, &mut out);
    varint(value.len() as u64, &mut out);
    out.extend_from_slice(value);
    out
}
pub(crate) fn float(tag: u32, value: f32) -> Vec<u8> {
    let mut out = Vec::new();
    varint((u64::from(tag) << 3) | 5, &mut out);
    out.extend_from_slice(&value.to_le_bytes());
    out
}

/// Replace one repeated field group without re-encoding unrelated payloads.
/// Published upstream fields are ordered; unknown fields retain their position.
pub(crate) fn replace(fields: &[Field<'_>], tag: u32, replacement: &[Vec<u8>]) -> Vec<u8> {
    let insertion = fields
        .iter()
        .position(|field| field.tag >= tag)
        .unwrap_or(fields.len());
    let mut out = Vec::new();
    for index in 0..=fields.len() {
        if index == insertion {
            for field in replacement {
                out.extend_from_slice(field);
            }
        }
        if let Some(field) = fields.get(index)
            && field.tag != tag
        {
            out.extend_from_slice(field.raw);
        }
    }
    out
}

/// Append to a repeated group without copying existing tensor payloads separately.
pub(crate) fn append(fields: &[Field<'_>], tag: u32, extra: &[Vec<u8>]) -> Vec<u8> {
    let insertion = fields
        .iter()
        .rposition(|field| field.tag == tag)
        .map(|i| i + 1)
        .unwrap_or_else(|| {
            fields
                .iter()
                .position(|field| field.tag > tag)
                .unwrap_or(fields.len())
        });
    let mut out = Vec::new();
    for index in 0..=fields.len() {
        if index == insertion {
            for field in extra {
                out.extend_from_slice(field);
            }
        }
        if let Some(field) = fields.get(index) {
            out.extend_from_slice(field.raw);
        }
    }
    out
}
