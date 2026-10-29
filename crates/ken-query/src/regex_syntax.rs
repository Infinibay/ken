//! Validate the lexer's restricted Python regex grammar without expanding repeats.
//! No automaton is built; even a{4294967294} has constant validation storage.
#[derive(Clone, Copy)]
enum Atom {
    None,
    Ready,
    Repeat,
    Modified,
}
pub(crate) fn validate(pattern: &str) -> Result<(), String> {
    let mut p = Pattern {
        chars: pattern.chars().collect(),
        pos: 0,
    };
    let mut groups = Vec::new();
    let mut atom = Atom::None;
    while let Some(c) = p.current() {
        let at = p.pos;
        p.pos += 1;
        match c {
            '[' => {
                p.class(at)?;
                atom = Atom::Ready;
            }
            '\\' => {
                let literal = p.escape(at, false)?;
                atom = if literal.is_some()
                    || matches!(p.chars.get(at + 1), Some('d' | 'D' | 's' | 'S' | 'w' | 'W'))
                {
                    Atom::Ready
                } else {
                    Atom::None
                };
            }
            '(' => {
                groups.push(at);
                if p.current() == Some('?') {
                    p.pos += 2;
                }
                atom = Atom::None;
            }
            ')' => {
                if groups.pop().is_none() {
                    return Err(error("unbalanced parenthesis", at));
                }
                atom = Atom::Ready;
            }
            '|' => atom = Atom::None,
            '^' | '$' => atom = Atom::None,
            '*' | '+' | '?' => {
                atom = repeat(atom, c, at)?;
            }
            '{' => {
                if let Some((minimum, maximum)) = p.repetition() {
                    if let (Some(a), Some(b)) = (minimum.as_ref(), maximum.as_ref()) {
                        let a = number(a)?;
                        let b = number(b)?;
                        if b < a {
                            return Err(error("min repeat greater than max repeat", at + 1));
                        }
                    } else {
                        if let Some(n) = minimum {
                            number(&n)?;
                        }
                        if let Some(n) = maximum {
                            number(&n)?;
                        }
                    }
                    atom = repeat(atom, '{', at)?;
                } else {
                    atom = Atom::Ready;
                }
            }
            _ => atom = Atom::Ready,
        }
    }
    if let Some(start) = groups.last() {
        return Err(error("missing ), unterminated subpattern", *start));
    }
    Ok(())
}
fn number(n: &str) -> Result<u32, String> {
    let mut value = 0u32;
    for b in n.bytes() {
        value = value
            .checked_mul(10)
            .and_then(|n| n.checked_add(u32::from(b - b'0')))
            .filter(|n| *n < u32::MAX)
            .ok_or("the repetition number is too large")?;
    }
    Ok(value)
}
fn repeat(atom: Atom, op: char, at: usize) -> Result<Atom, String> {
    match atom {
        Atom::None => Err(error("nothing to repeat", at)),
        Atom::Repeat if matches!(op, '?' | '+') => Ok(Atom::Modified),
        Atom::Repeat | Atom::Modified => Err(error("multiple repeat", at)),
        Atom::Ready => Ok(Atom::Repeat),
    }
}
fn error(message: &str, pos: usize) -> String {
    format!("{message} at position {pos}")
}
struct Pattern {
    chars: Vec<char>,
    pos: usize,
}
impl Pattern {
    fn current(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }
    fn raw(&self, start: usize, end: usize) -> String {
        self.chars[start..end.min(self.chars.len())]
            .iter()
            .collect()
    }
    fn escape(&mut self, start: usize, in_class: bool) -> Result<Option<u32>, String> {
        let Some(c) = self.current() else {
            return Err(error("bad escape (end of pattern)", start));
        };
        self.pos += 1;
        if matches!(c, 'x' | 'u' | 'U') {
            let count = match c {
                'x' => 2,
                'u' => 4,
                _ => 8,
            };
            let mut n = 0u32;
            for _ in 0..count {
                let Some(d) = self
                    .current()
                    .and_then(|c| c.to_digit(16))
                    .filter(|_| self.current().is_some_and(|c| c.is_ascii_hexdigit()))
                else {
                    return Err(error(
                        &format!("incomplete escape {}", self.raw(start, self.pos)),
                        start,
                    ));
                };
                n = n * 16 + d;
                self.pos += 1;
            }
            if n > 0x10ffff {
                return Err(error(
                    &format!("bad escape {}", self.raw(start, self.pos)),
                    start,
                ));
            }
            return Ok(Some(n));
        }
        if c == 'N' {
            if self.current() != Some('{') {
                return Err(error("missing {", self.pos));
            }
            self.pos += 1;
            let begin = self.pos;
            while self.current().is_some_and(|c| c != '}') {
                self.pos += 1;
            }
            if self.current().is_none() {
                return Err(error("missing }, unterminated name", begin));
            }
            if self.pos == begin {
                return Err(error("missing character name", begin));
            }
            let name = self.raw(begin, self.pos);
            self.pos += 1;
            let Some(c) = unicode_names2::character(&name).filter(|c| crate::lexer::assigned(*c))
            else {
                return Err(error(
                    &format!(
                        "undefined character name {}",
                        ken_program::value::string_repr(&name.as_str().into())
                    ),
                    start,
                ));
            };
            return Ok(Some(c as u32));
        }
        Ok(match c {
            'a' => Some(7),
            'b' => {
                if in_class {
                    Some(8)
                } else {
                    None
                }
            }
            'f' => Some(12),
            'n' => Some(10),
            'r' => Some(13),
            't' => Some(9),
            'v' => Some(11),
            'd' | 'D' | 's' | 'S' | 'w' | 'W' => None,
            'A' | 'Z' | 'B' if !in_class => None,
            _ if c.is_ascii_alphabetic() => return Err(error(&format!("bad escape \\{c}"), start)),
            _ => Some(c as u32),
        })
    }
    fn element(&mut self) -> Result<Option<u32>, String> {
        let at = self.pos;
        let c = self.current().unwrap();
        self.pos += 1;
        if c == '\\' {
            self.escape(at, true)
        } else {
            Ok(Some(c as u32))
        }
    }
    fn class(&mut self, start: usize) -> Result<(), String> {
        if self.current() == Some('^') {
            self.pos += 1;
        }
        let mut first = true;
        loop {
            let Some(c) = self.current() else {
                return Err(error("unterminated character set", start));
            };
            if c == ']' && !first {
                self.pos += 1;
                return Ok(());
            }
            first = false;
            let begin = self.pos;
            let left = self.element()?;
            let left_token_end = begin + if c == '\\' { 2 } else { 1 };
            if self.current() == Some('-')
                && self.chars.get(self.pos + 1).is_some_and(|c| *c != ']')
            {
                self.pos += 1;
                let Some(_) = self.current() else {
                    return Err(error("unterminated character set", start));
                };
                let right_begin = self.pos;
                let right_token_end =
                    right_begin + if self.current() == Some('\\') { 2 } else { 1 };
                let right = self.element()?;
                if left.zip(right).is_none_or(|(a, b)| a > b) {
                    return Err(error(
                        &format!(
                            "bad character range {}-{}",
                            self.raw(begin, left_token_end),
                            self.raw(right_begin, right_token_end)
                        ),
                        self.pos - (left_token_end - begin) - 1 - (right_token_end - right_begin),
                    ));
                }
            }
        }
    }
    fn repetition(&mut self) -> Option<(Option<String>, Option<String>)> {
        let saved = self.pos;
        let begin = self.pos;
        while self.current().is_some_and(|c| c.is_ascii_digit()) {
            self.pos += 1;
        }
        let minimum = (self.pos > begin).then(|| self.raw(begin, self.pos));
        let maximum;
        if self.current() == Some(',') {
            self.pos += 1;
            let begin = self.pos;
            while self.current().is_some_and(|c| c.is_ascii_digit()) {
                self.pos += 1;
            }
            maximum = (self.pos > begin).then(|| self.raw(begin, self.pos));
        } else if minimum.is_some() {
            maximum = minimum.clone();
        } else {
            self.pos = saved;
            return None;
        }
        if self.current() != Some('}') {
            self.pos = saved;
            return None;
        }
        self.pos += 1;
        Some((minimum, maximum))
    }
}
