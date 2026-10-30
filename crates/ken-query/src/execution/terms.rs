//! Typed endpoint binding and the original asymmetric attribute comparisons.
use super::regex_runtime::{Cache, Dialect};
use super::{ExecutionError, Result};
use crate::relational::Term;
use ken_program::value::GraphValue;
use ken_text::PythonText;
use std::collections::BTreeMap;
use std::time::Duration;
pub(super) type Bindings = BTreeMap<String, String>;
pub(super) fn variable(t: &Term) -> bool {
    matches!(t,Term::Text(s)if s.starts_with('$'))
}
pub(super) fn resolve(t: &Term, b: &Bindings) -> Option<String> {
    match t {
        Term::Literal(v) => Some(v.literal.clone()),
        Term::Text(s) if s == "_" => None,
        Term::Text(s) if s.starts_with('$') => b.get(s).cloned(),
        Term::Text(s) if !s.contains('|') => Some(s.clone()),
        _ => None,
    }
}
pub(super) fn bind(t: &Term, v: &str, b: &mut Bindings) -> bool {
    match t {
        Term::Literal(q) => q.literal == v,
        Term::Text(s) if s == "_" => true,
        Term::Text(s) if s.starts_with('$') => {
            if let Some(old) = b.get(s) {
                old == v
            } else {
                b.insert(s.clone(), v.into());
                true
            }
        }
        Term::Text(s) => s.split('|').any(|x| x == v),
    }
}
pub(super) fn spelling(v: &GraphValue, actual: bool) -> String {
    if actual {
        v.comparison()
    } else {
        v.string().unwrap_or_else(|| v.repr())
    }
}
#[derive(Default)]
pub(crate) struct Comparisons {
    patterns: Cache,
    interruption: super::Interruption,
}
impl Comparisons {
    pub fn check(&self) -> Result<()> {
        self.interruption.check()
    }
    pub fn interruption(&self) -> super::Interruption {
        self.interruption.clone()
    }
    pub fn new(interruption: super::Interruption) -> Self {
        Self {
            patterns: Cache::default(),
            interruption,
        }
    }
    pub fn prepare(&mut self, pattern: &str) -> Result<()> {
        let interruption = self.interruption.clone();
        self.patterns
            .compile(&pattern.into(), "", Dialect::Regex, &mut || {
                interruption.check()
            })
            .map(|_| ())
    }
    fn regex(
        &mut self,
        actual: &GraphValue,
        pattern: &str,
        timeout: Option<Duration>,
    ) -> Result<bool> {
        let interruption = self.interruption.clone();
        let pattern = self
            .patterns
            .compile(&pattern.into(), "", Dialect::Regex, &mut || {
                interruption.check()
            })?;
        let text = match actual {
            GraphValue::String(text) => text.clone(),
            _ => PythonText::from(spelling(actual, true)),
        };
        pattern.is_match_with_timeout(&text, timeout, &mut || interruption.check())
    }
    /// SourceExecutor regex callbacks rely on their enclosing query deadline.
    pub fn compare_source(
        &mut self,
        actual: &GraphValue,
        op: &str,
        expected: &str,
    ) -> Result<bool> {
        self.check()?;
        if op == "regex" {
            if matches!(actual, GraphValue::Null) {
                return Ok(false);
            }
            return self.regex(actual, expected, None);
        }
        self.compare(actual, op, expected)
    }

    pub fn compare(&mut self, actual: &GraphValue, op: &str, expected: &str) -> Result<bool> {
        self.interruption.check()?;
        if matches!(actual, GraphValue::Null) {
            return Ok(false);
        }
        if matches!(op, "<" | ">" | "<=" | ">=") {
            let a = super::numbers::actual(actual)?;
            let b = super::numbers::parse(expected);
            return Ok(match (a, b) {
                (Some(a), Some(b)) => match op {
                    "<" => a < b,
                    ">" => a > b,
                    "<=" => a <= b,
                    _ => a >= b,
                },
                _ => false,
            });
        }
        if op == "regex" {
            return self.regex(actual, expected, Some(Duration::from_millis(10)));
        }
        let value = spelling(actual, true);
        Ok(match op {
            "literal" => value == expected,
            "not_literal" => value != expected,
            "~=" => glob(&value, expected, &self.interruption)?,
            "!=" => !expected.split('|').any(|v| v == value),
            "=" | "==" => expected.split('|').any(|v| v == value),
            _ => {
                return Err(ExecutionError::Invalid(format!(
                    "unsupported comparison {op}"
                )));
            }
        })
    }
}
// fnmatchcase semantics: star/question/class (including ! and ranges), case-sensitive.
fn glob(text: &str, pattern: &str, check: &super::Interruption) -> Result<bool> {
    let t: Vec<_> = text.chars().collect();
    let p: Vec<_> = pattern.chars().collect();
    let mut previous = vec![false; t.len() + 1];
    previous[0] = true;
    let mut i = 0;
    while i < p.len() {
        check.check()?;
        let c = p[i];
        i += 1;
        if c == '*' {
            for n in 1..=t.len() {
                if n % 1024 == 0 {
                    check.check()?;
                }
                previous[n] |= previous[n - 1];
            }
            continue;
        }
        let mut class = None;
        if c == '[' {
            let begin = i;
            let mut end = i + usize::from(p.get(i) == Some(&'!'));
            if p.get(end) == Some(&']') {
                end += 1;
            }
            while end < p.len() && p[end] != ']' {
                end += 1;
            }
            if end < p.len() {
                class = Some(&p[begin..end]);
                i = end + 1;
            }
        }
        for n in (1..=t.len()).rev() {
            if n % 1024 == 0 {
                check.check()?;
            }
            let matches = if let Some(items) = class {
                let negate = items.first() == Some(&'!');
                let mut k = usize::from(negate);
                let mut hit = false;
                while k < items.len() {
                    if k + 2 < items.len() && items[k + 1] == '-' {
                        hit |= items[k] <= t[n - 1] && t[n - 1] <= items[k + 2];
                        k += 3;
                    } else {
                        hit |= items[k] == t[n - 1];
                        k += 1;
                    }
                }
                hit != negate
            } else {
                c == '?' || c == t[n - 1]
            };
            previous[n] = previous[n - 1] && matches;
        }
        previous[0] = false;
    }
    Ok(previous[t.len()])
}
