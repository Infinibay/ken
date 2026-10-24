//! Project complete requested units into the registered piece feature schema.
use crate::{
    Result, RetrievalError,
    coverage::{STAT_NAMES, TermDocument, coverage},
    description::OwnerDescription,
    feature_matrix::FeatureMatrix,
    intent::{interpret, requested_piece_kind},
    matrix::Matrix,
    piece_candidates::PieceCandidate,
    query::SearchRequest,
    stemming::WordStemmer,
    vocabulary::code_terms_python,
    word_encoder::WordEncoder,
};
use ken_text::PythonText;
use std::collections::BTreeSet;

const FIELDS: [&str; 8] = [
    "identity",
    "signature",
    "documentation",
    "executable",
    "calls",
    "returns",
    "path",
    "all",
];
const KINDS: [&str; 4] = ["class", "module", "symbol", "file"];
const DECLARATIONS: [&str; 8] = [
    "class",
    "interface",
    "enum",
    "type",
    "function",
    "method",
    "module",
    "constant",
];
const SCALARS: [&str; 18] = [
    "native_score",
    "native_to_best",
    "native_rank",
    "member_log_count",
    "matched_log_count",
    "matched_fraction",
    "member_score_mean3",
    "member_score_gap",
    "declaration_present",
    "declaration_in_matches",
    "declaration_score_to_best",
    "log_owned_lines",
    "log_executable_lines",
    "documentation_fraction",
    "test_path",
    "data_file",
    "request_tests",
    "request_documentation",
];

pub fn piece_feature_names() -> Vec<PythonText> {
    let mut names: Vec<String> = SCALARS.iter().map(|s| s.to_string()).collect();
    names.extend(KINDS.map(|s| format!("request_{s}")));
    names.extend(DECLARATIONS.map(|s| format!("declaration_kind_{s}")));
    for (prefix, expanded) in [("original", false), ("piece", true), ("declaration", true)] {
        for field in FIELDS {
            names.push(format!("{prefix}_{field}_exact"));
            if expanded {
                names.push(format!("{prefix}_{field}_stem"));
            }
            names.extend(
                STAT_NAMES[1..]
                    .iter()
                    .map(|s| format!("{prefix}_{field}_{s}")),
            );
        }
    }
    names.into_iter().map(PythonText::from).collect()
}

fn join(values: &[PythonText]) -> PythonText {
    let mut points = Vec::new();
    for (i, value) in values.iter().enumerate() {
        if i > 0 {
            points.push(10);
        }
        points.extend_from_slice(value.codepoints());
    }
    PythonText::from_codepoints(points).expect("existing source codepoints")
}

fn document(members: &[&OwnerDescription], identity: &str) -> TermDocument {
    let mut fields = Vec::new();
    for field in &FIELDS[..7] {
        let mut seen = BTreeSet::new();
        let mut values = Vec::new();
        for member in members {
            let value = member
                .fields
                .get(*field)
                .cloned()
                .unwrap_or_else(|| "".into());
            if seen.insert(value.codepoints().to_vec()) {
                values.push(value);
            }
        }
        let value = join(&values);
        fields.push(if *field == "identity" {
            join(&[identity.into(), value])
        } else {
            value
        });
    }
    // `all` follows the original field insertion order, not map key order.
    fields.push(join(&fields));
    FIELDS
        .into_iter()
        .zip(fields)
        .map(|(field, text)| (field.into(), code_terms_python(&text, Some(4096))))
        .collect()
}

/// Python3.12 float sum preserves a small residual between cancelling priors.
/// Keep this separate from NumPy pairwise reduction and ordered tree addition.
/// See CPython v3.12.9 Python/bltinmodule.c, builtin_sum_impl.
fn prior_sum(values: impl Iterator<Item = f64>) -> f64 {
    let mut total = 0_f64;
    let mut correction = 0_f64;
    for value in values {
        let next = total + value;
        correction += if total.abs() >= value.abs() {
            (total - next) + value
        } else {
            (value - next) + total
        };
        total = next;
    }
    if correction != 0. && correction.is_finite() {
        total += correction;
    }
    total
}

