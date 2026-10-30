//! Syntax checking for string patterns. This never builds a matching automaton.
//! These strings use Python `regex` extensions, unlike graph /literal/ patterns.
use crate::{ParseError, Result, ast::Span, expression_check::unsupported};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Default)]
struct Mode {
    verbose: bool,
}
#[derive(Clone, Copy, Debug)]
enum Error {
    Invalid,
    Depth,
    Work,
}
type Checked<T> = std::result::Result<T, Error>;
struct Pattern {
    chars: Vec<char>,
    pos: usize,
    depth: usize,
    groups: usize,
    work: usize,
    names: BTreeMap<String, usize>,
    open: BTreeMap<usize, usize>,
    references: Vec<String>,
    mode: Mode,
    version: Option<bool>,
}
pub(super) fn validate(text: &str, span: &Span) -> Result<()> {
    let mut p = Pattern {
        chars: text.chars().collect(),
        pos: 0,
        depth: 0,
        groups: 0,
        work: text.chars().count().saturating_mul(4).saturating_add(65536),
        names: BTreeMap::new(),
        open: BTreeMap::new(),
        references: vec![],
        mode: Mode::default(),
        version: None,
    };
    let result = p.sequence(false, false).and_then(|_| {
        if p.references.iter().all(|r| {
            r.parse::<usize>()
                .map_or_else(|_| p.names.contains_key(r), |n| n <= p.groups)
        }) {
            Ok(())
        } else {
            Err(Error::Invalid)
        }
    });
    match result {
        Ok(()) => Ok(()),
        Err(Error::Invalid) => Err(unsupported("invalid regular expression", span)),
        Err(Error::Work) => Err(ParseError::resource(
            "regular expression work limit exceeded",
            span.clone(),
        )),
        Err(Error::Depth) => Err(ParseError::resource(
            "regular expression depth limit exceeded",
            span.clone(),
        )),
    }
}
impl Pattern {
    fn charge(&mut self, units: usize) -> Checked<()> {
        self.work = self.work.checked_sub(units).ok_or(Error::Work)?;
        Ok(())
    }
    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }
    fn take(&mut self) -> Checked<char> {
        let c = self.peek().ok_or(Error::Invalid)?;
        self.pos += 1;
        Ok(c)
    }
    fn eat(&mut self, c: char) -> bool {
        if self.peek() == Some(c) {
            self.pos += 1;
            true
        } else {
            false
        }
    }
    fn expect(&mut self, c: char) -> Checked<()> {
        if self.eat(c) {
            Ok(())
        } else {
            Err(Error::Invalid)
        }
    }
    fn enter(&mut self) -> Checked<()> {
        self.depth += 1;
        if self.depth > 512 {
            Err(Error::Depth)
        } else {
            Ok(())
        }
    }
    fn skip(&mut self) {
        if self.mode.verbose {
            loop {
                if self.peek().is_some_and(char::is_whitespace) {
                    self.pos += 1;
                } else if self.eat('#') {
                    while self.peek().is_some_and(|c| c != '\n') {
                        self.pos += 1;
                    }
                } else {
                    break;
                }
            }
        }
    }
    fn sequence(&mut self, closing: bool, reset: bool) -> Checked<()> {
        crate::with_stack(|| {
            self.enter()?;
            let initial = self.groups;
            let mut maximum = initial;
            let mut atom = false;
            let mut repeated = false;
            loop {
                self.charge(1)?;
                self.skip();
                match self.peek() {
                    None => {
                        if closing {
                            return Err(Error::Invalid);
                        }
                        break;
                    }
                    Some(')') => {
                        if !closing {
                            return Err(Error::Invalid);
                        }
                        self.pos += 1;
                        break;
                    }
                    Some('|') => {
                        self.pos += 1;
                        atom = false;
                        repeated = false;
                        if reset {
                            maximum = maximum.max(self.groups);
                            self.groups = initial;
                        }
                    }
                    Some('*' | '+' | '?') => {
                        if !atom || repeated {
                            return Err(Error::Invalid);
                        }
                        self.pos += 1;
                        if matches!(self.peek(), Some('?' | '+')) {
                            self.pos += 1;
                        }
                        repeated = true;
                    }
                    Some('{') if atom => {
                        let saved = self.pos;
                        if self.quantifier()? {
                            if repeated {
                                return Err(Error::Invalid);
                            }
                            if matches!(self.peek(), Some('?' | '+')) {
                                self.pos += 1;
                            }
                            repeated = true;
                        } else {
                            self.pos = saved + 1;
                            atom = true;
                            repeated = false;
                        }
                    }
                    Some('(') => {
                        self.pos += 1;
                        if self.group()? {
                            atom = true;
                            repeated = false;
                        }
                    }
                    Some('[') => {
                        self.pos += 1;
                        self.class()?;
                        atom = true;
                        repeated = false;
                    }
                    Some('\\') => {
                        self.pos += 1;
                        self.escape(false)?;
                        atom = true;
                        repeated = false;
                    }
                    Some(_) => {
                        self.pos += 1;
                        atom = true;
                        repeated = false;
                    }
                }
            }
            if reset {
                self.groups = maximum.max(self.groups);
            }
            self.depth -= 1;
            Ok(())
        })
    }
    fn capture(&mut self, name: Option<String>) -> Checked<()> {
        let id = if let Some(name) = name {
            if let Some(id) = self.names.get(&name) {
                *id
            } else {
                self.groups += 1;
                self.names.insert(name, self.groups);
                self.groups
            }
        } else {
            self.groups += 1;
            self.groups
        };
        *self.open.entry(id).or_default() += 1;
        let mode = self.mode;
        self.sequence(true, false)?;
        self.mode = mode;
        let count = self.open.get_mut(&id).expect("open capture");
        *count -= 1;
        if *count == 0 {
            self.open.remove(&id);
        }
        Ok(())
    }
    fn name(&mut self, end: char) -> Checked<String> {
        let start = self.pos;
        while self.peek().is_some_and(|c| c != end) {
            self.pos += 1;
        }
        self.charge(self.pos - start)?;
        self.expect(end)?;
        let name: String = self.chars[start..self.pos - 1].iter().collect();
        if name.is_empty() {
            return Err(Error::Invalid);
        }
        Ok(name)
    }
    fn identifier(name: &str) -> bool {
        let mut chars = name.chars();
        chars.next().is_some_and(|c| c == '_' || c.is_alphabetic())
            && chars.all(|c| c == '_' || c.is_alphanumeric() || matches!(c as u32, 0x300..=0x36f))
    }
    fn reference(&mut self, name: String, recursion: bool) -> Checked<()> {
        let id = name
            .parse::<usize>()
            .ok()
            .or_else(|| self.names.get(&name).copied());
        if !recursion && id.is_some_and(|n| self.open.contains_key(&n)) {
            return Err(Error::Invalid);
        }
        if name != "0" && !Self::identifier(&name) && name.parse::<usize>().is_err() {
            return Err(Error::Invalid);
        }
        self.references.push(name);
        Ok(())
    }
    fn subpattern(&mut self, reset: bool) -> Checked<bool> {
        let mode = self.mode;
        self.sequence(true, reset)?;
        self.mode = mode;
        Ok(true)
    }
    fn group(&mut self) -> Checked<bool> {
        if self.eat('*') {
            let verb = self.name(')')?;
            return if matches!(verb.as_str(), "FAIL" | "F" | "PRUNE" | "SKIP") {
                Ok(true)
            } else {
                Err(Error::Invalid)
            };
        }
        if !self.eat('?') {
            self.capture(None)?;
            return Ok(true);
        }
        match self.take()? {
            ':' | '=' | '!' | '>' => self.subpattern(false),
            '|' => self.subpattern(true),
            '<' => {
                if matches!(self.peek(), Some('=' | '!')) {
                    self.pos += 1;
                    self.subpattern(false)
                } else {
                    let name = self.name('>')?;
                    if !Self::identifier(&name) {
                        return Err(Error::Invalid);
                    }
                    self.capture(Some(name))?;
                    Ok(true)
                }
            }
            'P' => match self.take()? {
                '<' => {
                    let name = self.name('>')?;
                    if !Self::identifier(&name) {
                        return Err(Error::Invalid);
                    }
                    self.capture(Some(name))?;
                    Ok(true)
                }
                '=' | '>' | '&' => {
                    let recursion = self.chars[self.pos - 1] != '=';
                    let name = self.name(')')?;
                    self.reference(name, recursion)?;
                    Ok(true)
                }
                _ => Err(Error::Invalid),
            },
            '&' => {
                let name = self.name(')')?;
                self.reference(name, true)?;
                Ok(true)
            }
            'R' => {
                self.expect(')')?;
                self.reference("0".into(), true)?;
                Ok(true)
            }
            c @ ('0'..='9' | '+' | '-')
                if c.is_ascii_digit() || self.peek().is_some_and(|c| c.is_ascii_digit()) =>
            {
                let mut name = c.to_string();
                while self.peek().is_some_and(|c| c.is_ascii_digit()) {
                    name.push(self.take()?);
                }
                self.expect(')')?;
                let number = if matches!(c, '+' | '-') {
                    let offset = name.parse::<isize>().map_err(|_| Error::Invalid)?;
                    let id = self
                        .groups
                        .checked_add_signed(offset)
                        .and_then(|id| id.checked_add(usize::from(c == '-')))
                        .ok_or(Error::Invalid)?;
                    if id == 0 {
                        return Err(Error::Invalid);
                    }
                    id.to_string()
                } else {
                    name
                };
                self.reference(number, true)?;
                Ok(true)
            }
            '#' => {
                loop {
                    match self.take()? {
                        ')' => break,
                        '\\' => {
                            self.take()?;
                        }
                        _ => (),
                    }
                }
                Ok(false)
            }
            '(' => {
                if self.eat('?') {
                    if self.eat('<') {
                        if !matches!(self.take()?, '=' | '!') {
                            return Err(Error::Invalid);
                        }
                    } else if !matches!(self.take()?, '=' | '!') {
                        return Err(Error::Invalid);
                    }
                    self.subpattern(false)?;
                } else {
                    let condition = self.name(')')?;
                    if condition != "DEFINE" {
                        self.reference(condition, true)?;
                    }
                }
                self.subpattern(false)
            }
            _ => {
                self.pos -= 1;
                self.flags()
            }
        }
    }
    fn flag_set(&mut self) -> Checked<BTreeSet<String>> {
        let mut set = BTreeSet::new();
        while let Some(c) = self.peek() {
            if c == 'V' {
                self.pos += 1;
                let version = self.take()?;
                if !matches!(version, '0' | '1') {
                    return Err(Error::Invalid);
                }
                set.insert(format!("V{version}"));
            } else if "abefimprsuwxL".contains(c) && c != ' ' {
                self.pos += 1;
                set.insert(c.to_string());
            } else {
                break;
            }
        }
        Ok(set)
    }
    fn flags(&mut self) -> Checked<bool> {
        let on = self.flag_set()?;
        let off = if self.eat('-') {
            let off = self.flag_set()?;
            if off.is_empty() {
                return Err(Error::Invalid);
            }
            off
        } else {
            BTreeSet::new()
        };
        if on.iter().any(|v| off.contains(v))
            || off
                .iter()
                .any(|v| matches!(v.as_str(), "b" | "e" | "p" | "r" | "V0" | "V1"))
        {
            return Err(Error::Invalid);
        }
        if on
            .iter()
            .filter(|v| matches!(v.as_str(), "a" | "u" | "L"))
            .count()
            > 1
        {
            return Err(Error::Invalid);
        }
        let before = self.mode;
        for version in [false, true] {
            if on.contains(if version { "V1" } else { "V0" }) {
                if self.version.is_some_and(|v| v != version) {
                    return Err(Error::Invalid);
                }
                self.version = Some(version);
            }
        }
        if on.contains("x") {
            self.mode.verbose = true;
        }
        if off.contains("x") {
            self.mode.verbose = false;
        }
        if self.eat(':') {
            self.sequence(true, false)?;
            self.mode = before;
            Ok(true)
        } else {
            self.expect(')')?;
            Ok(false)
        }
    }
    fn digits(&mut self) -> String {
        let start = self.pos;
        while self.peek().is_some_and(|c| c.is_ascii_digit()) {
            self.pos += 1;
        }
        self.chars[start..self.pos].iter().collect()
    }
    fn quantifier(&mut self) -> Checked<bool> {
        self.pos += 1;
        let start = self.pos;
        let lo = self.digits();
        let comma = self.eat(',');
        let hi = if comma { self.digits() } else { lo.clone() };
        if (!lo.is_empty() || comma) && self.eat('}') {
            let lo = if lo.is_empty() {
                0
            } else {
                lo.parse::<u64>().map_err(|_| Error::Invalid)?
            };
            let hi = if comma && hi.is_empty() {
                u64::MAX
            } else {
                hi.parse::<u64>().map_err(|_| Error::Invalid)?
            };
            return if lo <= hi {
                Ok(true)
            } else {
                Err(Error::Invalid)
            };
        }
        let fuzzy = self.chars.get(start).is_some_and(|c| "deis".contains(*c))
            || !lo.is_empty() && self.peek().is_some_and(|c| "<dis".contains(c));
        self.pos = start;
        if !fuzzy || !self.peek().is_some_and(|c| "deis0123456789".contains(c)) {
            return Ok(false);
        }
        let tail = self.chars[start..].iter().position(|c| *c == '}');
        let Some(end) = tail.map(|n| start + n) else {
            self.charge(self.chars.len() - start)?;
            return Err(Error::Invalid);
        };
        self.charge(end - start)?;
        let text: String = self.chars[start..end].iter().collect();
        if !text.contains(['d', 'e', 'i', 's']) {
            return Ok(false);
        }
        // Parse the constraints separately from the optional one-atom test.
        let constraints = text.split(':').next().unwrap();
        let mut seen = BTreeSet::new();
        for part in constraints.split(',') {
            fuzzy_limit(part, &mut seen)?;
        }
        self.pos = start + constraints.chars().count();
        if self.eat(':') {
            match self.take()? {
                '[' => {
                    self.class()?;
                }
                '\\' => {
                    self.escape(false)?;
                }
                '(' | ')' | '|' | '*' | '+' | '?' | '{' | '}' => return Err(Error::Invalid),
                _ => (),
            }
        }
        self.expect('}')?;
        Ok(true)
    }
    fn escape(&mut self, class: bool) -> Checked<Option<u32>> {
        let c = self.take()?;
        match c {
            'x' | 'u' | 'U' => {
                let count = match c {
                    'x' => 2,
                    'u' => 4,
                    _ => 8,
                };
                let mut value = 0u32;
                for _ in 0..count {
                    value = value
                        .checked_mul(16)
                        .and_then(|v| self.take().ok().and_then(|c| c.to_digit(16)).map(|n| v + n))
                        .ok_or(Error::Invalid)?;
                }
                if value >= 0x110000 {
                    return Err(Error::Invalid);
                }
                Ok(Some(value))
            }
            'N' => {
                if !self.eat('{') {
                    return Ok(Some('N' as u32));
                }
                let name = self.name('}')?;
                let value = unicode_names2::character(&name)
                    .filter(|c| crate::lexer::assigned(*c))
                    .ok_or(Error::Invalid)?;
                Ok(Some(value as u32))
            }
            'p' | 'P' => {
                if self.eat('{') {
                    let name = self.name('}')?;
                    if !property(name.trim_start_matches('^')) {
                        return Err(Error::Invalid);
                    }
                } else if self.peek().is_some_and(|c| "CLMNPSZ".contains(c)) {
                    self.pos += 1;
                }
                Ok(None)
            }
            'g' if !class => {
                if self.eat('<') {
                    let saved = self.pos;
                    let name = self.name('>');
                    if let Ok(name) = name {
                        self.reference(name, false)?;
                    } else {
                        self.pos = saved - 1;
                    }
                }
                Ok(None)
            }
            'L' if !class => Err(Error::Invalid), // named lists require kwargs, unavailable here
            'G' | 'R' | 'X' | 'A' | 'B' | 'K' | 'm' | 'M' | 'Z' | 'z' if !class => Ok(None),
            'd' | 'D' | 's' | 'S' | 'w' | 'W' | 'h' => Ok(None),
            'a' => Ok(Some(7)),
            'b' => Ok(if class { Some(8) } else { None }),
            'f' => Ok(Some(12)),
            'n' => Ok(Some(10)),
            'r' => Ok(Some(13)),
            't' => Ok(Some(9)),
            'v' => Ok(Some(11)),
            '0'..='9' => {
                let mut digits = c.to_string();
                if class || c == '0' {
                    if c > '7' {
                        return Err(Error::Invalid);
                    }
                    while digits.len() < 3 && self.peek().is_some_and(|c| matches!(c, '0'..='7')) {
                        digits.push(self.take()?);
                    }
                    return Ok(Some(
                        u32::from_str_radix(&digits, 8).map_err(|_| Error::Invalid)?,
                    ));
                }
                if self.peek().is_some_and(|c| c.is_ascii_digit()) {
                    digits.push(self.take()?);
                }
                if digits.len() == 2
                    && digits.chars().all(|c| c <= '7')
                    && self.peek().is_some_and(|c| matches!(c, '0'..='7'))
                {
                    digits.push(self.take()?);
                    return Ok(Some(u32::from_str_radix(&digits, 8).unwrap()));
                }
                self.reference(digits, false)?;
                Ok(None)
            }
            _ if c.is_ascii_alphabetic() => Err(Error::Invalid),
            _ => Ok(Some(c as u32)),
        }
    }
    fn class_atom(&mut self) -> Checked<Option<u32>> {
        match self.take()? {
            '\\' => self.escape(true),
            '[' if self.version == Some(true) => {
                self.class()?;
                Ok(None)
            }
            c => Ok(Some(c as u32)),
        }
    }
    fn class(&mut self) -> Checked<()> {
        crate::with_stack(|| {
            self.enter()?;
            self.eat('^');
            let mut first = true;
            let mut operand = false;
            loop {
                if self.peek().is_none() {
                    return Err(Error::Invalid);
                }
                if self.peek() == Some(']') && !first {
                    if !operand {
                        return Err(Error::Invalid);
                    }
                    self.pos += 1;
                    break;
                }
                if self.version == Some(true)
                    && self.pos + 1 < self.chars.len()
                    && self.chars[self.pos] == self.chars[self.pos + 1]
                    && "&|~-".contains(self.chars[self.pos])
                {
                    if !operand {
                        return Err(Error::Invalid);
                    }
                    self.pos += 2;
                    operand = false;
                    first = false;
                    continue;
                }
                if self.chars[self.pos..].starts_with(&['[', ':']) {
                    self.pos += 2;
                    self.eat('^');
                    let start = self.pos;
                    while self.pos + 1 < self.chars.len()
                        && !self.chars[self.pos..].starts_with(&[':', ']'])
                    {
                        self.pos += 1;
                    }
                    let name: String = self.chars[start..self.pos].iter().collect();
                    if !property(&name) {
                        return Err(Error::Invalid);
                    }
                    self.expect(':')?;
                    self.expect(']')?;
                } else {
                    let left = self.class_atom()?;
                    if self.peek() == Some('-')
                        && self
                            .chars
                            .get(self.pos + 1)
                            .is_some_and(|c| *c != ']' && *c != '-')
                    {
                        self.pos += 1;
                        let right = self.class_atom()?;
                        if let (Some(a), Some(b)) = (left, right)
                            && a > b
                        {
                            return Err(Error::Invalid);
                        }
                    }
                }
                first = false;
                operand = true;
            }
            self.depth -= 1;
            Ok(())
        })
    }
}

