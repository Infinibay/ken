//! Validated named forests, ordered prediction, and reproducible pair accounting.
use crate::{matrix::Matrix, rank_json as json};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug, thiserror::Error)]
#[error("{message}")]
pub struct NumericError {
    kind: &'static str,
    message: String,
}
pub type NumericResult<T> = std::result::Result<T, NumericError>;
impl NumericError {
    pub fn kind(&self) -> &'static str {
        self.kind
    }
    pub(crate) fn value(message: impl Into<String>) -> Self {
        Self::typed("ValueError", message)
    }
    pub(crate) fn typed(kind: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}
#[derive(Clone, Debug)]
enum Tree {
    Leaf(f64),
    Split {
        feature: usize,
        boolean: bool,
        threshold: f64,
        left: Box<Tree>,
        right: Box<Tree>,
    },
}
type Object = json::Object;
fn object(raw: &str) -> NumericResult<Object> {
    json::object(raw)
}
fn get<'a>(data: &'a Object, key: &str) -> NumericResult<&'a RawValue> {
    data.get(key)
        .ok_or_else(|| NumericError::typed("KeyError", format!("'{key}'")))
}
impl Tree {
    fn parse(raw: &RawValue, size: usize, depth: usize) -> NumericResult<Self> {
        if depth > 64 {
            return Err(NumericError::value("ranking tree exceeds supported depth"));
        }
        let data = object(raw.get())
            .map_err(|_| NumericError::value("unsupported ranking tree schema"))?;
        if data.len() == 1 && data.contains_key("value") {
            let value = json::number(get(&data, "value")?)?;
            if !value.is_finite() {
                return Err(NumericError::value("finite leaf value required"));
            }
            return Ok(Self::Leaf(value));
        }
        if data.len() != 4
            || !["feature", "threshold", "left", "right"]
                .iter()
                .all(|k| data.contains_key(k))
        {
            return Err(NumericError::value("unsupported ranking tree schema"));
        }
        let index = get(&data, "feature")?;
        let boolean = json::kind(index) == "bool";
        let feature = if boolean {
            Some(usize::from(index.get() == "true"))
        } else if json::kind(index) == "int" {
            index.get().parse::<usize>().ok()
        } else {
            None
        };
        let feature = feature
            .filter(|i| *i < size)
            .ok_or_else(|| NumericError::value("ranking tree references an unknown feature"))?;
        let threshold = json::number(get(&data, "threshold")?)?;
        if !threshold.is_finite() {
            return Err(NumericError::value("finite split threshold required"));
        }
        Ok(Self::Split {
            feature,
            boolean,
            threshold,
            left: Box::new(Self::parse(get(&data, "left")?, size, depth + 1)?),
            right: Box::new(Self::parse(get(&data, "right")?, size, depth + 1)?),
        })
    }
    fn canonical(&self) -> String {
        match self {
            Self::Leaf(v) => format!("{{\"value\":{}}}", json::float(*v)),
            Self::Split {
                feature,
                boolean,
                threshold,
                left,
                right,
            } => format!(
                "{{\"feature\":{},\"left\":{},\"right\":{},\"threshold\":{}}}",
                if *boolean {
                    if *feature == 0 {
                        "false".into()
                    } else {
                        "true".into()
                    }
                } else {
                    feature.to_string()
                },
                left.canonical(),
                right.canonical(),
                json::float(*threshold)
            ),
        }
    }
    fn leaf(&self, row: &[f64]) -> f64 {
        let mut node = self;
        while let Self::Split {
            feature,
            threshold,
            left,
            right,
            ..
        } = node
        {
            node = if row[*feature] <= *threshold {
                left
            } else {
                right
            };
        }
        let Self::Leaf(v) = node else { unreachable!() };
        *v
    }
    fn path(&self, row: &[f64], names: &[PythonText]) -> NumericResult<(f64, Vec<PathStep>)> {
        let mut node = self;
        let mut path = Vec::new();
        while let Self::Split {
            feature,
            boolean,
            threshold,
            left,
            right,
        } = node
        {
            // Python row[bool] adds an axis, which float(array) rejects.
            if *boolean {
                return Err(NumericError::typed(
                    "TypeError",
                    "only 0-dimensional arrays can be converted to Python scalars",
                ));
            }
            let value = row[*feature];
            let choose_left = value <= *threshold;
            path.push(PathStep {
                feature: names[*feature].clone(),
                feature_index: *feature,
                value,
                threshold: *threshold,
                branch: if choose_left { "left" } else { "right" }.into(),
            });
            node = if choose_left { left } else { right };
        }
        let Self::Leaf(v) = node else { unreachable!() };
        Ok((*v, path))
    }
}
#[derive(Clone, Debug)]
pub struct NumericRanker {
    features: Vec<PythonText>,
    trees: Vec<Tree>,
    fingerprint: std::sync::OnceLock<NumericResult<String>>,
}
impl NumericRanker {
    pub fn from_json(raw: &str) -> NumericResult<Self> {
        let data = object(raw)?;
        if data.get("schema").is_none_or(|r| {
            !matches!(json::kind(r), "int" | "float" | "bool") || json::number(r).ok() != Some(1.)
        }) {
            return Err(NumericError::value("unsupported numeric ranking schema"));
        }
        let raw_names = get(&data, "features")?;
        let names: Vec<Box<RawValue>> = match json::kind(raw_names) {
            "list" => serde_json::from_str(raw_names.get())
                .map_err(|e| NumericError::value(e.to_string()))?,
            "str" => json::text(raw_names)?
                .codepoints()
                .iter()
                .map(|p| {
                    serde_json::value::to_raw_value(&PythonText::from_codepoints(vec![*p]).unwrap())
                        .unwrap()
                })
                .collect(),
            "dict" => object(raw_names.get())?
                .keys()
                .map(|s| serde_json::value::to_raw_value(s).unwrap())
                .collect(),
            name => {
                return Err(NumericError::typed(
                    "TypeError",
                    format!("'{name}' object is not iterable"),
                ));
            }
        };
        if !(1..=512).contains(&names.len()) {
            return Err(NumericError::value(
                "unique named ranking features required",
            ));
        }
        if let Some(raw) = names
            .iter()
            .find(|r| matches!(json::kind(r), "dict" | "list"))
        {
            return Err(NumericError::typed(
                "TypeError",
                format!("unhashable type: '{}'", json::kind(raw)),
            ));
        }
        let features: Vec<_> = names
            .iter()
            .map(|r| {
                if json::kind(r) == "str" {
                    json::text(r)
                } else {
                    Err(NumericError::value(
                        "unique named ranking features required",
                    ))
                }
            })
            .collect::<NumericResult<_>>()?;
        let unique: BTreeSet<_> = features.iter().map(|s| s.codepoints()).collect();
        if features.iter().any(PythonText::is_empty) || unique.len() != features.len() {
            return Err(NumericError::value(
                "unique named ranking features required",
            ));
        }
        let raw_trees = get(&data, "trees")?;
        let trees: Vec<Box<RawValue>> = match json::kind(raw_trees) {
            "list" => serde_json::from_str(raw_trees.get())
                .map_err(|e| NumericError::value(e.to_string()))?,
            "str" => json::text(raw_trees)?
                .codepoints()
                .iter()
                .map(|p| {
                    serde_json::value::to_raw_value(&PythonText::from_codepoints(vec![*p]).unwrap())
                        .unwrap()
                })
                .collect(),
            "dict" => object(raw_trees.get())?
                .keys()
                .map(|s| serde_json::value::to_raw_value(s).unwrap())
                .collect(),
            name => {
                return Err(NumericError::typed(
                    "TypeError",
                    format!("object of type '{name}' has no len()"),
                ));
            }
        };
        if !(1..=4096).contains(&trees.len()) {
            return Err(NumericError::value(
                "bounded nonempty ranking forest required",
            ));
        }
        Ok(Self {
            trees: trees
                .iter()
                .map(|r| Tree::parse(r, features.len(), 0))
                .collect::<NumericResult<_>>()?,
            features,
            fingerprint: std::sync::OnceLock::new(),
        })
    }
    pub fn features(&self) -> &[PythonText] {
        &self.features
    }
    pub fn tree_count(&self) -> usize {
        self.trees.len()
    }
    pub fn to_json(&self) -> NumericResult<String> {
        Ok(format!(
            "{{\"features\":[{}],\"schema\":1,\"trees\":[{}]}}",
            self.features
                .iter()
                .map(json::quote)
                .collect::<Vec<_>>()
                .join(","),
            self.trees
                .iter()
                .map(Tree::canonical)
                .collect::<Vec<_>>()
                .join(",")
        ))
    }
    pub fn fingerprint(&self) -> NumericResult<String> {
        self.fingerprint
            .get_or_init(|| self.compute_fingerprint())
            .clone()
    }
    fn compute_fingerprint(&self) -> NumericResult<String> {
        let canonical = self.to_json()?;
        // ensure_ascii=false emits surrogate code points, which UTF-8 cannot encode.
        let mut offset = 13;
        for feature in &self.features {
            if let Some(i) = feature
                .codepoints()
                .iter()
                .position(|c| (0xd800..=0xdfff).contains(c))
            {
                let run = feature.codepoints()[i..]
                    .iter()
                    .take_while(|c| (0xd800..=0xdfff).contains(*c))
                    .count();
                let prefix =
                    PythonText::from_codepoints(feature.codepoints()[..i].to_vec()).unwrap();
                let position = offset + json::quote(&prefix).chars().count() - 1;
                let details = if run == 1 {
                    format!(
                        "character '\\u{:04x}' in position {position}",
                        feature.codepoints()[i]
                    )
                } else {
                    format!("characters in position {position}-{}", position + run - 1)
                };
                return Err(NumericError::typed(
                    "UnicodeEncodeError",
                    format!("'utf-8' codec can't encode {details}: surrogates not allowed"),
                ));
            }
            offset += json::quote(feature).chars().count() + 1;
        }
        Ok(format!("{:x}", Sha256::digest(canonical.as_bytes())))
    }
    pub fn predict(&self, matrix: &Matrix<f64>) -> NumericResult<Vec<f64>> {
        if matrix.columns() != self.features.len() {
            return Err(NumericError::value("ranking feature schema mismatch"));
        }
        if matrix.values().iter().any(|v| !v.is_finite()) {
            return Err(NumericError::value("finite ranking features required"));
        }
        if matrix.rows() <= 128 {
            return Ok(matrix
                .values()
                .chunks(matrix.columns())
                .map(|row| self.trees.iter().fold(0., |sum, tree| sum + tree.leaf(row)))
                .collect());
        }
        let mut result = vec![0.; matrix.rows()];
        for tree in &self.trees {
            let mut pending = vec![(tree, (0..matrix.rows()).collect::<Vec<_>>())];
            while let Some((node, indices)) = pending.pop() {
                if indices.is_empty() {
                    continue;
                }
                match node {
                    Tree::Leaf(value) => {
                        for i in indices {
                            result[i] += value;
                        }
                    }
                    Tree::Split {
                        feature,
                        boolean,
                        threshold,
                        left,
                        right,
                    } => {
                        if *boolean {
                            let message = if *feature == 0 && indices.len() > 1 {
                                format!(
                                    "shape mismatch: indexing arrays could not be broadcast together with shapes ({},) (0,) ",
                                    indices.len()
                                )
                            } else {
                                "too many indices for array: array is 1-dimensional, but 2 were indexed".into()
                            };
                            return Err(NumericError::typed("IndexError", message));
                        }
                        let (a, b): (Vec<_>, Vec<_>) = indices.into_iter().partition(|i| {
                            matrix.values()[i * matrix.columns() + feature] <= *threshold
                        });
                        pending.push((left, a));
                        pending.push((right, b));
                    }
                }
            }
        }
        Ok(result)
    }
    pub fn explain_pair(&self, left: &[f64], right: &[f64]) -> NumericResult<PairExplanation> {
        if left.len() != self.features.len() || right.len() != self.features.len() {
            return Err(NumericError::value(
                "one ranking feature vector per candidate required",
            ));
        }
        let matrix = Matrix::new(2, self.features.len(), [left, right].concat())
            .expect("checked pair shape");
        let scores = self.predict(&matrix)?;
        let margin = scores[0] - scores[1];
        if scores.iter().any(|v| !v.is_finite()) || !margin.is_finite() {
            return Err(NumericError::value(
                "finite ranking scores and margin required",
            ));
        }
        let mut trees = Vec::new();
        let mut grouped: BTreeMap<Vec<u32>, (PythonText, Vec<f64>)> = BTreeMap::new();
        for (tree_index, tree) in self.trees.iter().enumerate() {
            let (left_leaf, left_path) = tree.path(left, &self.features)?;
            let (right_leaf, right_path) = tree.path(right, &self.features)?;
            let delta = left_leaf - right_leaf;
            let first_divergence = left_path
                .iter()
                .zip(&right_path)
                .find(|(a, b)| a.branch != b.branch)
                .map(|(a, b)| Divergence {
                    feature: a.feature.clone(),
                    threshold: a.threshold,
                    left_value: a.value,
                    right_value: b.value,
                    left_branch: a.branch.clone(),
                    right_branch: b.branch.clone(),
                });
            if let Some(d) = &first_divergence {
                grouped
                    .entry(d.feature.codepoints().to_vec())
                    .or_insert_with(|| (d.feature.clone(), Vec::new()))
                    .1
                    .push(delta);
            }
            trees.push(TreeExplanation {
                tree_index,
                left_leaf,
                right_leaf,
                delta,
                first_divergence,
                left_path,
                right_path,
            });
        }
        let accounted = accurate_sum(trees.iter().map(|t| t.delta))?;
        let branch_margin_by_feature = grouped
            .into_values()
            .map(|(name, values)| Ok((name, accurate_sum(values.into_iter())?)))
            .collect::<NumericResult<Vec<_>>>()?;
        Ok(PairExplanation {model_fingerprint:self.fingerprint()?,left_score:scores[0],right_score:scores[1],margin,trees,branch_margin_by_feature,rounding_residual:margin-accounted,attribution:"Tree leaf differences grouped by first divergent split; interaction accounting, not isolated causal feature effects or SHAP.".into()})
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PathStep {
    pub feature: PythonText,
    pub feature_index: usize,
    pub value: f64,
    pub threshold: f64,
    pub branch: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Divergence {
    pub feature: PythonText,
    pub threshold: f64,
    pub left_value: f64,
    pub right_value: f64,
    pub left_branch: String,
    pub right_branch: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TreeExplanation {
    pub tree_index: usize,
    pub left_leaf: f64,
    pub right_leaf: f64,
    #[serde(with = "crate::number_json")]
    pub delta: f64,
    pub first_divergence: Option<Divergence>,
    pub left_path: Vec<PathStep>,
    pub right_path: Vec<PathStep>,
}
#[derive(Clone, Debug, Serialize)]
pub struct PairExplanation {
    pub model_fingerprint: String,
    pub left_score: f64,
    pub right_score: f64,
    pub margin: f64,
    pub trees: Vec<TreeExplanation>,
    #[serde(serialize_with = "serialize_margins")]
    pub branch_margin_by_feature: Vec<(PythonText, f64)>,
    #[serde(serialize_with = "crate::number_json::serialize")]
    pub rounding_residual: f64,
    pub attribution: String,
}
fn serialize_margins<S: serde::Serializer>(
    values: &[(PythonText, f64)],
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    use serde::ser::SerializeMap;
    let mut map = serializer.serialize_map(Some(values.len()))?;
    for (name, value) in values {
        let name = name
            .to_utf8()
            .ok_or_else(|| serde::ser::Error::custom("non-scalar ranking feature"))?;
        map.serialize_entry(&name, &crate::number_json::value(*value))?;
    }
    map.end()
}
// Error-free partial sums followed by half-even correction, matching math.fsum.
// Algorithm reference: CPython v3.12.9 Modules/mathmodule.c, math_fsum.
fn accurate_sum(values: impl Iterator<Item = f64>) -> NumericResult<f64> {
    let mut partials: Vec<f64> = Vec::new();
    let mut special = 0.;
    let mut inf = 0.;
    for original in values {
        let mut x = original;
        let mut used = 0;
        for j in 0..partials.len() {
            let mut y = partials[j];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let lo = y - (hi - x);
            if lo != 0. {
                partials[used] = lo;
                used += 1;
            }
            x = hi;
        }
        partials.truncate(used);
        if x != 0. {
            if !x.is_finite() {
                if original.is_finite() {
                    return Err(NumericError::typed(
                        "OverflowError",
                        "intermediate overflow in fsum",
                    ));
                }
                if original.is_infinite() {
                    inf += original;
                }
                special += original;
                partials.clear();
            } else {
                partials.push(x);
            }
        }
    }
    if special != 0. {
        if inf.is_nan() {
            return Err(NumericError::value("-inf + inf in fsum"));
        }
        return Ok(special);
    }
    let mut hi = partials.pop().unwrap_or(0.);
    let mut lo = 0.;
    while let Some(y) = partials.pop() {
        let x = hi;
        hi = x + y;
        lo = y - (hi - x);
        if lo != 0. {
            break;
        }
    }
    if partials
        .last()
        .is_some_and(|p| (lo < 0. && *p < 0.) || (lo > 0. && *p > 0.))
    {
        let y = lo * 2.;
        let x = hi + y;
        if y == x - hi {
            hi = x;
        }
    }
    Ok(hi)
}
