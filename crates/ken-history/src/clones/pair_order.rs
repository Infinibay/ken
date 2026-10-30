//! Ordering of the clone policy's integer-ID pairs on its qualified x86_64
//! reference. Full score/file ties retain this order before result limiting.
//! Restricted to insertion and iteration; no Python runtime or general values.
//! Verified against CPython 3.12.9 Objects/{longobject,tupleobject,setobject}.c:
//! https://github.com/python/cpython/tree/v3.12.9/Objects
#[derive(Clone, Copy)]
struct Pair {
    left: i64,
    right: i64,
    hash: u64,
}
pub(super) struct PairOrder {
    slots: Vec<Option<Pair>>,
    used: usize,
}
impl PairOrder {
    pub(super) fn new() -> Self {
        Self {
            slots: vec![None; 8],
            used: 0,
        }
    }
    pub(super) fn insert(&mut self, left: i64, right: i64) {
        let (left, right) = if left < right {
            (left, right)
        } else {
            (right, left)
        };
        let pair = Pair {
            left,
            right,
            hash: pair_hash(left, right),
        };
        let position = locate(&self.slots, pair);
        if self.slots[position].is_some() {
            return;
        }
        self.slots[position] = Some(pair);
        self.used += 1;
        if self.used * 5 < (self.slots.len() - 1) * 3 {
            return;
        }
        let minimum = self.used * if self.used > 50_000 { 2 } else { 4 };
        let mut size = 8;
        while size <= minimum {
            size *= 2;
        }
        let previous = std::mem::replace(&mut self.slots, vec![None; size]);
        // Rehash in old slot order, exactly as the original no-deletion table.
        for pair in previous.into_iter().flatten() {
            let position = locate(&self.slots, pair);
            self.slots[position] = Some(pair);
        }
    }
    pub(super) fn pairs(self) -> impl Iterator<Item = (i64, i64)> {
        self.slots
            .into_iter()
            .flatten()
            .map(|pair| (pair.left, pair.right))
    }
}
fn locate(slots: &[Option<Pair>], pair: Pair) -> usize {
    let mask = slots.len() - 1;
    let mut index = pair.hash as usize & mask;
    let mut perturb = pair.hash;
    loop {
        let probes = if index + 9 <= mask { 9 } else { 0 };
        for offset in 0..=probes {
            match slots[index + offset] {
                None => return index + offset,
                Some(old)
                    if old.hash == pair.hash
                        && old.left == pair.left
                        && old.right == pair.right =>
                {
                    return index + offset;
                }
                _ => {}
            }
        }
        perturb >>= 5;
        index = (index
            .wrapping_mul(5)
            .wrapping_add(1)
            .wrapping_add(perturb as usize))
            & mask;
    }
}
fn integer_hash(value: i64) -> u64 {
    let magnitude = (value.unsigned_abs() % ((1u64 << 61) - 1)) as i64;
    let hash = if value < 0 { -magnitude } else { magnitude };
    (if hash == -1 { -2 } else { hash }) as u64
}
fn pair_hash(left: i64, right: i64) -> u64 {
    const P1: u64 = 11_400_714_785_074_694_791;
    const P2: u64 = 14_029_467_366_897_019_727;
    const P5: u64 = 2_870_177_450_012_600_261;
    let mut accumulator = P5;
    for value in [left, right] {
        accumulator = accumulator.wrapping_add(integer_hash(value).wrapping_mul(P2));
        accumulator = accumulator.rotate_left(31).wrapping_mul(P1);
    }
    accumulator = accumulator.wrapping_add(2 ^ (P5 ^ 3_527_539));
    if accumulator == u64::MAX {
        1_546_275_796
    } else {
        accumulator
    }
}
