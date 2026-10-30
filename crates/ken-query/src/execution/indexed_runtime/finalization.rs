//! Stable ordering polls between bounded pieces of work and moves rows only once.
use super::super::Result;
use std::cmp::Ordering;
pub(super) fn stable_sort(
    indices: &mut Vec<usize>,
    compare: &mut dyn FnMut(usize, usize) -> Ordering,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    check()?;
    let n = indices.len();
    if n < 2 {
        return Ok(());
    }
    let mut scratch = Vec::with_capacity(n);
    for i in 0..n {
        if i % 256 == 0 {
            check()?;
        }
        scratch.push(0);
    }
    let mut width = 1;
    let mut work = 0usize;
    while width < n {
        let mut begin = 0;
        while begin < n {
            let middle = begin.saturating_add(width).min(n);
            let end = middle.saturating_add(width).min(n);
            let (mut left, mut right, mut at) = (begin, middle, begin);
            while left < middle && right < end {
                poll(&mut work, check)?;
                if compare(indices[left], indices[right]) != Ordering::Greater {
                    scratch[at] = indices[left];
                    left += 1;
                } else {
                    scratch[at] = indices[right];
                    right += 1;
                }
                at += 1;
            }
            while left < middle {
                poll(&mut work, check)?;
                scratch[at] = indices[left];
                left += 1;
                at += 1;
            }
            while right < end {
                poll(&mut work, check)?;
                scratch[at] = indices[right];
                right += 1;
                at += 1;
            }
            begin = end;
        }
        std::mem::swap(indices, &mut scratch);
        check()?;
        width = width.saturating_mul(2);
    }
    check()
}
fn poll(work: &mut usize, check: &mut dyn FnMut() -> Result<()>) -> Result<()> {
    *work = work.wrapping_add(1);
    if work.is_multiple_of(256) {
        check()?;
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn checked_sort_preserves_stability_and_stops_during_ordering() {
        let values = (0..10_001).map(|i| (i * 73 + 19) % 17).collect::<Vec<_>>();
        let mut expected = (0..values.len()).collect::<Vec<_>>();
        expected.sort_by_key(|&i| values[i]);
        let mut indices = (0..values.len()).collect::<Vec<_>>();
        stable_sort(
            &mut indices,
            &mut |a, b| values[a].cmp(&values[b]),
            &mut || Ok(()),
        )
        .unwrap();
        assert_eq!(indices, expected);
        let mut indices = (0..values.len()).collect::<Vec<_>>();
        let (mut polls, mut comparisons) = (0, 0);
        let result = stable_sort(
            &mut indices,
            &mut |a, b| {
                comparisons += 1;
                values[a].cmp(&values[b])
            },
            &mut || {
                polls += 1;
                if polls >= 45 {
                    Err(super::super::super::ExecutionError::Exhausted(
                        "finalization_test",
                    ))
                } else {
                    Ok(())
                }
            },
        );
        assert!(matches!(
            result,
            Err(super::super::super::ExecutionError::Exhausted(
                "finalization_test"
            ))
        ));
        assert!(comparisons > 0 && comparisons < values.len());
    }
}
