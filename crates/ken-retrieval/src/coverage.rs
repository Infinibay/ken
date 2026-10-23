//! Stream bounded vocabulary blocks into field sums and per-query best matches.
use crate::{
    Result, RetrievalError,
    alignment::{FloatMatrix, FloatVector, TermAlignment},
    dense_math::DenseMath,
    matrix::Matrix,
    reductions::pairwise64,
    stemming::WordStemmer,
    vocabulary::code_terms_python,
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use std::collections::{BTreeMap, BTreeSet};
pub const STAT_NAMES: [&str; 9] = [
    "exact",
    "mean",
    "min",
    "p25",
    "above50",
    "above70",
    "weighted",
    "mean_cosine",
    "log_words",
];
const BLOCK: usize = 4096;
pub type TermDocument = BTreeMap<String, Vec<String>>;
fn terms<'a>(doc: &'a TermDocument, field: &str) -> Result<&'a [String]> {
    doc.get(field)
        .map(Vec::as_slice)
        .ok_or_else(|| RetrievalError::Invalid(format!("source term field missing: {field}")))
}
fn vectors(rows: Vec<Vec<f32>>, count: usize, width: usize) -> Result<Matrix<f32>> {
    if rows.len() != count || rows.iter().any(|r| r.len() != width) {
        return Err(RetrievalError::Invalid(
            "compatible finite document term matrix required".into(),
        ));
    }
    Matrix::new(count, width, rows.into_iter().flatten().collect())
}
pub fn coverage(
    query: &PythonText,
    documents: &[TermDocument],
    fields: &[&str],
    encoder: &dyn WordEncoder,
    stemmer: Option<&dyn WordStemmer>,
) -> Result<Vec<BTreeMap<String, f64>>> {
    let words = code_terms_python(query, Some(128));
    let vocabulary: Vec<String> = words
        .iter()
        .cloned()
        .chain(documents.iter().flat_map(|d| d.values()).flatten().cloned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let lookup: BTreeMap<_, _> = vocabulary
        .iter()
        .enumerate()
        .map(|(i, w)| (w.as_str(), i))
        .collect();
    let all_words: Vec<BTreeSet<_>> = documents
        .iter()
        .map(|d| Ok(terms(d, "all")?.iter().collect()))
        .collect::<Result<_>>()?;
    let weights: Vec<f64> = words
        .iter()
        .map(|w| {
            ((documents.len() as f64)
                / (1 + all_words.iter().filter(|d| d.contains(w)).count()) as f64)
                .ln_1p()
        })
        .collect();
    let sentence = encoder.embed_query(query)?;
    let width = sentence.len();
    let q = if words.is_empty() {
        Matrix::new(0, width, vec![])?
    } else {
        vectors(
            encoder.embed_passages(
                &words
                    .iter()
                    .map(|w| PythonText::from(w.as_str()))
                    .collect::<Vec<_>>(),
            )?,
            words.len(),
            width,
        )?
    };
    let alignment = TermAlignment::new(FloatMatrix::F32(q), FloatVector::F64(weights))?;
    let mut memberships = Vec::new();
    for d in documents {
        for field in fields {
            let mut ids: Vec<_> = terms(d, field)?
                .iter()
                .map(|w| lookup[w.as_str()])
                .collect();
            ids.sort_unstable();
            memberships.push(ids);
        }
    }
    let mut sums = vec![vec![0_f64; width]; memberships.len()];
    let mut peaks = vec![f32::NEG_INFINITY; memberships.len() * words.len()];
    for (block_number, block) in vocabulary.chunks(BLOCK).enumerate() {
        let offset = block_number * BLOCK;
        let encoded = vectors(
            encoder.embed_passages(
                &block
                    .iter()
                    .map(|w| PythonText::from(w.as_str()))
                    .collect::<Vec<_>>(),
            )?,
            block.len(),
            width,
        )?;
        let source = FloatMatrix::F32(encoded);
        let similarities = alignment.similarities(&source)?;
        let FloatMatrix::F32(encoded) = &source else {
            unreachable!()
        };
        let FloatMatrix::F32(similarities) = similarities else {
            unreachable!()
        };
        for (index, ids) in memberships.iter().enumerate() {
            let lower = ids.partition_point(|id| *id < offset);
            let upper = ids.partition_point(|id| *id < offset + block.len());
            let local = &ids[lower..upper];
            if local.is_empty() {
                continue;
            }
            if width == 1 {
                let values: Vec<f64> = local
                    .iter()
                    .map(|id| encoded.values()[id - offset] as f64)
                    .collect();
                sums[index][0] += 0. + pairwise64(&values);
            } else {
                let mut partial = vec![0_f64; width];
                for id in local {
                    for (column, total) in partial.iter_mut().enumerate() {
                        *total += encoded.values()[(id - offset) * width + column] as f64;
                    }
                }
                for (total, value) in sums[index].iter_mut().zip(partial) {
                    *total += value;
                }
            }
            for word in 0..words.len() {
                let best = local
                    .iter()
                    .map(|id| similarities.values()[word * block.len() + id - offset])
                    .reduce(maximum)
                    .expect("nonempty source membership");
                peaks[index * words.len() + word] =
                    maximum(peaks[index * words.len() + word], best);
            }
        }
    }
    let mut stems = BTreeMap::new();
    if let Some(stemmer) = stemmer {
        let values = stemmer.stem_words(
            &vocabulary
                .iter()
                .map(|w| PythonText::from(w.as_str()))
                .collect::<Vec<_>>(),
        )?;
        if values.len() != vocabulary.len() {
            return Err(RetrievalError::Invalid(
                if values.len() < vocabulary.len() {
                    "zip() argument 2 is shorter than argument 1"
                } else {
                    "zip() argument 2 is longer than argument 1"
                }
                .into(),
            ));
        }
        stems.extend(vocabulary.iter().cloned().zip(values));
    }
    let query_stems: BTreeSet<Vec<u32>> = words
        .iter()
        .filter_map(|w| stems.get(w))
        .map(|s| s.codepoints().to_vec())
        .collect();
    let present: Vec<_> = memberships.iter().map(|m| !m.is_empty()).collect();
    let summaries = alignment.summarize_maxima(
        &FloatMatrix::F32(Matrix::new(memberships.len(), words.len(), peaks)?),
        &present,
    )?;
    let word_set: BTreeSet<_> = words.iter().collect();
    let mut out = Vec::new();
    for (di, document) in documents.iter().enumerate() {
        let mut row = BTreeMap::new();
        for (fi, field) in fields.iter().enumerate() {
            let terms = terms(document, field)?;
            let index = di * fields.len() + fi;
            let c = summaries[index];
            let set: BTreeSet<_> = terms.iter().collect();
            let mean: Vec<_> = sums[index]
                .iter()
                .map(|v| {
                    if terms.is_empty() {
                        0.
                    } else {
                        v / terms.len() as f64
                    }
                })
                .collect();
            let norm = DenseMath::dot64(&mean, &mean)?.sqrt();
            let mean_cosine = if norm != 0. {
                DenseMath::dot64(
                    &sentence.iter().map(|v| *v as f64).collect::<Vec<_>>(),
                    &mean,
                )? / norm
            } else {
                0.
            };
            let values = [
                word_set.intersection(&set).count() as f64 / words.len().max(1) as f64,
                c.mean,
                c.minimum,
                c.quartile,
                c.above50,
                c.above70,
                c.weighted,
                mean_cosine,
                (terms.len() as f64).ln_1p(),
            ];
            row.extend(
                STAT_NAMES
                    .iter()
                    .zip(values)
                    .map(|(stat, v)| (format!("{field}_{stat}"), v)),
            );
            if !stems.is_empty() {
                let field_stems: BTreeSet<Vec<u32>> = terms
                    .iter()
                    .map(|w| stems[w].codepoints().to_vec())
                    .collect();
                row.insert(
                    format!("{field}_stem"),
                    query_stems.intersection(&field_stems).count() as f64
                        / query_stems.len().max(1) as f64,
                );
            }
        }
        out.push(row);
    }
    Ok(out)
}

fn maximum(a: f32, b: f32) -> f32 {
    if a.is_nan() {
        a
    } else if b.is_nan() {
        b
    } else {
        a.max(b)
    }
}
