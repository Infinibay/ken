//! A count is certain only when its predicate holds over every feasible size.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Decision {
    Satisfied,
    Rejected,
    Unknown,
}
pub(super) struct Cardinality {
    pub certain: usize,
    pub possible: Option<usize>,
}
impl Cardinality {
    pub fn compare(&self, operation: &str, target: f64) -> Decision {
        use Decision::*;
        let low = self.certain as f64;
        let high = self.possible.map(|n| n as f64);
        match operation {
            "=" => {
                if high == Some(low) && low == target {
                    Satisfied
                } else if low > target || high.is_some_and(|h| h < target) {
                    Rejected
                } else {
                    Unknown
                }
            }
            "!=" => match self.compare("=", target) {
                Satisfied => Rejected,
                Rejected => Satisfied,
                Unknown => Unknown,
            },
            "<" => {
                if low >= target {
                    Rejected
                } else if high.is_some_and(|h| h < target) {
                    Satisfied
                } else {
                    Unknown
                }
            }
            "<=" => {
                if low > target {
                    Rejected
                } else if high.is_some_and(|h| h <= target) {
                    Satisfied
                } else {
                    Unknown
                }
            }
            ">" => {
                if low > target {
                    Satisfied
                } else if high.is_some_and(|h| h <= target) {
                    Rejected
                } else {
                    Unknown
                }
            }
            ">=" => {
                if low >= target {
                    Satisfied
                } else if high.is_some_and(|h| h < target) {
                    Rejected
                } else {
                    Unknown
                }
            }
            _ => unreachable!("validated numeric count comparison"),
        }
    }
}
