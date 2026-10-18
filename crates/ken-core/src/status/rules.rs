//! Status policy and formatting shared by JSON and text presentation.
use super::{EmbeddingCoverage, IndexHealth, RankSignals, StatusCounts};

pub fn format_size(bytes: Option<u64>) -> String {
    let Some(bytes) = bytes else {
        return "missing".into();
    };
    let mut size = bytes as f64;
    for unit in ["B", "KiB", "MiB", "GiB"] {
        if size < 1024.0 {
            return format!("{size:.0}{unit}");
        }
        size /= 1024.0;
    }
    format!("{size:.0}TiB")
}
pub fn embedding_coverage(c: &StatusCounts) -> EmbeddingCoverage {
    let embedded = c.files_embedded + c.symbols_embedded;
    let total = c.files + c.symbols;
    let percent = if total == 0 {
        0.0
    } else {
        embedded as f64 / total as f64 * 100.0
    };
    // Decimal formatting rounds the original binary value with ties to even,
    // including 1.25 -> 1.2. Scaling then round() changes Python's semantics.
    let percent = format!("{percent:.1}").parse().expect("finite percentage");
    EmbeddingCoverage {
        embedded,
        total,
        percent,
    }
}
pub fn rank_signals(c: &StatusCounts) -> RankSignals {
    let embedded = c.files_embedded + c.symbols_embedded;
    let total = c.files + c.symbols;
    RankSignals {
        index: if c.files == 0 { "empty" } else { "yes" }.into(),
        embeddings: if embedded == 0 {
            "none".into()
        } else if embedded == total {
            "ready".into()
        } else {
            format!("partial({embedded}/{total})")
        },
        predictive: if c.session_scores > 0 && c.prompt_contexts_embedded > 0 {
            "yes"
        } else {
            "no"
        }
        .into(),
        findings: if c.findings_embedded > 0 { "yes" } else { "no" }.into(),
    }
}
pub fn recommendations(c: &StatusCounts, h: &IndexHealth) -> Vec<String> {
    let mut recs = Vec::new();
    let embedded = c.files_embedded + c.symbols_embedded;
    let total = c.files + c.symbols;
    if c.files == 0 {
        recs.push("run `ken install .` or re-run it to populate the code index");
    } else if h.stale_files > 0 {
        recs.push(
            "indexed files are missing on disk; run `ken install .` to resync after branch changes",
        );
    }
    if c.files > 0 && embedded == 0 {
        recs.push("run `ken rank \"your task\"` once to lazily build embeddings");
    } else if c.files > 0 && embedded < total {
        recs.push("embeddings are partial; use `ken install . --embed --embed-limit N` to warm more of the project when semantic recall matters");
    }
    if c.prompt_contexts_embedded == 0 {
        recs.push("submit at least one prompt through a hooked agent to seed context history");
    } else if c.interactions == 0 {
        recs.push(
            "verify tool hooks are recording reads/edits; no interactions have been captured",
        );
    }
    if c.session_scores == 0 {
        recs.push(if c.active_sessions > 0 {
            "end the active session to snapshot predictive scores"
        } else {
            "let hooks run through a few real turns to build predictive history"
        });
    }
    if c.findings_embedded == 0 {
        recs.push("save reusable project facts with `ken remember TOPIC CONTENT`");
    }
    recs.into_iter().map(String::from).collect()
}
