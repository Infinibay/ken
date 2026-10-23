//! Frozen original Python15 character properties used by syntax rules.
use serde::Deserialize;
use std::{collections::BTreeMap, sync::OnceLock};

#[derive(Deserialize)]
struct Compatibility {
    excluded_ranges: Vec<[u32; 2]>,
    aliases: BTreeMap<String, u32>,
    decimal_ranges: Vec<[u32; 2]>,
}
pub(crate) fn named_character(name: &str) -> Option<char> {
    let names = compatibility();
    let upper = name.to_ascii_uppercase();
    if let Some(&code) = names.aliases.get(&upper) {
        return char::from_u32(code);
    }
    let character = unicode_names2::character(name)?;
    let code = character as u32;
    if names
        .excluded_ranges
        .iter()
        .any(|r| r[0] <= code && code <= r[1])
    {
        return None;
    }
    // Python lookup is case insensitive but does not accept loose spaces,
    // underscores or noncanonical algorithmic hexadecimal spellings.
    (unicode_names2::name(character)?.to_string() == upper).then_some(character)
}

fn compatibility() -> &'static Compatibility {
    static NAMES: OnceLock<Compatibility> = OnceLock::new();
    NAMES.get_or_init(|| {
        serde_json::from_str(include_str!("python_unicode15.json"))
            .expect("fixed Unicode15 name compatibility")
    })
}

pub(crate) fn decimal(character: char) -> bool {
    let ranges = &compatibility().decimal_ranges;
    let code = character as u32;
    let index = ranges.partition_point(|range| range[1] < code);
    ranges.get(index).is_some_and(|range| range[0] <= code)
}
