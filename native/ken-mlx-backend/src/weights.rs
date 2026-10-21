//! Validate an entire declared network before publishing owned MLX arrays.
use crate::{CoreError, invalid};
use ken_native_model_api::{
    MAX_PAYLOAD, Qwen3Config, TransformerDtype, TransformerWeightLayout, validate_parameter_header,
};
use mlx_rs::{Array, Device, Dtype, with_device};
use std::{
    collections::BTreeMap,
    fs::{File, OpenOptions},
    io::{Read, Seek},
    os::{
        fd::AsRawFd,
        unix::{fs::MetadataExt, fs::OpenOptionsExt},
    },
    path::{Path, PathBuf},
};

pub struct MlxWeights {
    pub(crate) config: Qwen3Config,
    tensors: BTreeMap<String, Array>,
    pub(crate) head: Option<Array>,
}
impl MlxWeights {
    pub fn load(
        config: &Qwen3Config,
        path: &Path,
        dtype: TransformerDtype,
    ) -> Result<Self, CoreError> {
        config.validate()?;
        let shapes = config.parameter_shapes();
        let maximum = shapes
            .values()
            .try_fold(0_u64, |total, shape| {
                let elements = shape
                    .iter()
                    .try_fold(1_u64, |n, &size| n.checked_mul(size as u64))?;
                total.checked_add(elements.checked_mul(4)?)
            })
            .and_then(|n| {
                n.checked_add(
                    (config.vocab_size as u64)
                        .checked_mul(config.hidden_size as u64)?
                        .checked_mul(4)?,
                )
            })
            .and_then(|n| n.checked_add(MAX_PAYLOAD as u64 + 8))
            .ok_or_else(|| invalid("MLX parameter size overflow"))?;
        let source = HeldParameter::open(path, maximum)?;
        with_device(Device::gpu(), || {
            let loaded = with_device(Device::cpu(), || Array::load_safetensors(&source.alias))?;
            let mut tensors = BTreeMap::new();
            let mut head = None;
            for (name, value) in loaded {
                if !matches!(
                    value.dtype(),
                    Dtype::Float32 | Dtype::Float16 | Dtype::Bfloat16
                ) {
                    return Err(invalid(format!("unsupported MLX parameter dtype: {name}")));
                }
                finite(&value, &name)?;
                if name == "lm_head.weight" {
                    if value.shape() != [config.vocab_size as i32, config.hidden_size as i32] {
                        return Err(invalid("invalid explicit MLX output head shape"));
                    }
                    value.eval()?;
                    head = Some(value);
                    continue;
                }
                let key = match config.layout() {
                    Some(TransformerWeightLayout::Unprefixed) => name.as_str(),
                    Some(TransformerWeightLayout::ModelPrefix) => name
                        .strip_prefix("model.")
                        .ok_or_else(|| invalid("missing declared MLX model prefix"))?,
                    None => return Err(invalid("undeclared MLX parameter layout")),
                };
                let shape = shapes
                    .get(key)
                    .ok_or_else(|| invalid(format!("unexpected MLX parameter: {name}")))?;
                if value
                    .shape()
                    .iter()
                    .map(|&n| i64::from(n))
                    .collect::<Vec<_>>()
                    != *shape
                    || tensors.contains_key(key)
                {
                    return Err(invalid(format!(
                        "invalid MLX parameter shape/duplicate: {name}"
                    )));
                }
                let value = value.as_dtype(kind(dtype))?;
                value.eval()?;
                finite(&value, &name)?;
                tensors.insert(key.to_owned(), value);
            }
            if tensors.len() != shapes.len() {
                return Err(invalid("missing declared MLX parameters"));
            }
            source.check_unchanged()?;
            Ok(Self {
                config: config.clone(),
                tensors,
                head,
            })
        })
    }
    pub(crate) fn get(&self, name: &str) -> Result<&Array, CoreError> {
        self.tensors
            .get(name)
            .ok_or_else(|| invalid(format!("missing owned MLX weight: {name}")))
    }
}
pub(crate) fn finite(value: &Array, name: &str) -> Result<(), CoreError> {
    let valid = value.is_finite()?.all(None)?;
    valid.eval()?;
    if !valid.item_exact::<bool>() {
        return Err(invalid(format!("nonfinite MLX tensor: {name}")));
    }
    Ok(())
}
pub(crate) fn kind(dtype: TransformerDtype) -> Dtype {
    match dtype {
        TransformerDtype::Float32 => Dtype::Float32,
        TransformerDtype::Float16 => Dtype::Float16,
        TransformerDtype::BFloat16 => Dtype::Bfloat16,
    }
}

/// A private suffix-bearing alias satisfies the binding's filename check while
/// native I/O still reads the exact held inode, with no whole-file copy.
struct HeldParameter {
    file: File,
    original: std::fs::Metadata,
    _alias_owner: tempfile::TempDir,
    alias: PathBuf,
}
impl HeldParameter {
    fn open(path: &Path, maximum: u64) -> Result<Self, CoreError> {
        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(path)?;
        let original = file.metadata()?;
        if !original.is_file() || original.len() > maximum || original.len() < 8 {
            return Err(invalid("bounded regular MLX parameter file required"));
        }
        let mut length = [0_u8; 8];
        file.read_exact(&mut length)?;
        let length = u64::from_le_bytes(length);
        if length > MAX_PAYLOAD as u64 || length > original.len() - 8 {
            return Err(invalid("invalid bounded MLX parameter header"));
        }
        let mut header = vec![0_u8; length as usize];
        file.read_exact(&mut header)?;
        validate_parameter_header(&header, original.len() - 8 - length)?;
        let owner = tempfile::Builder::new().prefix("ken-mlx-held-").tempdir()?;
        let alias = owner.path().join("model.safetensors");
        std::os::unix::fs::symlink(format!("/dev/fd/{}", file.as_raw_fd()), &alias)?;
        file.rewind()?;
        let actual = File::open(&alias)?.metadata()?;
        if actual.dev() != original.dev()
            || actual.ino() != original.ino()
            || actual.len() != original.len()
        {
            return Err(invalid("MLX held parameter alias changed inode"));
        }
        Ok(Self {
            file,
            original,
            _alias_owner: owner,
            alias,
        })
    }
    fn check_unchanged(&self) -> Result<(), CoreError> {
        let current = self.file.metadata()?;
        if current.len() != self.original.len() {
            return Err(invalid("MLX parameter changed during read"));
        }
        Ok(())
    }
}
