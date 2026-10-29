//! Contextual tokenization over UTF-8 byte positions, without prefix re-encoding.
use crate::{ParseError, Result, Span, regex_syntax};
use std::sync::{Arc, OnceLock};
#[derive(Clone, Debug)]
pub(crate) struct Token {
    pub kind: &'static str,
    pub text: String,
    pub span: Span,
}
#[derive(serde::Deserialize)]
struct Properties {
    alpha: Vec<[u32; 2]>,
    digit: Vec<[u32; 2]>,
    assigned: Vec<[u32; 2]>,
}
fn properties() -> &'static Properties {
    static DATA: OnceLock<Properties> = OnceLock::new();
    DATA.get_or_init(|| {
        serde_json::from_str(include_str!("../resources/unicode15.json"))
            .expect("frozen Python Unicode15 properties")
    })
}
fn contains(ranges: &[[u32; 2]], c: char) -> bool {
    let n = c as u32;
    ranges
        .get(ranges.partition_point(|r| r[1] < n))
        .is_some_and(|r| r[0] <= n)
}
pub(crate) fn assigned(c: char) -> bool {
    contains(&properties().assigned, c)
}
fn alpha(c: char) -> bool {
    contains(&properties().alpha, c)
}
fn digit(c: char) -> bool {
    contains(&properties().digit, c)
}
pub(crate) struct Lexer<'a> {
    pub text: &'a str,
    pub source: Arc<str>,
    pub pos: usize,
    pub cached: Option<Token>,
}
impl<'a> Lexer<'a> {
    pub fn new(text: &'a str, source: &str, max_bytes: usize) -> Result<Self> {
        if text.len() > max_bytes {
            return Err(ParseError::resource(
                "input byte limit exceeded",
                Span {
                    source: source.into(),
                    start: 0,
                    end: text.len(),
                },
            ));
        }
        Ok(Self {
            text,
            source: source.into(),
            pos: 0,
            cached: None,
        })
    }
    pub fn span(&self, start: usize, end: usize) -> Span {
        Span {
            source: self.source.clone(),
            start,
            end,
        }
    }
    pub fn current(&self) -> Option<char> {
        self.text.get(self.pos..).and_then(|s| s.chars().next())
    }
    fn bump(&mut self) -> Option<char> {
        let c = self.current()?;
        self.pos += c.len_utf8();
        Some(c)
    }
    fn starts(&self, s: &str) -> bool {
        self.text.get(self.pos..).is_some_and(|t| t.starts_with(s))
    }
    pub fn fail(&self, message: impl Into<String>, at: usize) -> ParseError {
        let end = at
            + self
                .text
                .get(at..)
                .and_then(|s| s.chars().next())
                .map_or(0, char::len_utf8);
        ParseError::new(message, self.span(at, end.min(self.text.len())))
    }
    fn skip(&mut self) -> Result<()> {
        loop {
            if self.current().is_some_and(ken_text::unicode::whitespace) {
                self.bump();
            } else if self.starts("//") {
                self.pos = self.text[self.pos..]
                    .find('\n')
                    .map_or(self.text.len(), |n| self.pos + n + 1);
            } else if self.starts("/*") {
                let Some(end) = self.text[self.pos + 2..].find("*/") else {
                    return Err(self.fail("unterminated comment", self.pos));
                };
                self.pos += end + 4;
            } else {
                return Ok(());
            }
        }
    }
    pub fn peek(&mut self) -> Result<&Token> {
        if self.cached.is_none() {
            let t = self.read()?;
            self.cached = Some(t);
        }
        Ok(self.cached.as_ref().unwrap())
    }
    pub fn take(&mut self) -> Result<Token> {
        self.peek()?;
        Ok(self.cached.take().unwrap())
    }
    fn ident_end(&self, start: usize) -> Option<usize> {
        let bytes = self.text.as_bytes();
        let &first = bytes.get(start)?;
        if !(first.is_ascii_alphabetic() || first == b'_') {
            return None;
        }
        let mut end = start + 1;
        while bytes
            .get(end)
            .is_some_and(|c| c.is_ascii_alphanumeric() || *c == b'_')
        {
            end += 1;
        }
        Some(end)
    }
    fn number_end(&self, start: usize) -> usize {
        let b = self.text.as_bytes();
        let mut end = start + 1;
        if b[start] != b'0' {
            while b.get(end).is_some_and(u8::is_ascii_digit) {
                end += 1;
            }
        }
        if b.get(end) == Some(&b'.') && b.get(end + 1).is_some_and(u8::is_ascii_digit) {
            end += 2;
            while b.get(end).is_some_and(u8::is_ascii_digit) {
                end += 1;
            }
        }
        if b.get(end).is_some_and(|c| matches!(c, b'e' | b'E')) {
            let mut next = end + 1;
            if b.get(next).is_some_and(|c| matches!(c, b'+' | b'-')) {
                next += 1;
            }
            if b.get(next).is_some_and(u8::is_ascii_digit) {
                end = next + 1;
                while b.get(end).is_some_and(u8::is_ascii_digit) {
                    end += 1;
                }
            }
        }
        end
    }
    fn read(&mut self) -> Result<Token> {
        self.skip()?;
        let start = self.pos;
        let Some(c) = self.current() else {
            return Ok(Token {
                kind: "EOF",
                text: String::new(),
                span: self.span(start, start),
            });
        };
        let kind;
        if c == '"' {
            self.bump();
            loop {
                let Some(c) = self.bump() else {
                    return Err(self.fail("unterminated string", start));
                };
                if c == '\\' {
                    if self.bump().is_none() {
                        return Err(self.fail("unterminated string", start));
                    }
                } else if c == '"' {
                    break;
                }
            }
            if serde_json::from_str::<String>(&self.text[start..self.pos]).is_err() {
                return Err(ParseError::new(
                    "invalid JSON string",
                    self.span(start, self.pos),
                ));
            }
            kind = "STRING";
        } else if c == '$' {
            let Some(end) = self.ident_end(start + 1) else {
                return Err(self.fail("expected role name", start));
            };
            self.pos = end;
            kind = "ROLE";
        } else if c.is_ascii_digit() {
            self.pos = self.number_end(start);
            kind = if self.text[start..self.pos].contains(['.', 'e', 'E']) {
                "FLOAT"
            } else {
                "INTEGER"
            };
        } else if let Some(end) = self.ident_end(start) {
            self.pos = end;
            kind = "IDENT";
        } else {
            let op = [
                "...", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "++", "--", "**", "->",
            ]
            .into_iter()
            .find(|op| self.starts(op));
            if let Some(op) = op {
                self.pos += op.len();
            } else if "{}()[];,:.|&^~+-*/%<>=_".contains(c) {
                self.bump();
            } else {
                return Err(self.fail(
                    format!(
                        "unexpected character {}",
                        ken_program::value::string_repr(&c.to_string().as_str().into())
                    ),
                    start,
                ));
            }
            kind = "SYMBOL";
        }
        Ok(Token {
            kind,
            text: self.text[start..self.pos].into(),
            span: self.span(start, self.pos),
        })
    }
    pub fn regex(&mut self) -> Result<Token> {
        let opening = self.take()?;
        if opening.text != "/" {
            return Err(ParseError::new("expected regular expression", opening.span));
        }
        let start = opening.span.start;
        let mut in_class = false;
        let pattern_end;
        loop {
            let Some(c) = self.bump() else {
                return Err(self.fail("unterminated regex", start));
            };
            match c {
                '\\' => {
                    let Some(next) = self.current() else {
                        return Err(self.fail("unterminated regex", start));
                    };
                    if digit(next) || matches!(next, 'g' | 'k') {
                        return Err(self.fail("regex backreferences are not supported", start));
                    }
                    self.bump();
                }
                '[' => in_class = true,
                ']' => in_class = false,
                '/' if !in_class => {
                    pattern_end = self.pos - 1;
                    break;
                }
                '\r' | '\n' => return Err(self.fail("newline in regex", start)),
                '(' if self.starts("?") && !self.starts("?:") => {
                    return Err(self.fail(
                        "regex extensions other than (?:...) are not supported",
                        start,
                    ));
                }
                _ => (),
            }
        }
        let pattern = &self.text[start + 1..pattern_end];
        if pattern.len() > 4096 {
            return Err(self.fail("regex byte limit exceeded", start));
        }
        let flags_start = self.pos;
        while self.current().is_some_and(alpha) {
            self.bump();
        }
        let flags = &self.text[flags_start..self.pos];
        let mut seen = std::collections::BTreeSet::new();
        if flags.chars().any(|c| !"ims".contains(c) || !seen.insert(c)) {
            return Err(self.fail("invalid or repeated regex flags", flags_start));
        }
        if let Err(message) = regex_syntax::validate(pattern) {
            return Err(ParseError::new(
                format!("invalid regex: {message}"),
                opening.span,
            ));
        }
        Ok(Token {
            kind: "REGEX",
            text: self.text[start..self.pos].into(),
            span: self.span(start, self.pos),
        })
    }
}
