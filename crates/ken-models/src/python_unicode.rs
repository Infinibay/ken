//! Fixed original Python Unicode15 behavior, independent of the Rust toolchain's tables.
use serde::Deserialize;
use std::{cmp::Ordering, sync::OnceLock};

#[derive(Deserialize)]
struct Tables {
    word: Vec<[u32; 2]>,
    decimal: Vec<[u32; 2]>,
    whitespace: Vec<[u32; 2]>,
    casefold: Vec<(u32, String)>,
}

fn tables() -> &'static Tables {
    static DATA: OnceLock<Tables> = OnceLock::new();
    DATA.get_or_init(|| {
        serde_json::from_str(include_str!("data/python-unicode15.json"))
            .expect("embedded original Unicode15 data is verified by the whole-scalar contract")
    })
}

fn in_ranges(value: char, ranges: &[[u32; 2]]) -> bool {
    let number = value as u32;
    ranges
        .binary_search_by(|[low, high]| {
            if *high < number {
                Ordering::Less
            } else if *low > number {
                Ordering::Greater
            } else {
                Ordering::Equal
            }
        })
        .is_ok()
}

pub(crate) fn word(value: char) -> bool {
    in_ranges(value, &tables().word)
}
pub(crate) fn space(value: char) -> bool {
    in_ranges(value, &tables().whitespace)
}

#[cfg(test)]
fn decimal(value: char) -> bool {
    in_ranges(value, &tables().decimal)
}

pub(crate) fn casefold(text: &str) -> String {
    let data = tables();
    let mut folded = String::with_capacity(text.len());
    for value in text.chars() {
        if let Ok(index) = data
            .casefold
            .binary_search_by_key(&(value as u32), |(number, _)| *number)
        {
            folded.push_str(&data.casefold[index].1);
        } else {
            folded.push(value);
        }
    }
    folded
}

fn character_class(ranges: &[[u32; 2]]) -> String {
    let mut class = String::from("[");
    for [low, high] in ranges {
        class.push_str(&format!("\\x{{{low:x}}}"));
        if low != high {
            class.push_str(&format!("-\\x{{{high:x}}}"));
        }
    }
    class.push(']');
    class
}

pub(crate) fn word_class() -> String {
    character_class(&tables().word)
}
pub(crate) fn decimal_class() -> String {
    character_class(&tables().decimal)
}

#[cfg(test)]
mod tests {
    use sha2::{Digest, Sha256};

    #[test]
    fn whole_scalar_contract_matches_independent_python_unicode15_digest() {
        let mut digest = Sha256::new();
        for number in 0..=0x10ffff_u32 {
            let Some(char) = char::from_u32(number) else {
                continue;
            };
            let flags = u8::from(super::word(char))
                | (u8::from(super::decimal(char)) << 1)
                | (u8::from(super::space(char)) << 2);
            let mut buffer = [0; 4];
            let folded = super::casefold(char.encode_utf8(&mut buffer));
            digest.update(number.to_be_bytes());
            digest.update([flags, u8::try_from(folded.len()).unwrap()]);
            digest.update(folded.as_bytes());
        }
        assert_eq!(
            format!("{:x}", digest.finalize()),
            "ade25dd6e59cf7919537e19af9070770bd3ec5ea50b5ad98c6948ea2ff495777"
        );
    }
}