fn fuzzy_limit(part: &str, seen: &mut BTreeSet<String>) -> Checked<()> {
    let parts: Vec<_> = part.split('<').collect();
    let number = |s: &str| s.parse::<i64>().map_err(|_| Error::Invalid);
    let upper = |s: &str| -> Checked<i64> {
        if let Some(s) = s.strip_prefix('=') {
            number(s)
        } else {
            number(s)?.checked_sub(1).ok_or(Error::Invalid)
        }
    };
    match parts.as_slice() {
        [kind] if kind.len() == 1 && "deis".contains(kind) => {
            if !seen.insert((*kind).into()) {
                return Err(Error::Invalid);
            }
        }
        [kind, limit] if kind.len() == 1 && "deis".contains(kind) => {
            if upper(limit)? < 0 || !seen.insert((*kind).into()) {
                return Err(Error::Invalid);
            }
        }
        [low, kind, high] => {
            let inclusive = kind.starts_with('=');
            let kind = kind.trim_start_matches('=');
            if kind.len() != 1 || !"deis".contains(kind) {
                return Err(Error::Invalid);
            }
            let low = number(low)?
                .checked_add(i64::from(!inclusive))
                .ok_or(Error::Invalid)?;
            if low > upper(high)? || !seen.insert(kind.into()) {
                return Err(Error::Invalid);
            }
        }
        [sum, limit] => {
            if upper(limit)? < 0 || !seen.insert("cost".into()) {
                return Err(Error::Invalid);
            }
            let mut terms = BTreeSet::new();
            for term in sum.split('+') {
                let Some(kind) = term.chars().last() else {
                    return Err(Error::Invalid);
                };
                if !"dis".contains(kind) || !terms.insert(kind) {
                    return Err(Error::Invalid);
                }
                let coefficient = &term[..term.len() - 1];
                if !coefficient.is_empty() {
                    number(coefficient)?;
                }
            }
        }
        _ => return Err(Error::Invalid),
    }
    Ok(())
}
#[derive(serde::Deserialize)]
struct Properties {
    aliases: BTreeMap<String, u32>,
    values: BTreeMap<u32, BTreeSet<String>>,
}
fn property(name: &str) -> bool {
    static DATA: std::sync::OnceLock<Properties> = std::sync::OnceLock::new();
    let data = DATA.get_or_init(|| {
        serde_json::from_str(include_str!("../../resources/regex-properties.json"))
            .expect("frozen regex properties")
    });
    let normalize = |s: &str| {
        s.chars()
            .filter(|c| !matches!(c, '_' | '-' | ' '))
            .flat_map(char::to_uppercase)
            .collect::<String>()
    };
    let contains = |p: &str, v: &str| {
        data.aliases
            .get(p)
            .and_then(|id| data.values.get(id))
            .is_some_and(|values| values.contains(v))
    };
    if let Some((p, v)) = name.split_once(['=', ':']) {
        let p = normalize(p);
        let v = normalize(v);
        return (p == "GENERALCATEGORY" || p == "GC") && v == "ASSIGNED" || contains(&p, &v);
    }
    let name = normalize(name);
    if name == "ASSIGNED"
        || ["GC", "SCRIPT", "BLOCK"].iter().any(|p| contains(p, &name))
        || data.aliases.contains_key(&name)
    {
        return true;
    }
    if let Some(name) = name.strip_prefix("IS") {
        return contains(name, "YES") || contains("SCRIPT", name);
    }
    name.strip_prefix("IN")
        .is_some_and(|name| contains("BLOCK", name))
}
