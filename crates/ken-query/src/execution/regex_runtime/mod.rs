//! Native codepoint matching with explicit Python dialects and invocation budgets.
mod boundaries;
mod cache;
mod parser;
mod references;
mod unicode;
pub use cache::Cache;
mod vm;
use super::{ExecutionError, Result};
use ken_text::PythonText;
use std::{
    collections::BTreeMap,
    sync::Arc,
    time::{Duration, Instant},
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Dialect {
    Stdlib,
    Regex,
}
#[derive(Clone, Copy, Debug, Default)]
struct Flags {
    ignore: bool,
    multi: bool,
    dot: bool,
    verbose: bool,
    ascii: bool,
    full: bool,
    v1: bool,
    reverse: bool,
    word: bool,
}
#[derive(Clone, Debug)]
struct Node {
    kind: Kind,
    flags: Flags,
}
type N = Arc<Node>;
#[derive(Clone, Debug)]
enum Kind {
    Empty,
    Fail,
    Literal(Vec<u32>),
    Class(Set),
    Any,
    Anchor(Anchor),
    Sequence(Vec<N>),
    Alternate(Vec<N>),
    Repeat {
        node: N,
        min: u64,
        max: Option<u64>,
        lazy: bool,
    },
    Atomic(N),
    Capture(usize, N),
    Backref(usize),
    Look {
        node: N,
        positive: bool,
        behind: bool,
    },
    Conditional {
        group: usize,
        yes: N,
        no: N,
    },
    AssertionConditional {
        assertion: N,
        positive: bool,
        behind: bool,
        yes: N,
        no: N,
    },
    Call(usize),
    Fuzzy(N, Arc<Fuzzy>),
    Grapheme,
    Linebreak,
    Keep,
    Prune,
    Skip,
}
#[derive(Clone, Copy, Debug)]
enum Anchor {
    Start,
    End,
    AbsoluteStart,
    AbsoluteEnd,
    Word(bool),
    WordStart,
    WordEnd,
    SearchStart,
}
#[derive(Clone, Debug)]
enum Set {
    Char(u32),
    Range(u32, u32),
    Class(Class),
    Property(u32),
    Union(Vec<Set>),
    Not(Box<Set>),
    And(Box<Set>, Box<Set>),
    Difference(Box<Set>, Box<Set>),
    Xor(Box<Set>, Box<Set>),
}
#[derive(Clone, Copy, Debug)]
enum Class {
    Word,
    Digit,
    Space,
}
#[derive(Clone, Debug)]
struct Fuzzy {
    minimum: [u32; 4],
    maximum: [u32; 4],
    cost: [u32; 3],
    max_cost: u32,
    test: Option<Set>,
}
fn node(kind: Kind, flags: Flags) -> N {
    Arc::new(Node { kind, flags })
}
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(format!("invalid regular expression: {}", message.into()))
}
#[derive(Clone, Debug)]
pub struct Pattern {
    root: N,
    groups: Vec<Option<N>>,
    dialect: Dialect,
    flags: Flags,
}
impl Pattern {
    pub fn compile(
        pattern: &str,
        flags: &str,
        dialect: Dialect,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        check()?;
        if pattern.len() > 2_000_000 {
            return Err(ExecutionError::Exhausted("regex_pattern"));
        }
        let mut seen = std::collections::BTreeSet::new();
        let mut options = Flags::default();
        for flag in flags.chars() {
            if !seen.insert(flag) {
                return Err(invalid("repeated regex flag"));
            }
            match flag {
                'i' => options.ignore = true,
                'm' => options.multi = true,
                's' => options.dot = true,
                _ => return Err(invalid("invalid regex flag")),
            }
        }
        unicode::initialize();
        check()?;
        parser::compile(pattern, options, dialect, check)
    }
    /// Python strings can contain isolated surrogate codepoints in patterns too.
    /// Encode only those literals as equivalent Unicode escapes before syntax
    /// parsing; valid scalar characters and all operators retain their spelling.
    pub fn compile_text(
        pattern: &PythonText,
        flags: &str,
        dialect: Dialect,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        check()?;
        let mut raw = String::new();
        let mut slashes = 0usize;
        for cp in pattern.codepoints() {
            check()?;
            if (0xd800..=0xdfff).contains(cp) {
                if slashes % 2 == 1 {
                    raw.pop();
                }
                raw.push_str(&format!("\\u{cp:04x}"));
                slashes = 0;
            } else {
                let c = char::from_u32(*cp).ok_or_else(|| invalid("invalid codepoint"))?;
                raw.push(c);
                slashes = if c == '\\' { slashes + 1 } else { 0 };
            }
        }
        Self::compile(&raw, flags, dialect, check)
    }
    pub fn is_match(
        &self,
        text: &PythonText,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<bool> {
        self.is_match_with_timeout(text, Some(Duration::from_millis(50)), check)
    }
    /// A context may impose its own subdeadline or rely on the caller budget.
    /// The native expansion ceiling and cooperative checks always remain active.
    pub fn is_match_with_timeout(
        &self,
        text: &PythonText,
        timeout: Option<Duration>,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<bool> {
        check()?;
        let mut control = Control {
            check,
            started: Instant::now(),
            steps: 0,
            timeout,
        };
        vm::search(self, text.codepoints(), &mut control)
    }
}
struct Control<'a> {
    check: &'a mut dyn FnMut() -> Result<()>,
    started: Instant,
    steps: u64,
    timeout: Option<Duration>,
}
impl Control<'_> {
    fn poll(&mut self) -> Result<()> {
        (self.check)()?;
        self.steps += 1;
        if self.steps > 10_000_000
            || self
                .timeout
                .is_some_and(|limit| self.started.elapsed() >= limit)
        {
            return Err(ExecutionError::Exhausted("regex_timeout"));
        }
        Ok(())
    }
}
