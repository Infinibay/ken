//! Four-lane AVX2 key/index network semantics, preserving Intel's tie moves.
//! Adapted from x86-simd-sort5adb334; see LICENSE.intel.txt (BSD-3-Clause).
#[derive(Clone, Copy)]
struct Entry {
    key: f32,
    index: usize,
}
type Lanes = [Entry; 4];
fn min(a: f32, b: f32) -> f32 {
    if a < b { a } else { b }
}
fn max(a: f32, b: f32) -> f32 {
    if a > b { a } else { b }
}
fn shuffle(input: Lanes, map: [usize; 4]) -> Lanes {
    map.map(|i| input[i])
}
fn compare_merge(input: Lanes, other: Lanes, mask: u8) -> Lanes {
    std::array::from_fn(|i| {
        let key = if mask & (1 << i) == 0 {
            min(other[i].key, input[i].key)
        } else {
            max(other[i].key, input[i].key)
        };
        Entry {
            key,
            index: if key == input[i].key {
                input[i].index
            } else {
                other[i].index
            },
        }
    })
}
fn sort_lanes(mut lanes: Lanes) -> Lanes {
    lanes = compare_merge(lanes, shuffle(lanes, [1, 0, 3, 2]), 0xa);
    lanes = compare_merge(lanes, shuffle(lanes, [3, 2, 1, 0]), 0xc);
    compare_merge(lanes, shuffle(lanes, [1, 0, 3, 2]), 0xa)
}
fn merge_lanes(mut lanes: Lanes) -> Lanes {
    lanes = compare_merge(lanes, shuffle(lanes, [2, 3, 0, 1]), 0xc);
    compare_merge(lanes, shuffle(lanes, [1, 0, 3, 2]), 0xa)
}
fn compare_vectors(vectors: &mut [Lanes], a: usize, b: usize) {
    let first = vectors[a];
    let second = vectors[b];
    for lane in 0..4 {
        let low = min(first[lane].key, second[lane].key);
        let high = max(first[lane].key, second[lane].key);
        let same = low == first[lane].key;
        vectors[a][lane] = Entry {
            key: low,
            index: if same {
                first[lane].index
            } else {
                second[lane].index
            },
        };
        vectors[b][lane] = Entry {
            key: high,
            index: if same {
                second[lane].index
            } else {
                first[lane].index
            },
        };
    }
}
fn merge_vectors(vectors: &mut [Lanes]) {
    let count = vectors.len();
    for i in 0..count / 2 {
        let last = count - i - 1;
        vectors[last].reverse();
        compare_vectors(vectors, i, last);
        vectors[last].reverse();
    }
    let mut group = count / 2;
    while group >= 2 {
        for begin in (0..count).step_by(group) {
            for i in 0..group / 2 {
                compare_vectors(vectors, begin + i, begin + i + group / 2);
            }
        }
        group /= 2;
    }
    for vector in vectors {
        *vector = merge_lanes(*vector);
    }
}
pub(super) fn sort(values: &[f32], indices: &mut [usize]) {
    if indices.is_empty() {
        return;
    }
    let count = indices.len().div_ceil(4).next_power_of_two();
    let padding = Entry {
        key: f32::INFINITY,
        index: usize::MAX,
    };
    let mut vectors = vec![[padding; 4]; count];
    for (i, index) in indices.iter().copied().enumerate() {
        vectors[i / 4][i % 4] = Entry {
            key: values[index],
            index,
        };
    }
    for vector in &mut vectors {
        *vector = sort_lanes(*vector);
    }
    let mut group = 2;
    while group <= count {
        for chunk in vectors.chunks_exact_mut(group) {
            merge_vectors(chunk);
        }
        group *= 2;
    }
    for (index, entry) in indices.iter_mut().zip(vectors.iter().flatten()) {
        *index = entry.index;
    }
}
pub(super) fn median(values: &[f32], indices: &[usize], begin: usize, end: usize) -> f32 {
    let step = (end - begin - 1) / 4;
    let lanes = std::array::from_fn(|i| {
        let index = indices[begin + (4 - i) * step];
        Entry {
            key: values[index],
            index,
        }
    });
    sort_lanes(lanes)[2].key
}
