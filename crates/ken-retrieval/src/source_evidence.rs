//! Cover distinct query cues with faithful fragments of one physical owner.
use crate::{
    Passage, Result, RetrievalError, Span,
    evidence::{MAX_EVIDENCE_LINES, combinations, source_bounds, source_text, verified_lines},
    intent::interpret,
    query::{CodeMatch, SearchRequest},
    source_snapshot::SourceAuthority,
    stemming::WordStemmer,
    vocabulary::code_terms_python,
};
use ken_text::PythonText;
use std::collections::{BTreeMap, BTreeSet};
/// The number of query cues determines storage; cue 64 is not a truncation point.
#[derive(Clone, Debug, PartialEq, Eq)]
struct CueMask(Vec<u64>);
impl CueMask {
    fn empty(cues: usize) -> Self {
        Self(vec![0; cues.div_ceil(64)])
    }
    fn insert(&mut self, index: usize) {
        self.0[index / 64] |= 1 << (index % 64);
    }
    fn union(&mut self, other: &Self) {
        for (a, b) in self.0.iter_mut().zip(&other.0) {
            *a |= b;
        }
    }
    fn count(&self) -> u32 {
        self.0.iter().map(|w| w.count_ones()).sum()
    }
    fn adds_to(&self, other: &Self) -> bool {
        self.0.iter().zip(&other.0).any(|(a, b)| a & !b != 0)
    }
}
fn tokens(text: &PythonText) -> BTreeSet<Vec<u32>> {
    code_terms_python(text, None)
        .into_iter()
        .map(|word| word.chars().map(u32::from).collect())
        .collect()
}
fn window_masks(
    regions: &BTreeSet<Span>,
    masks: &BTreeMap<usize, CueMask>,
    width: usize,
    cues: usize,
) -> Vec<(Span, CueMask)> {
    let mut proposals = BTreeMap::new();
    for region in regions {
        let size = width.min(region.end_line - region.start_line + 1);
        let mut starts = BTreeSet::from([region.start_line, region.end_line - size + 1]);
        for (&line, mask) in masks {
            if mask.count() == 0 || line < region.start_line || line > region.end_line {
                continue;
            }
            for start in [
                line as i128 - size as i128 + 1,
                line as i128 - (size / 2) as i128,
                line as i128,
            ] {
                starts.insert(
                    start
                        .min((region.end_line - size + 1) as i128)
                        .max(region.start_line as i128) as usize,
                );
            }
        }
        for start in starts {
            let span = Span {
                start_line: start,
                end_line: start + size - 1,
            };
            let mut covered = CueMask::empty(cues);
            for line in span.start_line..=span.end_line {
                if let Some(mask) = masks.get(&line) {
                    covered.union(mask);
                }
            }
            proposals.insert(span, covered);
        }
    }
    let mut ordered: Vec<_> = proposals.into_iter().collect();
    ordered.sort_by(|(a, x), (b, y)| y.count().cmp(&x.count()).then_with(|| a.cmp(b)));
    let mut selected = Vec::new();
    let mut covered = CueMask::empty(cues);
    for item in &ordered {
        if item.1.adds_to(&covered) {
            covered.union(&item.1);
            selected.push(item.clone());
        }
        if selected.len() == 24 {
            break;
        }
    }
    for item in ordered {
        if !selected.contains(&item) {
            selected.push(item);
        }
    }
    selected.truncate(24);
    selected
}
fn select(
    owner: &CodeMatch,
    lines: &[String],
    query: &BTreeSet<Vec<u32>>,
    stemmer: &dyn WordStemmer,
    purpose: &str,
) -> Result<Option<Vec<Passage>>> {
    let implementation = purpose != "documentation";
    let regions = owner
        .evidence
        .iter()
        .map(|p| source_bounds(owner, p, lines.len(), implementation))
        .collect::<Result<BTreeSet<_>>>()?;
    let mut words_by_line = BTreeMap::new();
    for region in &regions {
        // Every proposed line must remain physical, even for malformed ownership.
        source_text(lines, *region)?;
        for line in region.start_line..=region.end_line {
            words_by_line.insert(line, tokens(&lines[line - 1].as_str().into()));
        }
    }
    let mut vocabulary = query.clone();
    for words in words_by_line.values() {
        vocabulary.extend(words.iter().cloned());
    }
    let vocabulary: Vec<_> = vocabulary
        .into_iter()
        .map(|points| PythonText::from_codepoints(points).expect("source term points"))
        .collect();
    let stemmed = stemmer.stem_words(&vocabulary)?;
    if stemmed.len() != vocabulary.len() {
        return Err(RetrievalError::Invalid(
            "one stem per source vocabulary word required".into(),
        ));
    }
    let stems: BTreeMap<_, _> = vocabulary
        .iter()
        .zip(stemmed)
        .map(|(word, stem)| (word.codepoints().to_vec(), stem.codepoints().to_vec()))
        .collect();
    let distinct: BTreeSet<_> = query.iter().map(|q| stems[q].clone()).collect();
    let terms: BTreeMap<_, _> = distinct
        .into_iter()
        .enumerate()
        .map(|(i, word)| (word, i))
        .collect();
    let mut masks = BTreeMap::new();
    for (line, words) in words_by_line {
        let mut mask = CueMask::empty(terms.len());
        for word in words {
            if let Some(index) = terms.get(&stems[&word]) {
                mask.insert(*index);
            }
        }
        masks.insert(line, mask);
    }
    let mut best: Vec<Span> = Vec::new();
    let mut best_coverage = 0;
    for count in 1..=3 {
        let windows = window_masks(&regions, &masks, MAX_EVIDENCE_LINES / count, terms.len());
        for bundle in combinations(windows.len(), count) {
            let mut spans: Vec<_> = bundle.iter().map(|i| windows[*i].0).collect();
            spans.sort();
            if spans.windows(2).any(|p| p[0].end_line >= p[1].start_line) {
                continue;
            }
            let mut covered = CueMask::empty(terms.len());
            for index in bundle {
                covered.union(&windows[index].1);
            }
            let coverage = covered.count();
            let earlier = spans
                .iter()
                .map(|s| s.start_line)
                .cmp(best.iter().map(|s| s.start_line))
                .is_lt();
            if coverage > best_coverage
                || (coverage == best_coverage
                    && coverage > 0
                    && (count < best.len() || (count == best.len() && earlier)))
            {
                best_coverage = coverage;
                best = spans;
            }
        }
    }
    if best.is_empty() || best_coverage == 0 {
        return Ok(None);
    }
    let mut result = Vec::new();
    for span in best {
        let template = owner
            .evidence
            .iter()
            .find(|p| {
                source_bounds(owner, p, lines.len(), implementation).is_ok_and(|bounds| {
                    bounds.start_line <= span.start_line && bounds.end_line >= span.end_line
                })
            })
            .ok_or_else(|| {
                RetrievalError::Invalid("source window has no supporting owner".into())
            })?;
        let mut passage = template.clone();
        passage.span = span;
        passage.fields.body = source_text(lines, span)?.into();
        passage.signals.insert("selected_window".into(), 1.);
        result.push(passage);
    }
    Ok(Some(result))
}
pub fn refine_source_evidence(
    matches: &[CodeMatch],
    source: &SourceAuthority,
    request: &SearchRequest,
    query: &PythonText,
    stemmer: &dyn WordStemmer,
) -> Result<Vec<CodeMatch>> {
    let intent = interpret(request);
    let mut result = matches.to_vec();
    if intent.identity {
        return Ok(result);
    }
    let query = tokens(query);
    for (index, owner) in matches.iter().take(request.limit()).enumerate() {
        if owner.signals.get("exact").is_some_and(|v| *v != 0.) {
            continue;
        }
        let Ok(lines) = verified_lines(source, owner) else {
            continue;
        };
        if let Some(evidence) = select(owner, &lines, &query, stemmer, &intent.purpose)? {
            result[index].evidence = evidence;
        }
    }
    Ok(result)
}