pub fn piece_features(
    request: &SearchRequest,
    pieces: &[PieceCandidate],
    encoder: &dyn WordEncoder,
    stemmer: &dyn WordStemmer,
    expanded: Option<&PythonText>,
) -> Result<FeatureMatrix> {
    let kind = requested_piece_kind(request);
    let names = piece_feature_names();
    if pieces.iter().any(|p| p.kind() != kind) {
        return Err(RetrievalError::Invalid(
            "piece candidates differ from requested kind".into(),
        ));
    }
    if pieces.is_empty() {
        return Ok(FeatureMatrix {
            values: Matrix::new(0, names.len(), vec![])?,
            names,
        });
    }
    let documents: Vec<_> = pieces
        .iter()
        .map(|p| {
            let identity = format!(
                "{}\n{}",
                p.path(),
                p.entity().and_then(|e| e.qualname.as_deref()).unwrap_or("")
            );
            document(
                &p.members().iter().map(|m| m.as_ref()).collect::<Vec<_>>(),
                &identity,
            )
        })
        .collect();
    let declarations: Vec<_> = pieces
        .iter()
        .map(|p| document(&p.declaration().into_iter().collect::<Vec<_>>(), ""))
        .collect();
    let expanded = expanded
        .filter(|s| !s.is_empty())
        .unwrap_or(request.query());
    let original = coverage(request.query(), &documents, &FIELDS, encoder, None)?;
    let whole = coverage(expanded, &documents, &FIELDS, encoder, Some(stemmer))?;
    let direct = coverage(expanded, &declarations, &FIELDS, encoder, Some(stemmer))?;
    let purpose = interpret(request).purpose;
    let best_score = pieces[0].matches()[0].score;
    let mut values = Vec::new();
    for (rank, piece) in pieces.iter().enumerate() {
        let mut ordered: Vec<_> = piece.matches().iter().collect();
        ordered.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let top = &ordered[..ordered.len().min(3)];
        let root = piece.declaration();
        let root_match = ordered
            .iter()
            .find(|m| root.is_some_and(|r| r.entity == m.entity));
        let (owned, executable) =
            piece
                .members()
                .iter()
                .try_fold((0_usize, 0_usize), |(owned, executable), m| {
                    owned
                        .checked_add(m.owned_lines)
                        .zip(executable.checked_add(m.executable_lines))
                        .ok_or_else(|| {
                            RetrievalError::Invalid(
                                "piece line count exceeds the native source limit".into(),
                            )
                        })
                })?;
        let path = piece
            .path()
            .split('/')
            .filter(|p| !p.is_empty() && *p != ".");
        let test_path = path.clone().any(|p| {
            matches!(
                p,
                "test" | "tests" | "typing_tests" | "platform-tests" | "spec" | "specs"
            )
        });
        let suffix = std::path::Path::new(piece.path())
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("");
        values.extend([
            ordered[0].score,
            ordered[0].score - best_score,
            1. / (rank + 1) as f64,
            (piece.members().len() as f64).ln_1p(),
            (ordered.len() as f64).ln_1p(),
            ordered.len() as f64 / piece.members().len() as f64,
            prior_sum(top.iter().map(|m| m.score)) / top.len() as f64,
            ordered[0].score - ordered.get(1).unwrap_or(&ordered[0]).score,
            f64::from(root.is_some()),
            f64::from(root_match.is_some()),
            root_match.map_or(0., |m| m.score - ordered[0].score),
            (owned as f64).ln_1p(),
            (executable as f64).ln_1p(),
            1. - executable as f64 / owned.max(1) as f64,
            f64::from(test_path),
            f64::from(matches!(suffix, "json" | "yaml" | "yml" | "toml")),
            f64::from(purpose == "tests"),
            f64::from(purpose == "documentation"),
        ]);
        values.extend(KINDS.map(|k| f64::from(kind == k)));
        values.extend(DECLARATIONS.map(|k| f64::from(root.is_some_and(|r| r.entity.kind == k))));
        for (prefix, stats, expanded) in [
            ("original", &original[rank], false),
            ("piece", &whole[rank], true),
            ("declaration", &direct[rank], true),
        ] {
            for field in FIELDS {
                let statistics = ["exact"]
                    .into_iter()
                    .chain(expanded.then_some("stem"))
                    .chain(STAT_NAMES[1..].iter().copied());
                for stat in statistics {
                    let key = format!("{field}_{stat}");
                    let value = stats
                        .get(&key)
                        .ok_or_else(|| RetrievalError::Invalid(format!("'{prefix}_{key}'")))?;
                    values.push(*value);
                }
            }
        }
    }
    Ok(FeatureMatrix {
        values: Matrix::new(pieces.len(), names.len(), values)?,
        names,
    })
}
