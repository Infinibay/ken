//! Intel AVX2's four-vector partition schedule, including reversed high lanes.
//! Adapted from x86-simd-sort5adb334; see LICENSE.intel.txt (BSD-3-Clause).
fn load(indices: &[usize], begin: usize) -> [usize; 4] {
    indices[begin..begin + 4]
        .try_into()
        .expect("complete four-lane block")
}
struct Partition<'a> {
    values: &'a [f32],
    indices: &'a mut [usize],
    pivot: f32,
    smallest: f32,
    biggest: f32,
}
impl Partition<'_> {
    fn observe(&mut self, index: usize) {
        let value = self.values[index];
        if value < self.smallest {
            self.smallest = value;
        }
        if self.biggest < value {
            self.biggest = value;
        }
    }
    fn vector(&mut self, lanes: [usize; 4], left: usize, right: usize) -> usize {
        let mut packed = [0usize; 4];
        let mut low = 0;
        let mut high = 4;
        for index in lanes {
            self.observe(index);
            if self.values[index] >= self.pivot {
                high -= 1;
                packed[high] = index;
            } else {
                packed[low] = index;
                low += 1;
            }
        }
        // AVX2 double_compressstore writes the complete permuted vector to both
        // frontiers. The loading schedule protects every not-yet-consumed element.
        self.indices[left..left + 4].copy_from_slice(&packed);
        self.indices[right - 4..right].copy_from_slice(&packed);
        4 - low
    }
}
pub(super) fn partition(
    values: &[f32],
    indices: &mut [usize],
    mut left: usize,
    mut right: usize,
    pivot: f32,
) -> (usize, f32, f32) {
    debug_assert!(right - left > 256);
    let mut state = Partition {
        values,
        indices,
        pivot,
        smallest: f32::INFINITY,
        biggest: f32::NEG_INFINITY,
    };
    for _ in 0..(right - left) % 16 {
        let index = state.indices[left];
        state.observe(index);
        if state.values[index] >= pivot {
            right -= 1;
            state.indices.swap(left, right);
        } else {
            left += 1;
        }
    }
    let first: [[_; 4]; 4] = std::array::from_fn(|i| load(state.indices, left + 4 * i));
    let last: [[_; 4]; 4] = std::array::from_fn(|i| load(state.indices, right - 16 + 4 * i));
    let mut l_store = left;
    let mut r_store = right - 4;
    left += 16;
    right -= 16;
    while right != left {
        let lanes: [[_; 4]; 4];
        if (r_store + 4) - right < left - l_store {
            right -= 16;
            lanes = std::array::from_fn(|i| load(state.indices, right + 4 * i));
        } else {
            lanes = std::array::from_fn(|i| load(state.indices, left + 4 * i));
            left += 16;
        }
        for vector in lanes {
            let high = state.vector(vector, l_store, r_store + 4);
            l_store += 4 - high;
            r_store = r_store.wrapping_sub(high);
        }
    }
    for vector in first.into_iter().chain(last) {
        let high = state.vector(vector, l_store, r_store + 4);
        l_store += 4 - high;
        r_store = r_store.wrapping_sub(high);
    }
    (l_store, state.smallest, state.biggest)
}
