//! Default Unicode word boundaries and WORD-mode line boundaries.
use super::*;
fn property(cp: u32, name: &str) -> bool {
    unicode::property(name).is_some_and(|id| unicode::has(id, cp))
}
fn wb(cp: u32, name: &str) -> bool {
    property(cp, &format!("WB={name}"))
}
fn ignored(cp: u32) -> bool {
    wb(cp, "EXTEND") || wb(cp, "FORMAT") || wb(cp, "ZWJ")
}
fn newline(cp: u32) -> bool {
    wb(cp, "CR") || wb(cp, "LF") || wb(cp, "NEWLINE")
}
fn letter(cp: u32) -> bool {
    wb(cp, "ALETTER") || wb(cp, "HEBREWLETTER")
}
fn mid_letter(cp: u32) -> bool {
    wb(cp, "MIDLETTER") || wb(cp, "MIDNUMLET") || wb(cp, "SINGLEQUOTE")
}
fn mid_number(cp: u32) -> bool {
    wb(cp, "MIDNUM") || wb(cp, "MIDNUMLET") || wb(cp, "SINGLEQUOTE")
}
fn previous(text: &[u32], mut end: usize, control: &mut Control<'_>) -> Result<Option<usize>> {
    while end > 0 {
        control.poll()?;
        end -= 1;
        if !ignored(text[end]) {
            return Ok(Some(end));
        }
    }
    Ok(None)
}
fn following(text: &[u32], mut start: usize, control: &mut Control<'_>) -> Result<Option<usize>> {
    while start < text.len() {
        control.poll()?;
        if !ignored(text[start]) {
            return Ok(Some(start));
        }
        start += 1;
    }
    Ok(None)
}
pub(super) fn word(text: &[u32], position: usize, control: &mut Control<'_>) -> Result<bool> {
    if text.is_empty() {
        return Ok(false);
    }
    if position == 0 || position == text.len() {
        return Ok(true);
    }
    let (a, b) = (text[position - 1], text[position]);
    if a == 13 && b == 10 {
        return Ok(false);
    }
    if newline(a) || newline(b) {
        return Ok(true);
    }
    if wb(a, "ZWJ") && property(b, "EXTENDEDPICTOGRAPHIC") {
        return Ok(false);
    }
    if wb(a, "WSEGSPACE") && wb(b, "WSEGSPACE") {
        return Ok(false);
    }
    if ignored(b) {
        return Ok(false);
    }
    let Some(left) = previous(text, position, control)? else {
        return Ok(true);
    };
    let a = text[left];
    let Some(right) = following(text, position, control)? else {
        return Ok(true);
    };
    let b = text[right];
    let before = previous(text, left, control)?.map(|i| text[i]);
    let after = following(text, right + 1, control)?.map(|i| text[i]);
    if letter(a) && letter(b) {
        return Ok(false);
    }
    if letter(a) && mid_letter(b) && after.is_some_and(letter)
        || before.is_some_and(letter) && mid_letter(a) && letter(b)
    {
        return Ok(false);
    }
    if wb(a, "HEBREWLETTER") && wb(b, "SINGLEQUOTE") {
        return Ok(false);
    }
    if wb(a, "HEBREWLETTER") && wb(b, "DOUBLEQUOTE") && after.is_some_and(|c| wb(c, "HEBREWLETTER"))
        || before.is_some_and(|c| wb(c, "HEBREWLETTER"))
            && wb(a, "DOUBLEQUOTE")
            && wb(b, "HEBREWLETTER")
    {
        return Ok(false);
    }
    if wb(a, "NUMERIC") && wb(b, "NUMERIC")
        || letter(a) && wb(b, "NUMERIC")
        || wb(a, "NUMERIC") && letter(b)
    {
        return Ok(false);
    }
    if wb(a, "NUMERIC") && mid_number(b) && after.is_some_and(|c| wb(c, "NUMERIC"))
        || before.is_some_and(|c| wb(c, "NUMERIC")) && mid_number(a) && wb(b, "NUMERIC")
    {
        return Ok(false);
    }
    if wb(a, "KATAKANA") && wb(b, "KATAKANA") {
        return Ok(false);
    }
    let extendable = |cp| letter(cp) || wb(cp, "NUMERIC") || wb(cp, "KATAKANA");
    if (extendable(a) || wb(a, "EXTENDNUMLET")) && wb(b, "EXTENDNUMLET")
        || wb(a, "EXTENDNUMLET") && extendable(b)
    {
        return Ok(false);
    }
    if wb(a, "RI") && wb(b, "RI") {
        let mut count = 1usize;
        let mut at = left;
        while let Some(i) = previous(text, at, control)? {
            if !wb(text[i], "RI") {
                break;
            }
            count += 1;
            at = i;
        }
        if count % 2 == 1 {
            return Ok(false);
        }
    }
    Ok(true)
}
pub(super) fn line_start(text: &[u32], position: usize, multi: bool, word: bool) -> bool {
    position == 0
        || multi
            && position > 0
            && if word {
                is_line(text[position - 1])
                    && !(text[position - 1] == 13 && text.get(position) == Some(&10))
            } else {
                text[position - 1] == 10
            }
}
pub(super) fn line_end(text: &[u32], position: usize, multi: bool, word: bool) -> bool {
    if position == text.len() {
        return true;
    }
    let cp = text[position];
    if !word {
        return cp == 10 && (multi || position + 1 == text.len());
    }
    if !is_line(cp) || cp == 10 && position > 0 && text[position - 1] == 13 {
        return false;
    }
    multi
        || position + 1 == text.len()
        || cp == 13 && position + 2 == text.len() && text.get(position + 1) == Some(&10)
}
fn is_line(cp: u32) -> bool {
    matches!(cp, 10..=13 | 0x85 | 0x2028 | 0x2029)
}
