//! Preserve NumPy 2.4.4 ARM64 integer argsort ties used by Sentence Transformers.
//! Compatibility algorithm: median-of-three introsort, insertion cutoff, heap fallback.
//! Upstream references: numpy/_core/src/npysort/{quicksort.cpp,npysort_heapsort.h}.
//! NumPy BSD-3-Clause notice is retained in licenses/numpy-sort-LICENSE.txt.

pub(crate) fn sentence_indices(lengths: &[usize]) -> Vec<usize> {
    let mut order: Vec<_> = (0..lengths.len()).collect();
    if order.len() < 2 {
        return order;
    }
    let mut pending = vec![(0, order.len() - 1, 2 * order.len().ilog2() as i32)];
    while let Some((mut begin, mut end, mut depth)) = pending.pop() {
        if depth < 0 {
            heap_indices(&mut order[begin..=end], lengths);
            continue;
        }
        while end - begin > 15 {
            let middle = begin + (end - begin) / 2;
            if lengths[order[middle]] > lengths[order[begin]] {
                order.swap(middle, begin);
            }
            if lengths[order[end]] > lengths[order[middle]] {
                order.swap(end, middle);
            }
            if lengths[order[middle]] > lengths[order[begin]] {
                order.swap(middle, begin);
            }
            let pivot = lengths[order[middle]];
            let mut left = begin;
            let mut right = end - 1;
            order.swap(middle, right);
            loop {
                left += 1;
                while lengths[order[left]] > pivot {
                    left += 1;
                }
                right -= 1;
                while pivot > lengths[order[right]] {
                    right -= 1;
                }
                if left >= right {
                    break;
                }
                order.swap(left, right);
            }
            order.swap(left, end - 1);
            depth -= 1;
            if left - begin < end - left {
                pending.push((left + 1, end, depth));
                end = left - 1;
            } else {
                pending.push((begin, left - 1, depth));
                begin = left + 1;
            }
        }
        for index in begin + 1..=end {
            let value = order[index];
            let mut at = index;
            while at > begin && lengths[value] > lengths[order[at - 1]] {
                order[at] = order[at - 1];
                at -= 1;
            }
            order[at] = value;
        }
    }
    order
}

fn heap_indices(order: &mut [usize], lengths: &[usize]) {
    for start in (0..order.len() / 2).rev() {
        sift(order, lengths, start, order.len(), order[start]);
    }
    for end in (1..order.len()).rev() {
        let value = order[end];
        order[end] = order[0];
        sift(order, lengths, 0, end, value);
    }
}
fn sift(order: &mut [usize], lengths: &[usize], mut at: usize, limit: usize, value: usize) {
    loop {
        let mut child = 2 * at + 1;
        if child >= limit {
            break;
        }
        if child + 1 < limit && lengths[order[child]] > lengths[order[child + 1]] {
            child += 1;
        }
        if lengths[value] <= lengths[order[child]] {
            break;
        }
        order[at] = order[child];
        at = child;
    }
    order[at] = value;
}

#[cfg(test)]
mod tests {
    use super::sentence_indices;
    use serde::Deserialize;
    #[derive(Deserialize)]
    struct Case {
        name: String,
        lengths: Vec<usize>,
        indices: Vec<usize>,
    }
    #[test]
    fn sentence_order_matches_original_numpy_including_equal_keys_and_depth_fallback() {
        let cases: Vec<Case> = serde_json::from_str(include_str!(
            "../tests/fixtures/transformer-order/numpy-2.4.4.json"
        ))
        .unwrap();
        for case in cases {
            assert_eq!(
                sentence_indices(&case.lengths),
                case.indices,
                "{}",
                case.name
            );
        }
    }
}
