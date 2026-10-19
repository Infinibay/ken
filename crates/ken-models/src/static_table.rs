//! The fitted bag-of-tokens concept: gather, sum, project and normalize.
use crate::{
    ModelError,
    table_npz::{Table, invalid},
};
use ndarray::Array2;
use tokenizers::Tokenizer;

pub struct StaticTableEncoder {
    table: Table,
    tokenizer: Tokenizer,
}

impl StaticTableEncoder {
    pub fn from_npz(bytes: &[u8]) -> Result<Self, ModelError> {
        let table = Table::from_npz(bytes)?;
        let tokenizer = Tokenizer::from_bytes(&table.tokenizer)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        if tokenizer
            .get_vocab(true)
            .values()
            .any(|i| *i as usize >= table.lut.len())
        {
            return Err(invalid("tokenizer ID outside LUT"));
        }
        Ok(Self { table, tokenizer })
    }

    pub fn dim(&self) -> usize {
        self.table.b.ncols()
    }

    pub fn meta(&self) -> &serde_json::Value {
        &self.table.meta
    }

    pub fn tokenize(&self, text: &str) -> Result<Vec<u32>, ModelError> {
        self.tokenizer
            .encode(text, false)
            .map(|e| e.get_ids().to_vec())
            .map_err(|e| ModelError::Tokenizer(e.to_string()))
    }

    pub fn token_count(&self, text: &str) -> Result<usize, ModelError> {
        Ok(self.tokenize(text)?.len())
    }

    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError> {
        Ok(self.embed_passages(&[text])?.remove(0))
    }

    pub fn embed_queries(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        self.embed_passages(texts)
    }

    pub fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        if texts.is_empty() {
            return Ok(vec![]);
        }
        let encodings = self
            .tokenizer
            .encode_batch(texts.to_vec(), false)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        let mut pooled = Array2::<f32>::zeros((texts.len(), self.table.a.ncols()));
        for (mut row, encoding) in pooled.rows_mut().into_iter().zip(encodings) {
            let indexes: Vec<usize> = encoding
                .get_ids()
                .iter()
                .map(|id| {
                    self.table
                        .lut
                        .get(*id as usize)
                        .copied()
                        .ok_or_else(|| invalid("emitted ID outside LUT"))
                })
                .collect::<Result<_, _>>()?;
            if let Some(first) = indexes.first() {
                for col in 0..row.len() {
                    // reduceat copies its first element, then adds the pairwise
                    // reduction of the remainder (not a left fold of all rows).
                    row[col] = self.table.a[(*first, col)]
                        + pairwise_sum(indexes.len() - 1, &|i| self.table.a[(indexes[i + 1], col)]);
                }
            }
        }
        let mut output = pooled.dot(&self.table.b);
        let mut result = Vec::with_capacity(texts.len());
        for mut row in output.rows_mut() {
            let norm = pairwise_sum(row.len(), &|i| row[i] * row[i])
                .sqrt()
                .max(1e-12);
            row /= norm;
            if row.iter().any(|x| !x.is_finite()) {
                return Err(ModelError::Inference(
                    "nonfinite static table output".into(),
                ));
            }
            result.push(row.to_vec());
        }
        Ok(result)
    }
}

// NumPy 2.4's stable F32 reduction grouping: eight lanes, 128-element
// blocks and recursively aligned halves. Required for cancellation/long texts.
// https://github.com/numpy/numpy/blob/v2.4.4/numpy/_core/src/umath/loops_utils.h.src
fn pairwise_sum(len: usize, at: &impl Fn(usize) -> f32) -> f32 {
    fn block(start: usize, len: usize, at: &impl Fn(usize) -> f32) -> f32 {
        if len < 8 {
            return (start..start + len).fold(-0.0_f32, |sum, i| sum + at(i));
        }
        if len > 128 {
            let middle = (len / 2) / 8 * 8;
            return block(start, middle, at) + block(start + middle, len - middle, at);
        }
        let mut lanes: [f32; 8] = std::array::from_fn(|i| at(start + i));
        let boundary = len / 8 * 8;
        for offset in (8..boundary).step_by(8) {
            for (lane, value) in lanes.iter_mut().enumerate() {
                *value += at(start + offset + lane);
            }
        }
        let sum = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[3]))
            + ((lanes[4] + lanes[5]) + (lanes[6] + lanes[7]));
        (boundary..len).fold(sum, |sum, i| sum + at(start + i))
    }
    block(0, len, at)
}
