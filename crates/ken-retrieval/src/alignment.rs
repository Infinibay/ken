//! One best document match per query term, retaining original numeric dtype.
use crate::{Result, RetrievalError, dense_math::DenseMath, matrix::Matrix};
use std::borrow::Cow;
#[derive(Clone, Debug)]
pub enum FloatMatrix {
    F32(Matrix<f32>),
    F64(Matrix<f64>),
}
impl FloatMatrix {
    pub fn rows(&self) -> usize {
        match self {
            Self::F32(m) => m.rows(),
            Self::F64(m) => m.rows(),
        }
    }
    pub fn columns(&self) -> usize {
        match self {
            Self::F32(m) => m.columns(),
            Self::F64(m) => m.columns(),
        }
    }
    fn finite(&self) -> bool {
        match self {
            Self::F32(m) => m.values().iter().all(|v| v.is_finite()),
            Self::F64(m) => m.values().iter().all(|v| v.is_finite()),
        }
    }
    fn values64(&self) -> Cow<'_, [f64]> {
        match self {
            Self::F32(m) => Cow::Owned(m.values().iter().map(|v| *v as f64).collect()),
            Self::F64(m) => Cow::Borrowed(m.values()),
        }
    }
    fn row(&self, index: usize) -> Row<'_> {
        let start = index * self.columns();
        let end = start + self.columns();
        match self {
            Self::F32(m) => Row::F32(&m.values()[start..end]),
            Self::F64(m) => Row::F64(&m.values()[start..end]),
        }
    }
}
#[derive(Clone, Debug)]
pub enum FloatVector {
    F32(Vec<f32>),
    F64(Vec<f64>),
}
impl FloatVector {
    fn len(&self) -> usize {
        match self {
            Self::F32(v) => v.len(),
            Self::F64(v) => v.len(),
        }
    }
    fn valid(&self) -> bool {
        match self {
            Self::F32(v) => v.iter().all(|n| n.is_finite() && *n >= 0.),
            Self::F64(v) => v.iter().all(|n| n.is_finite() && *n >= 0.),
        }
    }
    fn values64(&self) -> Cow<'_, [f64]> {
        match self {
            Self::F32(v) => Cow::Owned(v.iter().map(|v| *v as f64).collect()),
            Self::F64(v) => Cow::Borrowed(v),
        }
    }
    fn denominator(&self) -> f64 {
        match self {
            // Python max compares a NumPy scalar to the weak Python floor using
            // its own dtype. Equality retains the exact Python1e-9 floor.
            Self::F32(v) => {
                let sum = 0. + ken_models::numpy_pairwise_sum(v.len(), &|i| v[i]);
                if sum > 1e-9_f32 { sum as f64 } else { 1e-9 }
            }
            Self::F64(v) => (0. + pairwise64(v)).max(1e-9),
        }
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct TermCoverage {
    pub mean: f64,
    pub minimum: f64,
    pub quartile: f64,
    pub above50: f64,
    pub above70: f64,
    pub weighted: f64,
}
#[derive(Clone, Debug)]
pub struct TermAlignment {
    query_vectors: FloatMatrix,
    weights: FloatVector,
}
impl TermAlignment {
    pub fn new(query_vectors: FloatMatrix, weights: FloatVector) -> Result<Self> {
        if !query_vectors.finite() {
            return Err(invalid("finite query term matrix required"));
        }
        if weights.len() != query_vectors.rows() || !weights.valid() {
            return Err(invalid(
                "weights must be finite, nonnegative and match the query terms",
            ));
        }
        Ok(Self {
            query_vectors,
            weights,
        })
    }
    pub fn similarities(&self, documents: &FloatMatrix) -> Result<FloatMatrix> {
        if documents.columns() != self.query_vectors.columns() || !documents.finite() {
            return Err(invalid("compatible finite document term matrix required"));
        }
        let (m, n, d) = (
            self.query_vectors.rows(),
            documents.rows(),
            documents.columns(),
        );
        match (&self.query_vectors, documents) {
            (FloatMatrix::F32(q), FloatMatrix::F32(v)) => Ok(FloatMatrix::F32(Matrix::new(
                m,
                n,
                DenseMath::product32(q.values(), m, d, v.values(), n)?,
            )?)),
            _ => Ok(FloatMatrix::F64(Matrix::new(
                m,
                n,
                DenseMath::product64(
                    &self.query_vectors.values64(),
                    m,
                    d,
                    &documents.values64(),
                    n,
                )?,
            )?)),
        }
    }
    pub fn coverage(&self, documents: &FloatMatrix) -> Result<TermCoverage> {
        self.summarize(&self.similarities(documents)?)
    }
    pub fn summarize(&self, similarities: &FloatMatrix) -> Result<TermCoverage> {
        if similarities.rows() != self.weights.len() || !similarities.finite() {
            return Err(invalid("one finite similarity row per query term required"));
        }
        if similarities.rows() == 0 || similarities.columns() == 0 {
            return Ok(TermCoverage::default());
        }
        let peaks = match similarities {
            FloatMatrix::F32(m) => FloatMatrix::F32(Matrix::new(
                1,
                m.rows(),
                m.values()
                    .chunks(m.columns())
                    .map(|r| {
                        r.iter()
                            .copied()
                            .reduce(f32::max)
                            .expect("nonempty term row")
                    })
                    .collect(),
            )?),
            FloatMatrix::F64(m) => FloatMatrix::F64(Matrix::new(
                1,
                m.rows(),
                m.values()
                    .chunks(m.columns())
                    .map(|r| {
                        r.iter()
                            .copied()
                            .reduce(f64::max)
                            .expect("nonempty term row")
                    })
                    .collect(),
            )?),
        };
        Ok(self.summarize_maxima(&peaks, &[true])?[0])
    }
    pub fn summarize_maxima(
        &self,
        maxima: &FloatMatrix,
        present: &[bool],
    ) -> Result<Vec<TermCoverage>> {
        if maxima.columns() != self.weights.len()
            || present.len() != maxima.rows()
            || present
                .iter()
                .enumerate()
                .any(|(i, p)| *p && !maxima.row(i).finite())
        {
            return Err(invalid(
                "aligned finite active maxima and boolean source presence required",
            ));
        }
        let mut out = vec![TermCoverage::default(); maxima.rows()];
        if self.weights.len() == 0 || !present.iter().any(|p| *p) {
            return Ok(out);
        }
        let denominator = self.weights.denominator();
        for (i, active) in present.iter().enumerate() {
            if *active {
                out[i] = maxima.row(i).summarize(&self.weights, denominator)?;
            }
        }
        Ok(out)
    }
}
fn invalid(message: &str) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
enum Row<'a> {
    F32(&'a [f32]),
    F64(&'a [f64]),
}
impl Row<'_> {
    fn finite(&self) -> bool {
        match self {
            Self::F32(v) => v.iter().all(|v| v.is_finite()),
            Self::F64(v) => v.iter().all(|v| v.is_finite()),
        }
    }
    fn summarize(&self, weights: &FloatVector, denominator: f64) -> Result<TermCoverage> {
        match self {
            Self::F32(values) => {
                let n = values.len();
                let mut sorted = values.to_vec();
                sorted.sort_by(f32::total_cmp);
                let index = (n - 1) as f64 * 0.25;
                let lo = index.floor() as usize;
                let hi = (lo + 1).min(n - 1);
                let t = (index - lo as f64) as f32;
                let difference = sorted[hi] - sorted[lo];
                let quartile = if t >= 0.5 {
                    sorted[hi] - difference * (1. - t)
                } else {
                    sorted[lo] + difference * t
                };
                let weighted = match weights {
                    FloatVector::F32(w) => {
                        (DenseMath::dot32(values, w)? / (denominator as f32)) as f64
                    }
                    FloatVector::F64(w) => {
                        DenseMath::dot64(&values.iter().map(|v| *v as f64).collect::<Vec<_>>(), w)?
                            / denominator
                    }
                };
                Ok(TermCoverage {
                    mean: ((0. + ken_models::numpy_pairwise_sum(n, &|i| values[i])) / (n as f32))
                        as f64,
                    minimum: sorted[0] as f64,
                    quartile: quartile as f64,
                    above50: values.iter().filter(|v| **v >= 0.5_f32).count() as f64 / n as f64,
                    above70: values.iter().filter(|v| **v >= 0.7_f32).count() as f64 / n as f64,
                    weighted,
                })
            }
            Self::F64(values) => {
                let n = values.len();
                let mut sorted = values.to_vec();
                sorted.sort_by(f64::total_cmp);
                let index = (n - 1) as f64 * 0.25;
                let lo = index.floor() as usize;
                let hi = (lo + 1).min(n - 1);
                let t = index - lo as f64;
                let difference = sorted[hi] - sorted[lo];
                let quartile = if t >= 0.5 {
                    sorted[hi] - difference * (1. - t)
                } else {
                    sorted[lo] + difference * t
                };
                Ok(TermCoverage {
                    mean: (0. + pairwise64(values)) / n as f64,
                    minimum: sorted[0],
                    quartile,
                    above50: values.iter().filter(|v| **v >= 0.5).count() as f64 / n as f64,
                    above70: values.iter().filter(|v| **v >= 0.7).count() as f64 / n as f64,
                    weighted: DenseMath::dot64(values, &weights.values64())? / denominator,
                })
            }
        }
    }
}
fn pairwise64(values: &[f64]) -> f64 {
    let n = values.len();
    if n < 8 {
        return values.iter().fold(-0., |a, v| a + v);
    }
    if n > 128 {
        let middle = (n / 2) / 8 * 8;
        return pairwise64(&values[..middle]) + pairwise64(&values[middle..]);
    }
    let mut lanes: [f64; 8] = values[..8].try_into().expect("complete eight-value block");
    let boundary = n / 8 * 8;
    for chunk in values[8..boundary].chunks_exact(8) {
        for (sum, v) in lanes.iter_mut().zip(chunk) {
            *sum += v;
        }
    }
    let sum = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[3]))
        + ((lanes[4] + lanes[5]) + (lanes[6] + lanes[7]));
    values[boundary..].iter().fold(sum, |sum, v| sum + v)
}
