//! Frozen scalar reductions shared by feature and evidence policies.
/// NumPy contiguous F64 sum; multi-column row accumulation is sequential.
pub(crate) fn pairwise64(values: &[f64]) -> f64 {
    let n = values.len();
    if n < 8 {
        return values.iter().fold(-0., |a, v| a + v);
    }
    if n > 128 {
        let middle = (n / 2) / 8 * 8;
        return pairwise64(&values[..middle]) + pairwise64(&values[middle..]);
    }
    let mut lanes: [f64; 8] = values[..8].try_into().expect("complete eight-value block");
    let boundary = n / 8 * 8;
    for chunk in values[8..boundary].chunks_exact(8) {
        for (sum, v) in lanes.iter_mut().zip(chunk) {
            *sum += v;
        }
    }
    let sum = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[3]))
        + ((lanes[4] + lanes[5]) + (lanes[6] + lanes[7]));
    values[boundary..].iter().fold(sum, |sum, v| sum + v)
}

/// Python3.12 float sum preserves a small residual between cancelling priors.
/// Keep this separate from NumPy pairwise reduction and ordered tree addition.
/// See CPython v3.12.9 Python/bltinmodule.c, builtin_sum_impl.
pub(crate) fn python_sum(values: impl Iterator<Item = f64>) -> f64 {
    let mut total = 0_f64;
    let mut correction = 0_f64;
    for value in values {
        let next = total + value;
        correction += if total.abs() >= value.abs() {
            (total - next) + value
        } else {
            (value - next) + total
        };
        total = next;
    }
    if correction != 0. && correction.is_finite() {
        total += correction;
    }
    total
}
