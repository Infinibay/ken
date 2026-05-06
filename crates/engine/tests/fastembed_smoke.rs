//! Smoke test for the production embedder (`all-MiniLM-L6-v2` quantized
//! via fastembed-rs).
//!
//! The test downloads the model on first run (~25 MB → fastembed cache);
//! subsequent runs are cache-hot. Gated `#[ignore]` because:
//!   * needs network on first run,
//!   * loads ONNX runtime + ~80 MB resident,
//!   * adds seconds to test latency.
//!
//! Run explicitly:
//!
//!     cargo test -p ken-engine --features fastembed -- --ignored fastembed
//!
//! Verifies:
//!   * model loads and reports the expected 384 dimensions,
//!   * embeddings are L2-normalized,
//!   * a relevant query lands closer to a relevant passage than to an
//!     unrelated one (sanity, not calibration).

#![cfg(feature = "fastembed")]

use engine::embed::{cosine, Embedder};
use engine::embed_fast::{FastEmbedder, EMBED_DIM};

fn norm(v: &[f32]) -> f32 {
    v.iter().map(|x| x * x).sum::<f32>().sqrt()
}

#[test]
#[ignore]
fn fastembed_loads_and_produces_normalized_384_dim_vectors() {
    let e = FastEmbedder::mini_q().expect("init");
    assert_eq!(e.dim(), EMBED_DIM);

    let q = e.embed_query("how does authentication work in this codebase");
    assert_eq!(q.len(), EMBED_DIM);
    assert!((norm(&q) - 1.0).abs() < 1e-3, "query not normalized: {}", norm(&q));

    let passages = e.embed_passages(&[
        "JWT tokens are issued at login and rotated every 30 minutes.",
        "The mascot is a small orange cat named Pumpkin.",
    ]);
    assert_eq!(passages.len(), 2);
    assert_eq!(passages[0].len(), EMBED_DIM);
    assert!((norm(&passages[0]) - 1.0).abs() < 1e-3);
    assert!((norm(&passages[1]) - 1.0).abs() < 1e-3);
}

#[test]
#[ignore]
fn fastembed_is_symmetric_for_same_text() {
    // mini-q is symmetric — query and passage encodings should agree
    // (or at least be effectively identical) for the same input.
    let e = FastEmbedder::mini_q().expect("init");
    let text = "rate limiting per user via sliding window";
    let q = e.embed_query(text);
    let p = e.embed_passage(text);
    let sim = cosine(&q, &p);
    assert!(sim > 0.999, "expected symmetry, got cosine={sim}");
}

#[test]
#[ignore]
fn fastembed_relevant_passage_beats_irrelevant() {
    let e = FastEmbedder::mini_q().expect("init");
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
