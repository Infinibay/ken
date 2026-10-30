//! Dataset and quality policy consume ranked and actually rendered observations.
use crate::{Error, Result};
use ken_text::PythonText;
use rusqlite::Connection;
use serde::Serialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    time::Instant,
};
#[derive(Clone, Debug, Serialize)]
pub struct BenchCase {
    pub prompt: PythonText,
    pub expected_files: Vec<String>,
    pub judgments: BTreeMap<String, f64>,
}
#[derive(Clone, Debug)]
pub struct BenchDataset {
    pub cases: Vec<BenchCase>,
}
impl BenchDataset {
    pub fn from_jsonl(input: &str) -> Result<Self> {
        let mut cases = Vec::new();
        for (line, raw) in input.lines().enumerate() {
            let raw = raw.trim_matches(ken_text::unicode::whitespace);
            if raw.is_empty() || raw.starts_with('#') {
                continue;
            }
            let row: Value = serde_json::from_str(raw)
                .map_err(|error| Error::Invalid(format!("benchmark line{}: {error}", line + 1)))?;
            let invalid = || {
                Error::Invalid(format!(
                    "benchmark line{} requires a nonempty prompt, unique expected_files and matching grades0..3",
                    line + 1
                ))
            };
            let row = row.as_object().ok_or_else(invalid)?;
            let prompt = row
                .get("prompt")
                .and_then(Value::as_str)
                .map(|prompt| prompt.trim_matches(ken_text::unicode::whitespace))
                .filter(|prompt| !prompt.is_empty())
                .ok_or_else(invalid)?;
            let expected = row
                .get("expected_files")
                .and_then(Value::as_array)
                .ok_or_else(invalid)?
                .iter()
                .map(|path| {
                    path.as_str()
                        .filter(|path| !path.is_empty())
                        .map(str::to_owned)
                        .ok_or_else(invalid)
                })
                .collect::<Result<Vec<_>>>()?;
            if expected.is_empty()
                || expected.iter().collect::<BTreeSet<_>>().len() != expected.len()
            {
                return Err(invalid());
            }
            let judgments = if let Some(raw) = row.get("judgments").filter(|value| !value.is_null())
            {
                let mut judgments = BTreeMap::new();
                for (path, grade) in raw.as_object().ok_or_else(invalid)? {
                    let grade = grade
                        .as_f64()
                        .filter(|grade| grade.is_finite() && (0.0..=3.0).contains(grade))
                        .ok_or_else(invalid)?;
                    if path.is_empty() {
                        return Err(invalid());
                    }
                    if grade > 0. {
                        judgments.insert(path.clone(), grade);
                    }
                }
                if judgments.keys().collect::<BTreeSet<_>>()
                    != expected.iter().collect::<BTreeSet<_>>()
                {
                    return Err(invalid());
                }
                judgments
            } else {
                expected.iter().map(|path| (path.clone(), 1.)).collect()
            };
            cases.push(BenchCase {
                prompt: prompt.into(),
                expected_files: expected,
                judgments,
            });
        }
        if cases.is_empty() {
            return Err(Error::Invalid("no valid benchmark cases".into()));
        }
        Ok(Self { cases })
    }
}
#[derive(Clone, Debug)]
pub struct BenchOptions {
    pub top: usize,
    pub max_chars: Option<i64>,
    pub verify_index: bool,
    pub fail_under_case_recall: Option<f64>,
    pub fail_under_expected_file_recall: Option<f64>,
    pub explain_misses: bool,
}
impl Default for BenchOptions {
    fn default() -> Self {
        Self {
            top: 8,
            max_chars: Some(4000),
            verify_index: true,
            fail_under_case_recall: None,
            fail_under_expected_file_recall: None,
            explain_misses: false,
        }
    }
}
#[derive(Default)]
pub struct BenchObservation {
    pub ranked: Vec<ken_context::RankedItem>,
    pub visible_files: Vec<PythonText>,
    pub block: PythonText,
    pub timings_ms: BTreeMap<String, f64>,
}
pub trait BenchRunner {
    fn evaluate(
        &mut self,
        prompt: &PythonText,
        top: usize,
        max_chars: Option<i64>,
    ) -> Result<BenchObservation>;
}
pub struct ContextBenchRunner<'a> {
    conn: &'a Connection,
    root: PathBuf,
    queries: &'a dyn ken_retrieval::query_encoder::QueryEncoder,
    numerics: &'a mut dyn ken_context::ContextNumerics,
    policy: ken_context::Policy,
    clock: ken_context::Clock,
}
impl<'a> ContextBenchRunner<'a> {
    pub fn new(
        conn: &'a Connection,
        root: &Path,
        queries: &'a dyn ken_retrieval::query_encoder::QueryEncoder,
        numerics: &'a mut dyn ken_context::ContextNumerics,
        policy: ken_context::Policy,
        clock: ken_context::Clock,
    ) -> Self {
        Self {
            conn,
            root: root.into(),
            queries,
            numerics,
            policy,
            clock,
        }
    }
}
impl BenchRunner for ContextBenchRunner<'_> {
    fn evaluate(
        &mut self,
        prompt: &PythonText,
        top: usize,
        max_chars: Option<i64>,
    ) -> Result<BenchObservation> {
        let e2e = Instant::now();
        let phase = Instant::now();
        let vector = self.queries.embed_query(prompt)?;
        let embed = phase.elapsed().as_secs_f64() * 1000.;
        let phase = Instant::now();
        let result = ken_context::rank(
            self.conn,
            &ken_context::RankRequest {
                agent_id: "__ken_bench__".into(),
                current_iteration: 0,
                prompt: prompt.clone(),
                prompt_embedding: vector,
                top_files: top
                    .try_into()
                    .map_err(|_| Error::Invalid("top exceeds native rank budget".into()))?,
                project_root: Some(self.root.clone()),
                clock: self.clock,
                ..Default::default()
            },
            &self.policy,
            self.numerics,
        )?;
        let rank = phase.elapsed().as_secs_f64() * 1000.;
        let phase = Instant::now();
        let block = ken_context::render_block(
            self.conn,
            &result,
            &ken_context::RenderOptions {
                verbose: 0,
                max_chars: max_chars.filter(|chars| *chars > 0),
                project_root: Some(self.root.clone()),
                ..Default::default()
            },
        )?;
        let visible_files = ken_context::visible_file_paths(&block);
        let render = phase.elapsed().as_secs_f64() * 1000.;
        Ok(BenchObservation {
            ranked: result.files.into_iter().take(top).collect(),
            visible_files,
            block,
            timings_ms: BTreeMap::from([
                ("embed".into(), embed),
                ("rank".into(), rank),
                ("render".into(), render),
                ("e2e".into(), e2e.elapsed().as_secs_f64() * 1000.),
            ]),
        })
    }
}
#[derive(Serialize)]
pub struct RankedDetail {
    pub path: PythonText,
    pub score: f64,
    pub reason: PythonText,
}
#[derive(Serialize)]
pub struct BenchCaseResult {
    pub case: usize,
    pub prompt: PythonText,
    pub expected_files: Vec<String>,
    pub judgments: BTreeMap<String, f64>,
    pub ranked_files: Vec<PythonText>,
    pub visible_files: Vec<PythonText>,
    pub visible_hits: Vec<String>,
    pub visible_reciprocal_rank: f64,
    pub ranked_details: Vec<RankedDetail>,
    pub hits: Vec<String>,
    pub hit: bool,
    pub reciprocal_rank: f64,
    pub ndcg: f64,
    pub context_chars: usize,
    pub context_est_tokens: usize,
    pub timings_ms: BTreeMap<String, f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub misses: Option<Vec<String>>,
}
#[derive(Serialize)]
pub struct BenchReport {
    pub ok: bool,
    pub cases: usize,
    pub top: usize,
    pub case_recall: f64,
    pub expected_file_recall: f64,
    pub mrr: f64,
    pub visible_case_recall: f64,
    pub visible_expected_file_recall: f64,
    pub visible_mrr: f64,
    pub ndcg: f64,
    pub avg_context_chars: f64,
    pub avg_context_est_tokens: f64,
    pub avg_timings_ms: BTreeMap<String, f64>,
    pub results: Vec<BenchCaseResult>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub failures: Vec<String>,
}
fn verify_index(conn: &Connection, root: &Path) -> Result<()> {
    use blake2::digest::{Update, VariableOutput};
    let paths = crate::paths(root)?;
    let reader = ken_core::source_reader::SourceFileReader::new(&paths)?;
    let mut statement = conn.prepare("SELECT path,content_hash FROM ci_files")?;
    let mut count = 0;
    for row in statement.query_map([], |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?))
    })? {
        let (path, expected) = row?;
        let bytes = reader
            .open(Path::new(&path))
            .and_then(|file| file.read())
            .map_err(|_| {
                Error::Invalid(
                    "indexed files do not belong to benchmark project root; check copied index"
                        .into(),
                )
            })?;
        let mut hash = blake2::Blake2bVar::new(32).expect("valid BLAKE2 size");
        hash.update(&bytes);
        let mut actual = [0u8; 32];
        hash.finalize_variable(&mut actual)
            .expect("exact digest size");
        if actual.as_slice() != expected.as_slice() {
            return Err(Error::Invalid(
                "indexed files do not belong to benchmark project root; check copied index".into(),
            ));
        }
        count += 1;
    }
    if count == 0 {
        return Err(Error::Invalid(
            "indexed files do not belong to benchmark project root; index is empty".into(),
        ));
    }
    Ok(())
}
fn ndcg(ranked: &[PythonText], judgments: &BTreeMap<String, f64>, top: usize) -> f64 {
    let gains = ranked
        .iter()
        .take(top)
        .enumerate()
        .map(|(i, path)| {
            let grade = path
                .to_utf8()
                .and_then(|path| judgments.get(&path).copied())
                .unwrap_or(0.);
            (2f64.powf(grade) - 1.) / ((i + 2) as f64).log2()
        })
        .collect::<Vec<_>>();
    let mut ideal = judgments.values().copied().collect::<Vec<_>>();
    ideal.sort_by(|a, b| b.total_cmp(a));
    let ideal = ideal
        .into_iter()
        .take(top)
        .enumerate()
        .map(|(i, grade)| (2f64.powf(grade) - 1.) / ((i + 2) as f64).log2())
        .collect::<Vec<_>>();
    let ideal = ken_retrieval::vector_math::python_sum_f64(&ideal);
    if ideal == 0. {
        0.
    } else {
        ken_retrieval::vector_math::python_sum_f64(&gains) / ideal
    }
}
fn rr(paths: &[PythonText], expected: &BTreeSet<String>) -> f64 {
    paths
        .iter()
        .position(|path| path.to_utf8().is_some_and(|path| expected.contains(&path)))
        .map(|index| 1. / (index + 1) as f64)
        .unwrap_or(0.)
}
pub fn benchmark(
    conn: &Connection,
    root: &Path,
    dataset: &BenchDataset,
    options: &BenchOptions,
    runner: &mut dyn BenchRunner,
) -> Result<BenchReport> {
    if options.top == 0
        || dataset.cases.is_empty()
        || [
            options.fail_under_case_recall,
            options.fail_under_expected_file_recall,
        ]
        .into_iter()
        .flatten()
        .any(|threshold| !threshold.is_finite() || !(0.0..=1.0).contains(&threshold))
    {
        return Err(Error::Invalid(
            "positive top, nonempty dataset and finite recall thresholds0..1 required".into(),
        ));
    }
    if options.verify_index {
        verify_index(conn, root)?;
    }
    let (
        mut hit_cases,
        mut visible_hit_cases,
        mut found,
        mut visible_found,
        mut expected_total,
        mut chars_total,
        mut tokens_total,
    ) = (0usize, 0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    let (mut reciprocal, mut visible_reciprocal, mut ndcg_total) = (0., 0., 0.);
    let mut timings = BTreeMap::from([
        ("embed".to_owned(), 0.),
        ("rank".into(), 0.),
        ("render".into(), 0.),
        ("e2e".into(), 0.),
    ]);
    let mut results = Vec::new();
    for (index, case) in dataset.cases.iter().enumerate() {
        let mut observed = runner.evaluate(&case.prompt, options.top, options.max_chars)?;
        observed.ranked.truncate(options.top);
        if observed.ranked.iter().any(|row| !row.score.is_finite())
            || observed
                .timings_ms
                .values()
                .any(|time| !time.is_finite() || *time < 0.)
        {
            return Err(Error::Invalid(
                "benchmark observations require finite scores and nonnegative timings".into(),
            ));
        }
        let ranked = observed
            .ranked
            .iter()
            .map(|row| row.target.clone())
            .collect::<Vec<_>>();
        let expected = case.expected_files.iter().cloned().collect::<BTreeSet<_>>();
        let ranked_set = ranked
            .iter()
            .filter_map(PythonText::to_utf8)
            .collect::<BTreeSet<_>>();
        let visible_set = observed
            .visible_files
            .iter()
            .filter_map(PythonText::to_utf8)
            .collect::<BTreeSet<_>>();
        let hits = expected
            .intersection(&ranked_set)
            .cloned()
            .collect::<Vec<_>>();
        let visible_hits = expected
            .intersection(&visible_set)
            .cloned()
            .collect::<Vec<_>>();
        let reciprocal_rank = rr(&ranked, &expected);
        let visible_rr = rr(&observed.visible_files, &expected);
        let ndcg = ndcg(&ranked, &case.judgments, options.top);
        let chars = observed.block.codepoints().len();
        let tokens = chars.saturating_add(3) / 4;
        hit_cases += usize::from(!hits.is_empty());
        visible_hit_cases += usize::from(!visible_hits.is_empty());
        found += hits.len();
        visible_found += visible_hits.len();
        expected_total += expected.len();
        chars_total += chars;
        tokens_total += tokens;
        reciprocal += reciprocal_rank;
        visible_reciprocal += visible_rr;
        ndcg_total += ndcg;
        for (phase, total) in &mut timings {
            *total += observed.timings_ms.get(phase).copied().unwrap_or(0.);
        }
        let misses = options
            .explain_misses
            .then(|| expected.difference(&ranked_set).cloned().collect());
        results.push(BenchCaseResult {
            case: index + 1,
            prompt: case.prompt.clone(),
            expected_files: expected.into_iter().collect(),
            judgments: case.judgments.clone(),
            ranked_files: ranked,
            visible_files: observed.visible_files,
            visible_hits,
            visible_reciprocal_rank: visible_rr,
            ranked_details: observed
                .ranked
                .into_iter()
                .map(|item| RankedDetail {
                    path: item.target,
                    score: item.score,
                    reason: item.reason,
                })
                .collect(),
            hits: hits.clone(),
            hit: !hits.is_empty(),
            reciprocal_rank,
            ndcg,
            context_chars: chars,
            context_est_tokens: tokens,
            timings_ms: observed.timings_ms,
            misses,
        });
    }
    let count = results.len() as f64;
    for total in timings.values_mut() {
        *total /= count;
    }
    let mut report = BenchReport {
        ok: true,
        cases: results.len(),
        top: options.top,
        case_recall: crate::round(hit_cases as f64 / count, 4),
        expected_file_recall: crate::round(found as f64 / expected_total as f64, 4),
        mrr: reciprocal / count,
        visible_case_recall: crate::round(visible_hit_cases as f64 / count, 4),
        visible_expected_file_recall: crate::round(visible_found as f64 / expected_total as f64, 4),
        visible_mrr: visible_reciprocal / count,
        ndcg: ndcg_total / count,
        avg_context_chars: crate::round(chars_total as f64 / count, 1),
        avg_context_est_tokens: crate::round(tokens_total as f64 / count, 1),
        avg_timings_ms: timings,
        results,
        failures: Vec::new(),
    };
    if let Some(threshold) = options
        .fail_under_case_recall
        .filter(|threshold| report.case_recall < *threshold)
    {
        report.failures.push(format!(
            "case_recall {:.4} < {threshold:.4}",
            report.case_recall
        ));
    }
    if let Some(threshold) = options
        .fail_under_expected_file_recall
        .filter(|threshold| report.expected_file_recall < *threshold)
    {
        report.failures.push(format!(
            "expected_file_recall {:.4} < {threshold:.4}",
            report.expected_file_recall
        ));
    }
    report.ok = report.failures.is_empty();
    Ok(report)
}
