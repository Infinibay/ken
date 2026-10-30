//! Immutable behavior facts from the authenticated original Unicode engines.
use super::*;
use serde::Deserialize;
use std::sync::OnceLock;
#[derive(Deserialize)]
struct Data {
    aliases: BTreeMap<String, (u32, BTreeMap<String, u32>)>,
    properties: BTreeMap<u32, Vec<[u32; 2]>>,
    stdlib: BTreeMap<String, Vec<[u32; 2]>>,
    stdlib_lower: BTreeMap<u32, u32>,
    stdlib_extra: BTreeMap<u32, Vec<u32>>,
    simple_fold: BTreeMap<u32, Vec<u32>>,
    full_fold: BTreeMap<u32, Vec<u32>>,
}
fn data() -> &'static Data {
    static DATA: OnceLock<Data> = OnceLock::new();
    DATA.get_or_init(|| {
        serde_json::from_str(include_str!(
            "../../../resources/regex-runtime-unicode.json"
        ))
        .expect("authenticated regex Unicode facts")
    })
}
pub(super) fn initialize() {
    let _ = data();
}
fn normalized(text: &str) -> String {
    text.chars()
        .filter(|c| !matches!(c, '_' | '-' | ' '))
        .flat_map(char::to_uppercase)
        .collect()
}
pub(super) fn property(name: &str) -> Option<u32> {
    let name = normalized(name);
    let d = data();
    if let Some((property, value)) = name.split_once(['=', ':']) {
        let (id, values) = d.aliases.get(property)?;
        return values.get(value).map(|v| (id << 16) | v);
    }
    for property in ["GENERALCATEGORY", "SCRIPT", "BLOCK"] {
        if let Some((id, values)) = d.aliases.get(property)
            && let Some(value) = values.get(&name)
        {
            return Some((id << 16) | value);
        }
    }
    if let Some((id, values)) = d.aliases.get(&name) {
        return values.get("YES").map(|v| (id << 16) | v);
    }
    if let Some(rest) = name.strip_prefix("IS") {
        return property(rest);
    }
    if let Some(rest) = name.strip_prefix("IN") {
        let (id, values) = d.aliases.get("BLOCK")?;
        return values.get(rest).map(|v| (id << 16) | v);
    }
    None
}
/// Bare nonbinary property aliases mean any value except the engine's zero
/// value. Explicit property/value forms retain the frozen membership above.
pub(super) fn property_set(name: &str) -> Option<Set> {
    if let Some(id) = property(name) {
        return Some(Set::Property(id));
    }
    let name = normalized(name);
    let (id, _) = data().aliases.get(&name)?;
    Some(Set::Not(Box::new(Set::Property(id << 16))))
}
pub(super) fn contains(ranges: &[[u32; 2]], cp: u32) -> bool {
    ranges
        .get(ranges.partition_point(|r| r[1] < cp))
        .is_some_and(|r| r[0] <= cp)
}
pub(super) fn has(property: u32, cp: u32) -> bool {
    data()
        .properties
        .get(&property)
        .is_some_and(|ranges| contains(ranges, cp))
}
pub(super) fn class(class: Class, cp: u32, dialect: Dialect, ascii: bool) -> bool {
    if ascii {
        return match class {
            Class::Word => cp == 95 || cp <= 127 && (cp as u8).is_ascii_alphanumeric(),
            Class::Digit => matches!(cp, 48..=57),
            Class::Space => matches!(cp, 9..=13 | 32),
        };
    }
    let name = match class {
        Class::Word => "word",
        Class::Digit => "digit",
        Class::Space => "space",
    };
    if dialect == Dialect::Stdlib {
        return contains(&data().stdlib[name], cp);
    }
    let property = match class {
        Class::Word => "WORD",
        Class::Digit => "GENERALCATEGORY=DECIMALNUMBER",
        Class::Space => "WHITESPACE",
    };
    self::property(property).is_some_and(|p| has(p, cp))
}
pub(super) fn cases(cp: u32, dialect: Dialect, ascii: bool) -> Vec<u32> {
    if ascii {
        return if (65..=90).contains(&cp) {
            vec![cp, cp + 32]
        } else if (97..=122).contains(&cp) {
            vec![cp, cp - 32]
        } else {
            vec![cp]
        };
    }
    let d = data();
    if dialect == Dialect::Regex {
        return d.simple_fold.get(&cp).cloned().unwrap_or_else(|| vec![cp]);
    }
    let lower = d.stdlib_lower.get(&cp).copied().unwrap_or(cp);
    let mut result = vec![cp, lower];
    result.extend(d.stdlib_extra.get(&lower).into_iter().flatten().copied());
    let equivalents = result.clone();
    result.extend(
        d.stdlib_lower
            .iter()
            .filter_map(|(key, value)| equivalents.contains(value).then_some(*key)),
    );
    result
}
pub(super) fn equal(a: u32, b: u32, flags: Flags, dialect: Dialect) -> bool {
    a == b || flags.ignore && cases(a, dialect, flags.ascii).contains(&b)
}
pub(super) fn fold(cp: u32) -> Vec<u32> {
    data()
        .full_fold
        .get(&cp)
        .cloned()
        .unwrap_or_else(|| vec![cp])
}
pub(super) fn set(set: &Set, cp: u32, flags: Flags, dialect: Dialect) -> bool {
    match set {
        Set::Char(c) => equal(*c, cp, flags, dialect),
        Set::Range(a, b) => {
            if a <= &cp && &cp <= b {
                return true;
            }
            flags.ignore
                && cases(cp, dialect, flags.ascii)
                    .iter()
                    .any(|p| a <= p && p <= b)
        }
        Set::Class(c) => class(*c, cp, dialect, flags.ascii),
        Set::Property(p) => {
            has(*p, cp)
                || flags.ignore && cases(cp, dialect, flags.ascii).iter().any(|c| has(*p, *c))
        }
        Set::Union(v) => v.iter().any(|v| self::set(v, cp, flags, dialect)),
        Set::Not(v) => !self::set(v, cp, flags, dialect),
        Set::And(a, b) => self::set(a, cp, flags, dialect) && self::set(b, cp, flags, dialect),
        Set::Difference(a, b) => {
            self::set(a, cp, flags, dialect) && !self::set(b, cp, flags, dialect)
        }
        Set::Xor(a, b) => self::set(a, cp, flags, dialect) != self::set(b, cp, flags, dialect),
    }
}
pub(super) fn grapheme_end(text: &[u32], start: usize, control: &mut Control<'_>) -> Result<usize> {
    if start >= text.len() {
        return Ok(start);
    }
    fn p(cp: u32, name: &str) -> bool {
        property(name).is_some_and(|p| has(p, cp))
    }
    let gcb = |cp, name| p(cp, &format!("GCB={name}"));
    let mut end = start + 1;
    let mut ri = usize::from(gcb(text[start], "RI"));
    while end < text.len() {
        control.poll()?;
        let (a, b) = (text[end - 1], text[end]);
        let join = if a == 13 && b == 10 {
            true
        } else if gcb(a, "CONTROL")
            || gcb(a, "CR")
            || gcb(a, "LF")
            || gcb(b, "CONTROL")
            || gcb(b, "CR")
            || gcb(b, "LF")
        {
            false
        } else if gcb(a, "L") && (gcb(b, "L") || gcb(b, "V") || gcb(b, "LV") || gcb(b, "LVT"))
            || (gcb(a, "LV") || gcb(a, "V")) && (gcb(b, "V") || gcb(b, "T"))
            || (gcb(a, "LVT") || gcb(a, "T")) && gcb(b, "T")
            || gcb(b, "EXTEND")
            || gcb(b, "ZWJ")
            || gcb(b, "SPACINGMARK")
            || gcb(a, "PREPEND")
        {
            true
        } else if p(b, "EXTENDEDPICTOGRAPHIC") && gcb(a, "ZWJ") {
            let mut i = end - 1;
            while i > start && gcb(text[i - 1], "EXTEND") {
                i -= 1;
            }
            i > start && p(text[i - 1], "EXTENDEDPICTOGRAPHIC")
        } else if p(b, "INCB=CONSONANT") {
            let mut i = end;
            let mut linker = false;
            while i > start && (p(text[i - 1], "INCB=EXTEND") || p(text[i - 1], "INCB=LINKER")) {
                i -= 1;
                linker |= p(text[i], "INCB=LINKER");
            }
            linker && i > start && p(text[i - 1], "INCB=CONSONANT")
        } else {
            gcb(a, "RI") && gcb(b, "RI") && ri % 2 == 1
        };
        if !join {
            break;
        }
        if gcb(b, "RI") {
            ri += 1;
        } else {
            ri = 0;
        }
        end += 1;
    }
    Ok(end)
}

/// Positive finite sets expand only characters actually present before casing,
/// as the original compiler does. Negated/property atoms remain one codepoint.
pub(super) fn expansions(
    set: &Set,
    flags: Flags,
    dialect: Dialect,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<Vec<Vec<u32>>> {
    if dialect != Dialect::Regex
        || !flags.ignore
        || !flags.full
        || flags.ascii
        || matches!(set, Set::Not(_) | Set::Property(_) | Set::Class(_))
    {
        return Ok(vec![]);
    }
    let mut raw = flags;
    raw.ignore = false;
    let mut result = vec![];
    for (cp, folded) in &data().full_fold {
        if folded.len() <= 1 {
            continue;
        }
        check()?;
        if self::set(set, *cp, raw, dialect) && !result.contains(folded) {
            result.push(folded.clone());
        }
    }
    Ok(result)
}
