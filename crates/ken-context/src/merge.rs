use crate::{FusionMode, Policy, RankedItem, text};
use std::collections::BTreeMap;
fn reason(a: &ken_text::PythonText, b: &ken_text::PythonText) -> ken_text::PythonText {
    if a.is_empty() {
        return b.clone();
    }
    if b.is_empty()
        || a.codepoints()
            .windows(b.codepoints().len())
            .any(|w| w == b.codepoints())
    {
        a.clone()
    } else {
        text::append(a, " | ", b.clone())
    }
}
pub(crate) fn symbols(items: impl IntoIterator<Item = RankedItem>) -> Vec<RankedItem> {
    let mut out = Vec::<RankedItem>::new();
    let mut positions = BTreeMap::<Vec<u32>, usize>::new();
    for item in items {
        if item.target_type != "symbol" {
            continue;
        }
        if let Some(&index) = positions.get(item.target.codepoints()) {
            if item.score > out[index].score {
                out[index] = item;
            }
        } else {
            positions.insert(item.target.codepoints().to_vec(), out.len());
            out.push(item);
        }
    }
    out
}
pub(crate) fn files(channels: &[Vec<RankedItem>], policy: &Policy) -> Vec<RankedItem> {
    if policy.fusion == FusionMode::LogOdds {
        return logodds(channels, policy);
    }
    let mut out = Vec::<RankedItem>::new();
    let mut positions = BTreeMap::<Vec<u32>, usize>::new();
    let mut counts = Vec::new();
    for item in channels.iter().flatten() {
        if item.target_type != "file" {
            continue;
        }
        if let Some(&i) = positions.get(item.target.codepoints()) {
            out[i].score = out[i].score.max(item.score);
            out[i].reason = reason(&out[i].reason, &item.reason);
            counts[i] += 1;
        } else {
            positions.insert(item.target.codepoints().to_vec(), out.len());
            counts.push(1);
            out.push(item.clone());
        }
    }
    for (item, count) in out.iter_mut().zip(counts) {
        if count > 1 {
            let bonus = 0.5 * (count - 1) as f64;
            item.score += bonus;
            item.reason = reason(
                &item.reason,
                &format!("synergy×{count}(+{bonus:.1})").into(),
            );
        }
    }
    out
}
fn probability(reason: &str, raw: f64) -> (&'static str, f64) {
    let prefix = reason
        .split(':')
        .next()
        .unwrap_or("")
        .split(' ')
        .next()
        .unwrap_or("");
    match prefix {
        "explicit-mention" => return ("explicit", 0.93),
        "explicit-symbol-mention" => return ("explicit", 0.80),
        "explicit-line-mention" => return ("explicit", 0.95),
        _ => (),
    };
    let (family, lo, hi) = match prefix {
        "reactive" | "predictive" => ("behavioral", 0.3, 6.),
        "cooc" => ("behavioral", 0.3, 3.),
        "doc-intent-symbol" => ("nametext", 0.2, 2.1),
        "doc-intent" => ("nametext", 0.2, 3.2),
        "literal" => ("nametext", 1.15, 2.5),
        "lexical" | "lexical-context" => ("nametext", 0.6, 1.4),
        _ => ("nametext", 0.3, 4.5),
    };
    let fraction = ((raw - lo) / (hi - lo)).clamp(0., 1.);
    let logit = 0.20 + fraction * 2.;
    (family, 1. / (1. + (-logit).exp()))
}
struct Evidence {
    item: RankedItem,
    families: Vec<(&'static str, Vec<f64>)>,
    reasons: Vec<ken_text::PythonText>,
}
fn logodds(channels: &[Vec<RankedItem>], policy: &Policy) -> Vec<RankedItem> {
    let mut all = Vec::<Evidence>::new();
    let mut positions = BTreeMap::<Vec<u32>, usize>::new();
    for item in channels.iter().flatten() {
        if item.target_type != "file" {
            continue;
        }
        let index = *positions
            .entry(item.target.codepoints().to_vec())
            .or_insert_with(|| {
                all.push(Evidence {
                    item: item.clone(),
                    families: Vec::new(),
                    reasons: Vec::new(),
                });
                all.len() - 1
            });
        let row = &mut all[index];
        let (family, p) = probability(&text::matching(&item.reason), item.score);
        if let Some((_, values)) = row.families.iter_mut().find(|(f, _)| *f == family) {
            values.push(p);
        } else {
            row.families.push((family, vec![p]));
        }
        if !row.reasons.contains(&item.reason) {
            row.reasons.push(item.reason.clone());
        }
    }
    all.into_iter()
        .map(|mut row| {
            let mut logit = 0.;
            for (family, values) in &row.families {
                let complement = values.iter().fold(1., |product, p| product * (1. - p));
                let p = (1. - complement).clamp(1e-6, 1. - 1e-6);
                logit +=
                    policy.family_weights.get(*family).copied().unwrap_or(1.) * (p / (1. - p)).ln();
            }
            row.item.score = (policy.fusion_scale * logit).max(0.);
            row.item.reason = text::join(row.reasons, " | ");
            if row.families.len() > 1 {
                row.item.reason = text::append(
                    &row.item.reason,
                    " | ",
                    format!("fused×{}fam", row.families.len()),
                );
            }
            row.item
        })
        .collect()
}
