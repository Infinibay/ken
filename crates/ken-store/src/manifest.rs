use crate::{StoreError, StoreResult, VectorSpace, segments::publish_new};
use serde::{Deserialize, Serialize};
use std::{io::Write, path::Path};

fn dtype() -> String {
    "float32".into()
}
fn segment_rows() -> usize {
    65_536
}

/// Identity and fixed capacity of a format-1 vector space.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorManifest {
    pub format: u32,
    pub space: String,
    pub dim: usize,
    #[serde(default = "dtype")]
    pub dtype: String,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default = "segment_rows")]
    pub segment_rows: usize,
}

impl VectorManifest {
    pub(crate) fn open(
        directory: &Path,
        space: VectorSpace,
        dim: usize,
        model: Option<&str>,
    ) -> StoreResult<Self> {
        let path = directory.join(format!("{space}.json"));
        let requested = Self {
            format: 1,
            space: space.to_string(),
            dim,
            dtype: dtype(),
            model: model.map(str::to_owned),
            segment_rows: segment_rows(),
        };
        requested.validate(&path, space, dim, model)?;
        match std::fs::read(&path) {
            Ok(raw) => Self::decode(&path, &raw, space, dim, model),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                std::fs::create_dir_all(directory).map_err(|e| StoreError::io(directory, e))?;
                let raw = serde_json::to_vec_pretty(&requested)
                    .map_err(|e| Self::invalid(&path, e.to_string()))?;
                if publish_new(&path, |file| file.write_all(&raw))? {
                    Ok(requested)
                } else {
                    let raw = std::fs::read(&path).map_err(|e| StoreError::io(&path, e))?;
                    Self::decode(&path, &raw, space, dim, model)
                }
            }
            Err(error) => Err(StoreError::io(&path, error)),
        }
    }

    fn decode(
        path: &Path,
        raw: &[u8],
        space: VectorSpace,
        dim: usize,
        model: Option<&str>,
    ) -> StoreResult<Self> {
        let manifest: Self =
            serde_json::from_slice(raw).map_err(|e| Self::invalid(path, e.to_string()))?;
        manifest.validate(path, space, dim, model)?;
        Ok(manifest)
    }

    fn invalid(path: &Path, reason: impl Into<String>) -> StoreError {
        StoreError::CorruptManifest {
            path: path.into(),
            reason: reason.into(),
        }
    }

    fn validate(
        &self,
        path: &Path,
        space: VectorSpace,
        dim: usize,
        model: Option<&str>,
    ) -> StoreResult<()> {
        if self.format != 1
            || self.space != space.as_str()
            || self.dtype != "float32"
            || self.dim == 0
            || self.segment_rows == 0
        {
            return Err(Self::invalid(
                path,
                "expected format1, correct space, float32 and positive dimensions/capacity",
            ));
        }
        if self.dim != dim {
            return Err(StoreError::Dimension(
                "requested dimension differs from manifest",
            ));
        }
        if let (Some(stored), Some(requested)) = (&self.model, model)
            && stored != requested
        {
            return Err(Self::invalid(
                path,
                "requested model conflicts with recorded model",
            ));
        }
        self.segment_bytes()?;
        Ok(())
    }

    pub(crate) fn row_bytes(&self) -> StoreResult<usize> {
        self.dim
            .checked_mul(4)
            .ok_or(StoreError::Dimension("row byte length overflows"))
    }
    pub(crate) fn segment_bytes(&self) -> StoreResult<u64> {
        let bytes = self
            .row_bytes()?
            .checked_mul(self.segment_rows)
            .and_then(|n| i64::try_from(n).ok());
        bytes
            .map(|n| n as u64)
            .ok_or(StoreError::Dimension("segment exceeds file offset range"))
    }
}
