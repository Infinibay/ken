//! Smoke test for the production embedder (`nomic-embed-text-v1.5` via
//! fastembed-rs).
//!
//! The test downloads the model on first run (~135 MB → fastembed cache);
//! subsequent runs are cache-hot. Gated `#[ignore]` because:
//!   * needs network on first run,
//!   * loads ONNX runtime + ~280 MB resident,
//!   * adds seconds to test latency.
//!
//! Run explicitly:
//!
//!     cargo test -p cae-engine --features fastembed -- --ignored fastembed
//!
//! Verifies:
//!   * model loads and reports the expected 768 dimensions,
//!   * embeddings are L2-normalized,
//!   * passage embedding ≠ query embedding for the same text (asymmetry),
//!   * a relevant query lands closer to a relevant passage than to an
//!     unrelated one (sanity, not calibration).

#![cfg(feature = "fastembed")]

use engine::embed::{cosine, Embedder};
use engine::embed_fast::{FastEmbedder, NOMIC_V15_DIM};

fn norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

#[test]
#[ignore]
fn fastembed_loads_and_produces_normalized_768_dim_vectors() {
    let e = FastEmbedder::nomic_v15().expect("init");
    assert_eq!(e.dim(), NOMIC_V15_DIM);

    let q = e.embed_query("how does authentication work in this codebase");
    assert_eq!(q.len(), NOMIC_V15_DIM);
    assert!((norm(&q) - 1.0).abs() < 1e-3, "query not normalized: {}", norm(&q));

    let passages = e.embed_passages(&[
        "JWT tokens are issued at login and rotated every 30 minutes.",
        "The mascot is a small orange cat named Pumpkin.",
    ]);
    assert_eq!(passages.len(), 2);
    assert_eq!(passages[0].len(), NOMIC_V15_DIM);
    assert!((norm(&passages[0]) - 1.0).abs() < 1e-3);
    assert!((norm(&passages[1]) - 1.0).abs() < 1e-3);
}

#[test]
#[ignore]
fn fastembed_is_asymmetric_for_same_text() {
    // Asymmetric models produce different vectors for query vs passage of
    // the same text — this is the whole point of search_query / search_document.
    let e = FastEmbedder::nomic_v15().expect("init");
    let text = "rate limiting per user via sliding window";
    let q = e.embed_query(text);
    let p = e.embed_passage(text);
    let sim = cosine(&q, &p);
    assert!(sim < 0.999, "expected asymmetry, got cosine={sim}");
    assert!(sim > 0.7, "query and passage should still be similar, got cosine={sim}");
}

#[test]
#[ignore]
fn fastembed_relevant_passage_beats_irrelevant() {
    let e = FastEmbedder::nomic_v15().expect("init");
    let q = e.embed_query("how is login authentication implemented");
    let p_relevant = e.embed_passage(
        "Authentication uses JWT tokens issued at login and validated on every request.",
    );
    let p_unrelated = e.embed_passage(
        "Our team's office mascot is an orange cat that loves pumpkins and tuna.",
    );
    let sim_rel = cosine(&q, &p_relevant);
    let sim_unrel = cosine(&q, &p_unrelated);
    assert!(
        sim_rel > sim_unrel + 0.05,
        "expected relevant > irrelevant by ≥0.05; relevant={sim_rel}, unrelated={sim_unrel}",
    );
}
