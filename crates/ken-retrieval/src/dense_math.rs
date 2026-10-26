//! The original platform BLAS reduction is part of dense ranking, even at a cutoff.
//! Scalar reductions and other BLAS versions may reverse two near-equal owners.
use crate::{Result, RetrievalError};

#[cfg(target_os = "macos")]
type BlasInt = i32;
#[cfg(target_os = "linux")]
type BlasInt = i64;
type Dot<T> = unsafe extern "C" fn(BlasInt, *const T, BlasInt, *const T, BlasInt) -> T;
type Gemv<T> = unsafe extern "C" fn(
    i32,
    i32,
    BlasInt,
    BlasInt,
    T,
    *const T,
    BlasInt,
    *const T,
    BlasInt,
    T,
    *mut T,
    BlasInt,
);
type Gemm<T> = unsafe extern "C" fn(
    i32,
    i32,
    i32,
    BlasInt,
    BlasInt,
    BlasInt,
    T,
    *const T,
    BlasInt,
    *const T,
    BlasInt,
    T,
    *mut T,
    BlasInt,
);

pub(crate) struct DenseMath {
    dot: Dot<f32>,
    gemv: Gemv<f32>,
    dot64: Dot<f64>,
    gemv64: Gemv<f64>,
    gemm: Gemm<f32>,
    gemm64: Gemm<f64>,
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
    fn cblas_ddot(n: BlasInt, x: *const f64, ix: BlasInt, y: *const f64, iy: BlasInt) -> f64;
    fn cblas_dgemv(
        order: i32,
        trans: i32,
        m: BlasInt,
        n: BlasInt,
        alpha: f64,
        a: *const f64,
        lda: BlasInt,
        x: *const f64,
        ix: BlasInt,
        beta: f64,
        y: *mut f64,
        iy: BlasInt,
    );
    fn cblas_sgemm(
        order: i32,
        ta: i32,
        tb: i32,
        m: BlasInt,
        n: BlasInt,
        k: BlasInt,
        alpha: f32,
        a: *const f32,
        lda: BlasInt,
        b: *const f32,
        ldb: BlasInt,
        beta: f32,
        c: *mut f32,
        ldc: BlasInt,
    );
    fn cblas_dgemm(
        order: i32,
        ta: i32,
        tb: i32,
        m: BlasInt,
        n: BlasInt,
        k: BlasInt,
        alpha: f64,
        a: *const f64,
        lda: BlasInt,
        b: *const f64,
        ldb: BlasInt,
        beta: f64,
        c: *mut f64,
        ldc: BlasInt,
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
            dot64: cblas_ddot,
            gemv64: cblas_dgemv,
            gemm: cblas_sgemm,
            gemm64: cblas_dgemm,
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
    let raw = if cfg!(target_arch = "x86_64") {
        include_str!("../resources/dense-runtime-x86_64.json")
    } else {
        include_str!("../resources/dense-runtime.json")
    };
    serde_json::from_str(raw).expect("pinned dense runtime manifest")
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

/// Verify the pinned native BLAS bundle for this architecture before loading it.
/// Packaging places every registered sidecar beside the executable in `dense-blas/`.
#[cfg(target_os = "linux")]
pub fn verify_dense_runtime(directory: &std::path::Path) -> Result<()> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    if !cfg!(any(target_arch = "aarch64", target_arch = "x86_64")) {
        return Err(RetrievalError::Invalid(
            "dense BLAS runtime is pinned for Linux aarch64 and x86_64".into(),
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
        // SAFETY: only the exact pinned native ELF is loaded; its typed public ILP64
        // CBLAS signatures are retained with their owning library for process lifetime.
        unsafe {
            let library = libloading::Library::new(path).map_err(|e| {
                RetrievalError::Invalid(format!("cannot load dense BLAS runtime: {e}"))
            })?;
            let dot = *library
                .get::<Dot<f32>>(b"scipy_cblas_sdot64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let gemv = *library
                .get::<Gemv<f32>>(b"scipy_cblas_sgemv64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let dot64 = *library
                .get::<Dot<f64>>(b"scipy_cblas_ddot64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let gemv64 = *library
                .get::<Gemv<f64>>(b"scipy_cblas_dgemv64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let gemm = *library
                .get::<Gemm<f32>>(b"scipy_cblas_sgemm64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let gemm64 = *library
                .get::<Gemm<f64>>(b"scipy_cblas_dgemm64_\0")
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            Ok(Self {
                dot,
                gemv,
                dot64,
                gemv64,
                gemm,
                gemm64,
                _library: library,
            })
        }
    }
}

impl DenseMath {
    pub(crate) fn dot32(x: &[f32], y: &[f32]) -> Result<f32> {
        if x.len() != y.len() {
            return Err(RetrievalError::Invalid(
                "compatible dot vectors required".into(),
            ));
        }
        if x.is_empty() {
            return Ok(0.);
        }
        let n = size(x.len())?;
        let math = Self::platform()?;
        // SAFETY: both immutable slices have exactly n elements and unit stride.
        Ok(unsafe { (math.dot)(n, x.as_ptr(), 1, y.as_ptr(), 1) })
    }
    pub(crate) fn dot64(x: &[f64], y: &[f64]) -> Result<f64> {
        if x.len() != y.len() {
            return Err(RetrievalError::Invalid(
                "compatible dot vectors required".into(),
            ));
        }
        if x.is_empty() {
            return Ok(0.);
        }
        let n = size(x.len())?;
        let math = Self::platform()?;
        // SAFETY: same checked lengths/strides as dot32, with the pinned f64 ABI.
        Ok(unsafe { (math.dot64)(n, x.as_ptr(), 1, y.as_ptr(), 1) })
    }
    /// Multiply owned C rows by the transpose of another owned C row matrix.
    /// Dispatch follows NumPy2.4.4 matmul.c.src, including single-axis cases.
    pub(crate) fn product32(
        a: &[f32],
        rows: usize,
        width: usize,
        b: &[f32],
        columns: usize,
    ) -> Result<Vec<f32>> {
        let mut out = product_output(a, rows, width, b, columns)?;
        if rows == 0 || columns == 0 || width == 0 {
            return Ok(out);
        }
        let (m, n, k) = (size(rows)?, size(columns)?, size(width)?);
        if width == 1 {
            for i in 0..rows {
                for j in 0..columns {
                    out[i * columns + j] = a[i] * b[j];
                }
            }
            return Ok(out);
        }
        let math = Self::platform()?;
        if rows == 1 {
            return math.scores(b, columns, a);
        }
        if columns == 1 {
            return math.scores(a, rows, b);
        }
        // SAFETY: rectangular lengths and product allocation are checked above;
        // dimensions/leading dimensions fit the ABI, output is distinct from inputs.
        unsafe {
            (math.gemm)(
                101,
                111,
                112,
                m,
                n,
                k,
                1.,
                a.as_ptr(),
                k,
                b.as_ptr(),
                k,
                0.,
                out.as_mut_ptr(),
                n,
            )
        };
        Ok(out)
    }
    pub(crate) fn product64(
        a: &[f64],
        rows: usize,
        width: usize,
        b: &[f64],
        columns: usize,
    ) -> Result<Vec<f64>> {
        let mut out = product_output(a, rows, width, b, columns)?;
        if rows == 0 || columns == 0 || width == 0 {
            return Ok(out);
        }
        let (m, n, k) = (size(rows)?, size(columns)?, size(width)?);
        if width == 1 {
            for i in 0..rows {
                for j in 0..columns {
                    out[i * columns + j] = a[i] * b[j];
                }
            }
            return Ok(out);
        }
        let math = Self::platform()?;
        if rows == 1 && columns == 1 {
            out[0] = Self::dot64(a, b)?;
        } else if rows == 1 || columns == 1 {
            let (matrix, vector, count) = if rows == 1 { (b, a, n) } else { (a, b, m) };
            // SAFETY: complete C rows, unit-stride vector/output, checked dimensions.
            unsafe {
                (math.gemv64)(
                    102,
                    112,
                    k,
                    count,
                    1.,
                    matrix.as_ptr(),
                    k,
                    vector.as_ptr(),
                    1,
                    0.,
                    out.as_mut_ptr(),
                    1,
                )
            };
        } else {
            // SAFETY: same rectangular/ownership guards as product32, with f64 values.
            unsafe {
                (math.gemm64)(
                    101,
                    111,
                    112,
                    m,
                    n,
                    k,
                    1.,
                    a.as_ptr(),
                    k,
                    b.as_ptr(),
                    k,
                    0.,
                    out.as_mut_ptr(),
                    n,
                )
            };
        }
        Ok(out)
    }
}
fn product_output<T: Default + Clone>(
    a: &[T],
    rows: usize,
    width: usize,
    b: &[T],
    columns: usize,
) -> Result<Vec<T>> {
    if rows.checked_mul(width) != Some(a.len()) || columns.checked_mul(width) != Some(b.len()) {
        return Err(RetrievalError::Invalid(
            "rectangular product inputs required".into(),
        ));
    }
    let count = rows.checked_mul(columns).ok_or_else(|| {
        RetrievalError::Invalid("term alignment output dimensions overflow".into())
    })?;
    let mut out = Vec::new();
    out.try_reserve_exact(count)
        .map_err(|e| RetrievalError::Invalid(format!("term alignment output allocation: {e}")))?;
    out.resize(count, T::default());
    Ok(out)
}

/// Identity of the numerical backend actually retained by the process.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct DenseRuntimeIdentity {
    pub core: String,
    pub threads: i32,
    pub sha256: String,
}

/// Inspect the same byte-verified library used by dense operations, without
/// changing its kernel selection or thread policy.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub fn dense_runtime_identity() -> Result<DenseRuntimeIdentity> {
    use std::ffi::{CStr, c_char};
    type Core = unsafe extern "C" fn() -> *const c_char;
    type Threads = unsafe extern "C" fn() -> i32;
    let math = DenseMath::platform()?;
    // SAFETY: platform() verifies the pinned bundle before loading it. These
    // public OpenBLAS introspection signatures belong to that exact library,
    // which stays owned by the process-wide DenseMath value.
    let (core, threads) = unsafe {
        let core = math
            ._library
            .get::<Core>(b"scipy_openblas_get_corename64_\0")
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
        let threads = math
            ._library
            .get::<Threads>(b"scipy_openblas_get_num_threads64_\0")
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
        let pointer = core();
        if pointer.is_null() {
            return Err(RetrievalError::Invalid("BLAS core identity missing".into()));
        }
        let name = CStr::from_ptr(pointer)
            .to_str()
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?
            .to_owned();
        (name, threads())
    };
    if core.is_empty() || threads <= 0 {
        return Err(RetrievalError::Invalid(
            "invalid BLAS execution identity".into(),
        ));
    }
    let registered = manifest();
    Ok(DenseRuntimeIdentity {
        core,
        threads,
        sha256: registered.files[&registered.library].sha256.clone(),
    })
}
