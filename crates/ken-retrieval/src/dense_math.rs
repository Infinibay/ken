//! The original platform BLAS reduction is part of dense ranking, even at a cutoff.
//! Scalar reductions and other BLAS versions may reverse two near-equal owners.
use crate::{Result, RetrievalError};

#[cfg(target_os = "macos")]
type BlasInt = i32;
#[cfg(target_os = "linux")]
type BlasInt = i64;
type Dot = unsafe extern "C" fn(BlasInt, *const f32, BlasInt, *const f32, BlasInt) -> f32;
type Gemv = unsafe extern "C" fn(
    i32,
    i32,
    BlasInt,
    BlasInt,
    f32,
    *const f32,
    BlasInt,
    *const f32,
    BlasInt,
    f32,
    *mut f32,
    BlasInt,
);

pub(crate) struct DenseMath {
    dot: Dot,
    gemv: Gemv,
    #[cfg(target_os = "linux")]
    _library: libloading::Library,
}

#[cfg(target_os = "macos")]
#[link(name = "Accelerate", kind = "framework")]
unsafe extern "C" {
    fn cblas_sdot(n: BlasInt, x: *const f32, ix: BlasInt, y: *const f32, iy: BlasInt) -> f32;
    fn cblas_sgemv(
        order: i32,
        trans: i32,
        m: BlasInt,
        n: BlasInt,
        alpha: f32,
        a: *const f32,
        lda: BlasInt,
        x: *const f32,
        ix: BlasInt,
        beta: f32,
        y: *mut f32,
        iy: BlasInt,
    );
}

impl DenseMath {
    pub(crate) fn platform() -> Result<&'static Self> {
        static MATH: std::sync::OnceLock<DenseMath> = std::sync::OnceLock::new();
        if let Some(math) = MATH.get() {
            return Ok(math);
        }
        #[cfg(target_os = "macos")]
        let math = Self {
            dot: cblas_sdot,
            gemv: cblas_sgemv,
        };
        #[cfg(target_os = "linux")]
        let math = Self::load(&runtime_directory()?)?;
        let _ = MATH.set(math);
        Ok(MATH.get().expect("initialized dense arithmetic"))
    }

    pub(crate) fn norm(&self, query: &[f32]) -> Result<f32> {
        let n = size(query.len())?;
        // SAFETY: n is checked, both slices have n readable elements, stride is one.
        Ok(unsafe { (self.dot)(n, query.as_ptr(), 1, query.as_ptr(), 1) }.sqrt())
    }

    pub(crate) fn scores(&self, matrix: &[f32], rows: usize, query: &[f32]) -> Result<Vec<f32>> {
        let (m, n) = (size(rows)?, size(query.len())?);
        let mut scores = vec![0.; rows];
        if rows == 0 || query.is_empty() {
            return Ok(scores);
        }
        if rows == 1 {
            // NumPy's scalar-output matmul dispatches to FLOAT_dot, not GEMV.
            scores[0] = unsafe { (self.dot)(n, matrix.as_ptr(), 1, query.as_ptr(), 1) };
        } else if query.len() == 1 {
            for (score, &value) in scores.iter_mut().zip(matrix) {
                *score = value * query[0];
            }
        } else {
            // Same CBLAS dispatch as NumPy 2.4.4 FLOAT_gemv for C-contiguous rows:
            // column-major transposed (width x rows), lda=width, alpha=1,beta=0.
            // SAFETY: DenseView validated rectangular ownership and flattened all rows;
            // m/n fit the BLAS ABI, inputs and separately allocated output do not alias.
            unsafe {
                (self.gemv)(
                    102,
                    112,
                    n,
                    m,
                    1.,
                    matrix.as_ptr(),
                    n,
                    query.as_ptr(),
                    1,
                    0.,
                    scores.as_mut_ptr(),
                    1,
                )
            };
        }
        Ok(scores)
    }
}

fn size(value: usize) -> Result<BlasInt> {
    BlasInt::try_from(value)
        .ok()
        .filter(|n| *n < BlasInt::MAX)
        .ok_or_else(|| {
            RetrievalError::Invalid("dense vector dimensions exceed the platform BLAS limit".into())
        })
}

#[cfg(target_os = "linux")]
#[derive(serde::Deserialize)]
struct RuntimeManifest {
    library: String,
    files: std::collections::BTreeMap<String, RuntimeFile>,
}
#[cfg(target_os = "linux")]
#[derive(serde::Deserialize)]
struct RuntimeFile {
    bytes: u64,
    sha256: String,
}
#[cfg(target_os = "linux")]
fn manifest() -> RuntimeManifest {
    serde_json::from_str(include_str!("../resources/dense-runtime.json"))
        .expect("pinned dense runtime manifest")
}

#[cfg(target_os = "linux")]
fn runtime_directory() -> Result<std::path::PathBuf> {
    if let Some(path) = std::env::var_os("KEN_DENSE_BLAS_DIR") {
        return Ok(path.into());
    }
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.join("dense-blas")))
        .ok_or_else(|| RetrievalError::Invalid("cannot locate prepared dense BLAS runtime".into()))
}

/// Verify the pinned pure-native Linux/aarch64 BLAS bundle before loading it.
/// Packaging places these two files beside the executable in `dense-blas/`.
#[cfg(target_os = "linux")]
pub fn verify_dense_runtime(directory: &std::path::Path) -> Result<()> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    if !cfg!(target_arch = "aarch64") {
        return Err(RetrievalError::Invalid(
            "dense BLAS runtime is pinned for Linux aarch64".into(),
        ));
    }
    for (name, record) in manifest().files {
        let path = directory.join(&name);
        let file = std::fs::File::open(&path).map_err(|e| {
            RetrievalError::Invalid(format!(
                "prepare dense BLAS runtime {}: {e}",
                path.display()
            ))
        })?;
        let mut bytes = Vec::new();
        file.take(record.bytes + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
        if bytes.len() as u64 != record.bytes
            || format!("{:x}", Sha256::digest(&bytes)) != record.sha256
        {
            return Err(RetrievalError::Invalid(format!(
                "dense BLAS runtime integrity differs: {name}"
            )));
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
impl DenseMath {
    fn load(directory: &std::path::Path) -> Result<Self> {
        verify_dense_runtime(directory)?;
        let path = directory.join(manifest().library);
        // SAFETY: only the exact pinned native ELF is loaded; its two public ILP64
        // CBLAS signatures are retained with their owning library for process lifetime.
        unsafe {
            let library = libloading::Library::new(path).map_err(|e| {
                RetrievalError::Invalid(format!("cannot load dense BLAS runtime: {e}"))
            })?;
            let dot = *library
                .get::<Dot>(b"scipy_cblas_sdot64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let gemv = *library
                .get::<Gemv>(b"scipy_cblas_sgemv64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            Ok(Self {
                dot,
                gemv,
                _library: library,
            })
        }
    }
}
