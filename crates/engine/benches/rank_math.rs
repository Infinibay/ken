//! Micro-benchmarks for the ranker's pure-CPU math: cosine, MAD, normal_inv_cdf,
//! channel merge. These are inside `Ranker::rank()`'s hot path so even a
//! 2x regression here is measurable end-to-end.
//!
//! Run with:  cargo bench --bench rank_math -p ken-engine

use criterion::{black_box, criterion_group, criterion_main, BatchSize, Criterion, Throughput};
use engine::rank::merge::{apply_confidence_and_mad, max_merge, ChannelHit, MergeConfig};
use engine::rank::stats::{cosine, mad, median, normal_inv_cdf};
use engine::types::{ChunkId, NodeRef};

fn random_unit_vector(seed: u64, dim: usize) -> Vec<f32> {
    // Deterministic LCG so benches are reproducible without bringing rand in.
    let mut state = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    let mut v: Vec<f32> = (0..dim)
        .map(|_| {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as i32 as f32) / i32::MAX as f32
        })
        .collect();
    let n = v.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-9);
    for x in &mut v {
        *x /= n;
    }
    v
}

fn bench_cosine(c: &mut Criterion) {
    let mut group = c.benchmark_group("cosine");
    for &dim in &[64usize, 384, 768, 1536] {
        let a = random_unit_vector(1, dim);
        let b = random_unit_vector(2, dim);
        group.throughput(Throughput::Elements(1));
        group.bench_function(format!("dim={dim}"), |bencher| {
            bencher.iter(|| cosine(black_box(&a), black_box(&b)));
        });
    }
    group.finish();
}

fn bench_mad_and_median(c: &mut Criterion) {
    let mut group = c.benchmark_group("mad");
    for &n in &[16usize, 64, 256, 1024] {
        let values: Vec<f32> = (0..n).map(|i| ((i * 7 + 3) % 97) as f32 / 13.0).collect();
        group.throughput(Throughput::Elements(n as u64));
        group.bench_function(format!("n={n}/median"), |bencher| {
            bencher.iter(|| median(black_box(&values)));
        });
        group.bench_function(format!("n={n}/mad"), |bencher| {
            bencher.iter(|| mad(black_box(&values)));
        });
    }
    group.finish();
}

fn bench_normal_inv_cdf(c: &mut Criterion) {
    c.bench_function("normal_inv_cdf", |bencher| {
        bencher.iter(|| {
            let mut acc = 0.0f64;
            for i in 1..100 {
                let p = i as f64 / 100.0;
                acc += normal_inv_cdf(black_box(p)).unwrap_or(0.0);
            }
            acc
        });
    });
}

fn bench_channel_merge(c: &mut Criterion) {
    fn make_channel(seed: u64, n: usize) -> Vec<ChannelHit> {
        (0..n)
            .map(|i| ChannelHit {
                target: NodeRef::Chunk(ChunkId((seed * 991 + i as u64) % 2048)),
                score: ((seed.wrapping_mul(13) + i as u64) % 1000) as f32 / 1000.0,
                reason: "synthetic".to_string(),
            })
            .collect()
    }
    let mut group = c.benchmark_group("merge");
    for &n in &[20usize, 100, 500] {
        let channels = vec![
            make_channel(1, n),
            make_channel(2, n),
            make_channel(3, n),
            make_channel(4, n),
        ];
        group.throughput(Throughput::Elements((n * 4) as u64));
        group.bench_function(format!("max_merge_{n}x4"), |bencher| {
            bencher.iter_batched(
                || channels.clone(),
                |chans| max_merge(black_box(chans)),
                BatchSize::SmallInput,
            );
        });
    }
    group.finish();
}

fn bench_confidence_and_mad(c: &mut Criterion) {
    let merged: Vec<ChannelHit> = (0..200u64)
        .map(|i| ChannelHit {
            target: NodeRef::Chunk(ChunkId(i)),
            score: 0.3 + ((i * 17) % 100) as f32 / 200.0,
            reason: "synthetic".to_string(),
        })
        .collect();
    let cfg = MergeConfig::default();
    c.bench_function("apply_confidence_and_mad/n=200", |bencher| {
        bencher.iter_batched(
            || merged.clone(),
            |hits| apply_confidence_and_mad(black_box(hits), &cfg),
            BatchSize::SmallInput,
        );
    });
}

criterion_group!(
    benches,
    bench_cosine,
    bench_mad_and_median,
    bench_normal_inv_cdf,
    bench_channel_merge,
    bench_confidence_and_mad,
);
criterion_main!(benches);
