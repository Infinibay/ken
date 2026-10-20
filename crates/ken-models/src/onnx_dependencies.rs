//! Bounded ONNX file-dependency traversal, independent of neural execution.
use crate::{ModelError, VerifiedModelFiles, onnx_wire::Stream};
use std::{
    collections::BTreeMap,
    io::{BufReader, Read, Seek},
    path::Path,
};

fn invalid(message: &str) -> ModelError {
    ModelError::Weights(format!("ONNX dependencies: {message}"))
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Model,
    Graph,
    Node,
    Attribute,
    Tensor,
    Sparse,
    Training,
    Function,
}

fn child(kind: Kind, tag: u32) -> Option<Kind> {
    use Kind::*;
    match (kind, tag) {
        (Model, 7) | (Attribute, 6 | 11) | (Training, 1 | 2) => Some(Graph),
        (Model, 20) => Some(Training),
        (Model, 25) => Some(Function),
        (Graph, 1) | (Function, 7) => Some(Node),
        (Graph, 5) | (Attribute, 5 | 10) | (Sparse, 1 | 2) => Some(Tensor),
        (Graph, 15) | (Attribute, 22 | 23) => Some(Sparse),
        (Node, 5) | (Function, 11) => Some(Attribute),
        _ => None,
    }
}

/// Resolve only a registered graph name; private artifact paths never escape.
pub fn verify_onnx_dependencies(graph: &str, files: &VerifiedModelFiles) -> Result<(), ModelError> {
    verify_dependencies(&files.artifact_path(graph)?, files)
}

pub(crate) fn verify_dependencies(
    graph: &Path,
    files: &VerifiedModelFiles,
) -> Result<(), ModelError> {
    let name = graph
        .strip_prefix(files.root())
        .ok()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid("registered owned graph required"))?;
    let length = files
        .artifact_size(name)
        .ok_or_else(|| invalid("registered owned graph required"))?;
    let file = crate::verified_file::open_regular(graph, length)
        .map_err(|error| invalid(&error.to_string()))?;
    let mut stream = Stream::new(BufReader::new(file), length);
    let parent = Path::new(name).parent().unwrap_or_else(|| Path::new(""));
    walk(&mut stream, Kind::Model, length, 0, parent, files)
}

fn entry<R: Read + Seek>(
    stream: &mut Stream<R>,
    end: u64,
    depth: usize,
) -> Result<(String, String), ModelError> {
    if depth > 64 {
        return Err(invalid("message depth exceeded"));
    }
    let (mut key, mut value) = (None, None);
    while let Some(field) = stream.field(end)? {
        if field.tag == 1 || field.tag == 2 {
            let slot = if field.tag == 1 { &mut key } else { &mut value };
            if slot.is_some() {
                return Err(invalid("duplicate external entry field"));
            }
            *slot = Some(stream.text(field)?);
        }
        stream.skip(field.end)?;
    }
    Ok((
        key.ok_or_else(|| invalid("external key missing"))?,
        value.ok_or_else(|| invalid("external value missing"))?,
    ))
}

fn walk<R: Read + Seek>(
    stream: &mut Stream<R>,
    kind: Kind,
    end: u64,
    depth: usize,
    parent: &Path,
    files: &VerifiedModelFiles,
) -> Result<(), ModelError> {
    if depth > 64 {
        return Err(invalid("message depth exceeded"));
    }
    let mut external = BTreeMap::new();
    let mut location = None;
    while let Some(field) = stream.field(end)? {
        if let Some(child) = child(kind, field.tag) {
            if field.wire != 2 {
                return Err(invalid("tensor carrier message required"));
            }
            walk(stream, child, field.end, depth + 1, parent, files)?;
        } else if kind == Kind::Tensor && field.tag == 13 {
            if field.wire != 2 {
                return Err(invalid("external entry message required"));
            }
            let (key, value) = entry(stream, field.end, depth + 1)?;
            if !matches!(key.as_str(), "location" | "offset" | "length" | "checksum") {
                return Err(invalid("unsupported external metadata key"));
            }
            if external.insert(key, value).is_some() {
                return Err(invalid("duplicate external metadata key"));
            }
        } else if kind == Kind::Tensor && field.tag == 14 {
            if location.is_some() || field.wire != 0 {
                return Err(invalid("ambiguous tensor data location"));
            }
            location = field.number;
        }
        stream.skip(field.end)?;
    }
    if kind == Kind::Tensor {
        match location.unwrap_or(0) {
            0 if external.is_empty() => (),
            1 => verify_external(&external, parent, files)?,
            _ => return Err(invalid("invalid tensor data location")),
        }
    }
    Ok(())
}

fn unsigned(value: &str) -> Result<u64, ModelError> {
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(invalid("nonnegative decimal external range required"));
    }
    value
        .parse()
        .map_err(|_| invalid("external range overflow"))
}

fn verify_external(
    entries: &BTreeMap<String, String>,
    parent: &Path,
    files: &VerifiedModelFiles,
) -> Result<(), ModelError> {
    let location = entries
        .get("location")
        .ok_or_else(|| invalid("external file location missing"))?;
    if !crate::assets::valid_artifact_name(location) {
        return Err(invalid("safe relative external location required"));
    }
    let path = parent.join(location);
    let name = path
        .to_str()
        .ok_or_else(|| invalid("invalid external path"))?;
    let size = files
        .artifact_size(name)
        .ok_or_else(|| invalid("external file is not a declared owned artifact"))?;
    let offset = entries
        .get("offset")
        .map(|value| unsigned(value))
        .transpose()?
        .unwrap_or(0);
    if offset > size {
        return Err(invalid("external offset exceeds file"));
    }
    let length = entries
        .get("length")
        .map(|value| unsigned(value))
        .transpose()?
        .unwrap_or(size - offset);
    if offset.checked_add(length).is_none_or(|end| end > size) {
        return Err(invalid("external range exceeds file"));
    }
    Ok(())
}
