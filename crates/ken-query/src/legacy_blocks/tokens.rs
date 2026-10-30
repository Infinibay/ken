//! Frozen Python lexical classes shared by the two unversioned query grammars.
use super::{Result, invalid, py};
#[derive(Clone, Copy, PartialEq)]
pub(crate) enum Grammar {
    Blocks,
    Selectors,
}
#[derive(Clone)]
pub(crate) struct Token {
    pub text: String,
    pub kind: &'static str,
}
pub(crate) struct Tokens {
    pub tokens: Vec<Token>,
    pub at: usize,
    pub grammar: Grammar,
}
impl Tokens {
    pub fn new(source: &str, grammar: Grammar) -> Result<Self> {
        if source.len() > 2_000_000 {
            return Err(invalid("legacy query source exceeds byte limit"));
        }
        let mut tokens = vec![];
        let mut at = 0;
        while at < source.len() {
            let begin = at;
            while source[at..]
                .chars()
                .next()
                .is_some_and(ken_text::unicode::whitespace)
            {
                at += source[at..].chars().next().unwrap().len_utf8();
            }
            if at == source.len() {
                break;
            }
            let rest = &source[at..];
            let first = rest.chars().next().unwrap();
            if first == '#' {
                at += rest.find('\n').unwrap_or(rest.len());
                continue;
            }
            let mut length = 0;
            let kind;
            if first == '"' || grammar == Grammar::Selectors && first == '\'' {
                let quote = first;
                let mut chars = rest.char_indices();
                chars.next();
                while let Some((i, c)) = chars.next() {
                    if c == '\\' {
                        let Some((_, escaped)) = chars.next() else {
                            break;
                        };
                        if escaped == '\n' {
                            break;
                        }
                    } else if c == quote {
                        length = i + c.len_utf8();
                        break;
                    }
                }
                kind = "string";
            } else if first == '/' {
                let mut chars = rest.char_indices();
                chars.next();
                while let Some((i, c)) = chars.next() {
                    if c == '\n' {
                        break;
                    }
                    if c == '\\' {
                        if chars.next().is_none_or(|(_, c)| c == '\n') {
                            break;
                        }
                    } else if c == '/' {
                        length = i + 1;
                        while matches!(rest.as_bytes().get(length), Some(b'i' | b'm' | b's')) {
                            length += 1;
                        }
                        break;
                    }
                }
                kind = "regex";
            } else if grammar == Grammar::Selectors {
                if first == '@'
                    || first == '$'
                    || ken_text::unicode::word(first)
                    || matches!(first, '.' | '-')
                {
                    let prefix = usize::from(first == '@' || first == '$');
                    length = prefix;
                    for (c_at, c) in rest[prefix..].char_indices() {
                        if ken_text::unicode::word(c) || matches!(c, '.' | '-') {
                            length = prefix + c_at + c.len_utf8();
                        } else {
                            break;
                        }
                    }
                    if length == prefix {
                        length = 0;
                    }
                    kind = "word";
                } else {
                    kind = "symbol";
                    if "(){}[]:,;*".contains(first) {
                        length = first.len_utf8();
                    }
                }
            } else if first == '$' {
                length = 1;
                for (c_at, c) in rest[1..].char_indices() {
                    if ken_text::unicode::word(c) {
                        length = c_at + 1 + c.len_utf8();
                    } else {
                        break;
                    }
                }
                if length == 1 {
                    length = 0;
                } else if rest.as_bytes().get(length) == Some(&b'.') {
                    let dot = length;
                    length += 1;
                    let start = length;
                    for (c_at, c) in rest[start..].char_indices() {
                        if ken_text::unicode::word(c) {
                            length = start + c_at + c.len_utf8();
                        } else {
                            break;
                        }
                    }
                    if length == start {
                        length = dot;
                    }
                }
                kind = "word";
            } else if first.is_ascii_alphabetic() || first == '_' {
                for (c_at, c) in rest.char_indices() {
                    if ken_text::unicode::word(c) || matches!(c, '.' | '-') {
                        length = c_at + c.len_utf8();
                    } else {
                        break;
                    }
                }
                kind = "word";
            } else if first.is_ascii_digit() {
                length = rest.bytes().take_while(u8::is_ascii_digit).count();
                kind = "word";
            } else {
                kind = "symbol";
                if [">=", "<=", "==", "!="].iter().any(|s| rest.starts_with(s)) {
                    length = 2;
                } else if "{}():,;[]*=<>".contains(first) {
                    length = first.len_utf8();
                }
            }
            if length == 0 {
                return Err(invalid(if grammar == Grammar::Blocks {
                    format!(
                        "KenQL line {}: invalid token near {}",
                        source[..begin].chars().filter(|c| *c == '\n').count() + 1,
                        py(&source[begin..].chars().take(32).collect::<String>())
                    )
                } else {
                    format!(
                        "invalid selector syntax near {}",
                        py(&source[begin..].chars().take(40).collect::<String>())
                    )
                }));
            }
            tokens.push(Token {
                text: rest[..length].into(),
                kind,
            });
            if tokens.len() > 65536 {
                return Err(invalid("legacy query token limit exceeded"));
            }
            at += length;
        }
        Ok(Self {
            tokens,
            at: 0,
            grammar,
        })
    }
    pub fn peek(&self, text: &str) -> bool {
        self.tokens.get(self.at).is_some_and(|t| t.text == text)
    }
    pub fn take(&mut self, expected: Option<&str>) -> Result<String> {
        let Some(token) = self.tokens.get(self.at) else {
            return Err(invalid(if self.grammar == Grammar::Blocks {
                format!(
                    "KenQL: expected {}, reached end",
                    expected.unwrap_or("token")
                )
            } else {
                format!(
                    "expected {}, reached end of query",
                    expected.unwrap_or("token")
                )
            }));
        };
        let text = token.text.clone();
        self.at += 1;
        if expected.is_some_and(|e| e != text) {
            return Err(invalid(if self.grammar == Grammar::Blocks {
                format!(
                    "KenQL: expected {}, got {}",
                    py(expected.unwrap()),
                    py(&text)
                )
            } else {
                format!("expected {}, got {}", py(expected.unwrap()), py(&text))
            }));
        }
        Ok(text)
    }
    pub fn expect(&mut self, text: &str) -> Result<()> {
        self.take(Some(text)).map(|_| ())
    }
    pub fn next(&mut self) -> Result<String> {
        self.take(None)
    }
    pub fn variable(&mut self) -> Result<String> {
        let token = self.next()?;
        if token.starts_with('$') {
            Ok(token)
        } else {
            Err(invalid(format!("expected bound role, got {token}")))
        }
    }
}
