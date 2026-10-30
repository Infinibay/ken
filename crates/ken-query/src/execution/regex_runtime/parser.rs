//! Symbolic pattern parser. Repetitions never expand into repeated instructions.
use super::*;
pub(super) fn compile(
    pattern: &str,
    mut flags: Flags,
    dialect: Dialect,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<Pattern> {
    // Regex global versions/direction discovered in a scoped group apply to the
    // entire pattern. Reparse once with those globals, as the source compiler does.
    loop {
        let mut parser = Parser {
            text: pattern.chars().collect(),
            at: 0,
            flags,
            dialect,
            groups: vec![None],
            names: BTreeMap::new(),
            references: vec![],
            calls: vec![],
            definitions: BTreeMap::new(),
            global_allowed: true,
            unresolved: BTreeMap::new(),
            open: vec![],
            version: None,
            reverse: flags.reverse,
            depth: 0,
            work: 0,
            check: &mut *check,
        };
        let mut root = parser.alternatives(false)?;
        parser.skip();
        if parser.at < parser.text.len() {
            return Err(parser.error("unbalanced parenthesis"));
        }
        let requested = parser.version.unwrap_or(flags.v1);
        if requested != flags.v1 || parser.reverse != flags.reverse {
            flags.v1 = requested;
            flags.full = requested;
            flags.reverse = parser.reverse;
            continue;
        }
        let resolved = parser
            .unresolved
            .iter()
            .map(|(id, name)| {
                parser
                    .names
                    .get(name)
                    .copied()
                    .map(|target| (*id, target))
                    .ok_or_else(|| parser.error("unknown group reference"))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        for id in parser.references.iter().chain(&parser.calls) {
            let id = resolved.get(id).unwrap_or(id);
            if *id >= parser.groups.len() {
                return Err(parser.error("invalid group reference"));
            }
        }
        for id in &parser.calls {
            let id = resolved.get(id).unwrap_or(id);
            if parser.definitions.get(id).copied().unwrap_or(0) > 1 {
                return Err(parser.error("ambiguous group reference"));
            }
        }
        references::resolve(&mut root, &resolved, parser.check)?;
        for group in parser.groups.iter_mut().flatten() {
            references::resolve(group, &resolved, parser.check)?;
        }
        parser.groups[0] = Some(root.clone());
        return Ok(Pattern {
            root,
            groups: parser.groups,
            dialect,
            flags: parser.flags,
        });
    }
}
struct Parser<'a> {
    text: Vec<char>,
    at: usize,
    flags: Flags,
    dialect: Dialect,
    groups: Vec<Option<N>>,
    names: BTreeMap<String, usize>,
    references: Vec<usize>,
    calls: Vec<usize>,
    definitions: BTreeMap<usize, usize>,
    global_allowed: bool,
    unresolved: BTreeMap<usize, String>,
    open: Vec<usize>,
    version: Option<bool>,
    reverse: bool,
    depth: usize,
    work: usize,
    check: &'a mut dyn FnMut() -> Result<()>,
}
impl Parser<'_> {
    fn poll(&mut self) -> Result<()> {
        (self.check)()?;
        self.work += 1;
        if self.work > 1_000_000 {
            return Err(ExecutionError::Exhausted("regex_pattern"));
        }
        Ok(())
    }
    fn restore(&mut self, mut flags: Flags) {
        if self.version == Some(true) && !flags.v1 {
            flags.v1 = true;
            flags.full = true;
        }
        if self.version == Some(false) {
            flags.v1 = false;
        }
        flags.reverse = self.reverse;
        self.flags = flags;
    }
    fn error(&self, message: &str) -> ExecutionError {
        invalid(format!("{message} at position {}", self.at))
    }
    fn peek(&self) -> Option<char> {
        self.text.get(self.at).copied()
    }
    fn take(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.at += 1;
        Some(c)
    }
    fn eat(&mut self, c: char) -> bool {
        if self.peek() == Some(c) {
            self.at += 1;
            true
        } else {
            false
        }
    }
    fn starts(&self, s: &str) -> bool {
        self.text[self.at..]
            .iter()
            .copied()
            .zip(s.chars())
            .all(|(a, b)| a == b)
            && self.text.len() - self.at >= s.chars().count()
    }
    fn accept(&mut self, s: &str) -> bool {
        if self.starts(s) {
            self.at += s.chars().count();
            true
        } else {
            false
        }
    }
    fn require(&mut self, c: char) -> Result<()> {
        if self.eat(c) {
            Ok(())
        } else {
            Err(self.error(&format!("expected {c}")))
        }
    }
    fn skip(&mut self) {
        if self.flags.verbose {
            loop {
                while self.peek().is_some_and(char::is_whitespace) {
                    self.at += 1;
                }
                if self.eat('#') {
                    while self.peek().is_some_and(|c| c != '\n') {
                        self.at += 1;
                    }
                } else {
                    break;
                }
            }
        }
    }
    fn alternatives(&mut self, reset: bool) -> Result<N> {
        crate::with_stack(|| {
            self.poll()?;
            self.depth += 1;
            if self.depth > 256 {
                return Err(ExecutionError::Exhausted("regex_pattern"));
            }
            let base = self.groups.len();
            let mut maximum = base;
            let mut arms = vec![];
            loop {
                if reset {
                    self.groups.truncate(base);
                }
                arms.push(self.sequence()?);
                maximum = maximum.max(self.groups.len());
                if !self.eat('|') {
                    break;
                }
                self.global_allowed = false;
            }
            if reset {
                self.groups.resize(maximum, None);
            }
            self.depth -= 1;
            Ok(if arms.len() == 1 {
                arms.remove(0)
            } else {
                node(Kind::Alternate(arms), self.flags)
            })
        })
    }
    fn sequence(&mut self) -> Result<N> {
        let mut parts: Vec<N> = vec![];
        loop {
            self.skip();
            if matches!(self.peek(), None | Some(')' | '|')) {
                break;
            }
            let atom = self.atom()?;
            let atom = self.repetition(atom)?;
            if let Kind::Empty = &atom.kind {
                continue;
            }
            if let Some(last) = parts.last_mut()
                && same_flags(last.flags, atom.flags)
                && let (Kind::Literal(a), Kind::Literal(b)) =
                    (&mut Arc::make_mut(last).kind, &atom.kind)
            {
                a.extend(b);
                continue;
            }
            parts.push(atom);
        }
        Ok(if parts.len() == 1 {
            parts.remove(0)
        } else if parts.is_empty() {
            node(Kind::Empty, self.flags)
        } else {
            node(Kind::Sequence(parts), self.flags)
        })
    }
    fn atom(&mut self) -> Result<N> {
        self.poll()?;
        let flags = self.flags;
        let allowed = self.global_allowed;
        self.global_allowed = false;
        let c = self
            .take()
            .ok_or_else(|| self.error("missing expression"))?;
        Ok(match c {
            '(' => return self.group(allowed),
            '[' => {
                let set = self.set_body()?;
                self.class_node(set, flags)?
            }
            '.' => node(Kind::Any, flags),
            '^' => node(Kind::Anchor(Anchor::Start), flags),
            '$' => node(Kind::Anchor(Anchor::End), flags),
            '\\' => return self.escape(false),
            '*' | '+' | '?' => return Err(self.error("nothing to repeat")),
            other => node(Kind::Literal(vec![other as u32]), flags),
        })
    }
    fn class_node(&mut self, set: Set, flags: Flags) -> Result<N> {
        let expansions = unicode::expansions(&set, flags, self.dialect, self.check)?;
        let base = node(Kind::Class(set), flags);
        if expansions.is_empty() {
            return Ok(base);
        }
        let mut alternatives = vec![base];
        alternatives.extend(
            expansions
                .into_iter()
                .map(|values| node(Kind::Literal(values), flags)),
        );
        Ok(node(Kind::Alternate(alternatives), flags))
    }
    fn group(&mut self, allowed: bool) -> Result<N> {
        let flags = self.flags;
        if self.eat('*') {
            if self.dialect == Dialect::Stdlib {
                return Err(self.error("nothing to repeat"));
            }
            let verb = self.until(')')?;
            return Ok(node(
                match verb.as_str() {
                    "FAIL" | "F" => Kind::Fail,
                    "PRUNE" => Kind::Prune,
                    "SKIP" => Kind::Skip,
                    _ => return Err(self.error("unknown verb")),
                },
                flags,
            ));
        }
        if !self.eat('?') {
            let id = self.groups.len();
            self.groups.push(None);
            *self.definitions.entry(id).or_default() += 1;
            self.open.push(id);
            let child = self.alternatives(false)?;
            self.require(')')?;
            self.open.pop();
            self.restore(flags);
            self.groups[id] = Some(child.clone());
            return Ok(node(Kind::Capture(id, child), flags));
        }
        if self.eat('#') {
            self.global_allowed = allowed;
            while let Some(c) = self.peek() {
                if c == ')' {
                    break;
                }
                self.at += 1;
                if c == '\\' && self.peek().is_some() {
                    self.at += 1;
                }
            }
            self.require(')')?;
            return Ok(node(Kind::Empty, flags));
        }
        if self.eat(':') {
            let child = self.alternatives(false)?;
            self.require(')')?;
            self.restore(flags);
            return Ok(child);
        }
        if self.eat('>') {
            let child = self.alternatives(false)?;
            self.require(')')?;
            self.restore(flags);
            return Ok(node(Kind::Atomic(child), flags));
        }
        if self.eat('|') {
            if self.dialect == Dialect::Stdlib {
                return Err(self.error("unknown extension"));
            }
            let child = self.alternatives(true)?;
            self.require(')')?;
            self.restore(flags);
            return Ok(child);
        }
        if self.eat('=') || self.eat('!') {
            let positive = self.text[self.at - 1] == '=';
            let child = self.alternatives(false)?;
            self.require(')')?;
            self.restore(flags);
            return Ok(node(
                Kind::Look {
                    node: child,
                    positive,
                    behind: false,
                },
                flags,
            ));
        }
        if self.eat('<') {
            if self.eat('=') || self.eat('!') {
                let positive = self.text[self.at - 1] == '=';
                let child = self.alternatives(false)?;
                self.require(')')?;
                self.restore(flags);
                if self.dialect == Dialect::Stdlib
                    && references::width(&child, &self.groups, 0).is_none()
                {
                    return Err(self.error("look-behind requires fixed-width pattern"));
                }
                return Ok(node(
                    Kind::Look {
                        node: child,
                        positive,
                        behind: true,
                    },
                    flags,
                ));
            }
            if self.dialect == Dialect::Stdlib {
                return Err(self.error("unknown extension"));
            }
            let name = self.until('>')?;
            return self.named_group(name, flags);
        }
        if self.eat('P') {
            if self.eat('<') {
                let name = self.until('>')?;
                return self.named_group(name, flags);
            }
            if self.eat('=') {
                let name = self.until(')')?;
                if self.dialect == Dialect::Stdlib && !ken_text::unicode::identifier(&name) {
                    return Err(self.error("bad group name"));
                }
                let id = self.reference(&name)?;
                return Ok(node(Kind::Backref(id), flags));
            }
            if self.dialect == Dialect::Regex && (self.eat('>') || self.eat('&')) {
                let name = self.until(')')?;
                let id = self.group_id(&name)?;
                self.calls.push(id);
                return Ok(node(Kind::Call(id), flags));
            }
            return Err(self.error("unknown extension"));
        }
        if self.dialect == Dialect::Regex && self.eat('&') {
            let name = self.until(')')?;
            let id = self.group_id(&name)?;
            self.calls.push(id);
            return Ok(node(Kind::Call(id), flags));
        }
        if self.dialect == Dialect::Regex && self.eat('R') {
            self.require(')')?;
            self.calls.push(0);
            return Ok(node(Kind::Call(0), flags));
        }
        if self.peek().is_some_and(|c| c.is_ascii_digit()) && self.dialect == Dialect::Regex {
            let id = self
                .number()?
                .ok_or_else(|| self.error("invalid group call"))? as usize;
            self.require(')')?;
            self.calls.push(id);
            return Ok(node(Kind::Call(id), flags));
        }
        if self.dialect == Dialect::Regex
            && matches!(self.peek(), Some('+' | '-'))
            && self.text.get(self.at + 1).is_some_and(char::is_ascii_digit)
        {
            let plus = self.take() == Some('+');
            let offset = self
                .number()?
                .ok_or_else(|| self.error("invalid relative group number"))?;
            let count = self.groups.len() - 1;
            let id = if plus {
                (count as u64).checked_add(offset)
            } else {
                (count as u64 + 1).checked_sub(offset)
            }
            .filter(|id| *id > 0)
            .and_then(|id| usize::try_from(id).ok())
            .ok_or_else(|| self.error("invalid relative group number"))?;
            self.require(')')?;
            self.calls.push(id);
            return Ok(node(Kind::Call(id), flags));
        }
        if self.eat('(') {
            if self.peek() == Some('?') && self.dialect == Dialect::Regex {
                self.at += 1;
                let behind = self.eat('<');
                let positive = if self.eat('=') {
                    true
                } else if self.eat('!') {
                    false
                } else {
                    return Err(self.error("expected lookaround conditional"));
                };
                let assertion = self.alternatives(false)?;
                self.require(')')?;
                self.restore(flags);
                let yes = self.sequence()?;
                let no = if self.eat('|') {
                    self.sequence()?
                } else {
                    node(Kind::Empty, flags)
                };
                self.require(')')?;
                self.restore(flags);
                return Ok(node(
                    Kind::AssertionConditional {
                        assertion,
                        positive,
                        behind,
                        yes,
                        no,
                    },
                    flags,
                ));
            }
            let name = self.until(')')?;
            let group = self.group_id(&name)?;
            self.references.push(group);
            let yes = self.sequence()?;
            let no = if self.eat('|') {
                self.sequence()?
            } else {
                node(Kind::Empty, flags)
            };
            self.require(')')?;
            self.restore(flags);
            return Ok(node(Kind::Conditional { group, yes, no }, flags));
        }
        let mut subtract = false;
        let mut any = false;
        let mut encoding = None;
        let mut on = std::collections::BTreeSet::new();
        let mut off = std::collections::BTreeSet::new();
        while let Some(c) = self.peek() {
            if c == ':' || c == ')' {
                break;
            }
            self.at += 1;
            if c == '-' {
                subtract = true;
                continue;
            }
            let value = !subtract;
            any = true;
            if value {
                on.insert(c);
            } else {
                off.insert(c);
            }
            if on.contains(&c) && off.contains(&c) {
                return Err(self.error("flag turned on and off"));
            }
            if !value
                && (self.dialect == Dialect::Stdlib && matches!(c, 'a' | 'u' | 'L')
                    || self.dialect == Dialect::Regex && matches!(c, 'b' | 'e' | 'p' | 'r' | 'V'))
            {
                return Err(self.error("cannot turn off global or encoding flag"));
            }
            if matches!(c, 'a' | 'u' | 'L') && value {
                if encoding.is_some_and(|old| old != c) {
                    return Err(self.error("ASCII and UNICODE flags are incompatible"));
                }
                encoding = Some(c);
            }
            match c {
                'i' => self.flags.ignore = value,
                'm' => self.flags.multi = value,
                's' => self.flags.dot = value,
                'x' => self.flags.verbose = value,
                'a' => self.flags.ascii = value,
                'u' => self.flags.ascii = !value,
                'L' if self.dialect == Dialect::Regex => self.flags.ascii = value,
                'f' if self.dialect == Dialect::Regex => self.flags.full = value,
                'w' if self.dialect == Dialect::Regex => self.flags.word = value,
                'r' if self.dialect == Dialect::Regex => {
                    self.flags.reverse = value;
                    self.reverse = value;
                }
                'b' | 'e' | 'p' if self.dialect == Dialect::Regex => (),
                'V' if self.dialect == Dialect::Regex => {
                    let version = match self.take() {
                        Some('0') => false,
                        Some('1') => true,
                        _ => return Err(self.error("unknown regex version")),
                    };
                    if self.version.is_some_and(|old| old != version) {
                        return Err(self.error("conflicting regex versions"));
                    }
                    self.version = Some(version);
                    self.flags.v1 = version;
                    self.flags.full = version;
                }
                _ => return Err(self.error("unknown extension or flag")),
            }
        }
        if !any {
            return Err(self.error("unknown extension"));
        }
        if subtract && off.is_empty() {
            return Err(self.error("no flags after minus"));
        }
        if self.eat(':') {
            let child = self.alternatives(false)?;
            self.require(')')?;
            self.restore(flags);
            Ok(child)
        } else {
            if self.dialect == Dialect::Stdlib && (!allowed || self.depth != 1 || subtract) {
                return Err(self.error("global flags not at the start of the expression"));
            }
            self.require(')')?;
            self.global_allowed = allowed;
            Ok(node(Kind::Empty, self.flags))
        }
    }
    fn named_group(&mut self, name: String, flags: Flags) -> Result<N> {
        if !ken_text::unicode::identifier(&name) {
            return Err(self.error("bad group name"));
        }
        let id = if let Some(id) = self.names.get(&name) {
            if self.dialect == Dialect::Stdlib {
                return Err(self.error("redefinition of group name"));
            }
            *id
        } else {
            let id = self.groups.len();
            self.groups.push(None);
            self.names.insert(name, id);
            id
        };
        *self.definitions.entry(id).or_default() += 1;
        self.open.push(id);
        let child = self.alternatives(false)?;
        self.require(')')?;
        self.open.pop();
        self.restore(flags);
        self.groups[id] = Some(child.clone());
        Ok(node(Kind::Capture(id, child), flags))
    }
    fn group_id(&mut self, name: &str) -> Result<usize> {
        if let Ok(id) = name.parse() {
            return Ok(id);
        }
        if let Some(id) = self.names.get(name) {
            return Ok(*id);
        }
        if self.dialect == Dialect::Stdlib {
            return Err(self.error("unknown group reference"));
        }
        let id = usize::MAX - self.unresolved.len();
        self.unresolved.insert(id, name.to_owned());
        Ok(id)
    }
    fn reference(&mut self, name: &str) -> Result<usize> {
        let id = self.group_id(name)?;
        if id == 0
            || self.open.contains(&id)
            || self.dialect == Dialect::Stdlib && id >= self.groups.len()
        {
            return Err(self.error("cannot refer to an open or unknown group"));
        }
        self.references.push(id);
        Ok(id)
    }
    fn until(&mut self, end: char) -> Result<String> {
        let start = self.at;
        while self.peek().is_some_and(|c| c != end) {
            self.at += 1;
        }
        let text = self.text[start..self.at].iter().collect();
        self.require(end)?;
        Ok(text)
    }
    fn number(&mut self) -> Result<Option<u64>> {
        let start = self.at;
        let mut n = 0u64;
        while let Some(c) = self.peek().filter(|c| c.is_ascii_digit()) {
            self.at += 1;
            n = n
                .checked_mul(10)
                .and_then(|n| n.checked_add(c as u64 - '0' as u64))
                .ok_or_else(|| self.error("repeat count too big"))?;
        }
        Ok((self.at > start).then_some(n))
    }
    fn repetition(&mut self, atom: N) -> Result<N> {
        self.skip();
        let start = self.at;
        let mut counts = None;
        match self.peek() {
            Some('*') => {
                self.at += 1;
                counts = Some((0, None));
            }
            Some('+') => {
                self.at += 1;
                counts = Some((1, None));
            }
            Some('?') => {
                self.at += 1;
                counts = Some((0, Some(1)));
            }
            Some('{') => {
                self.at += 1;
                let min = self.number()?;
                let max = if self.eat(',') { self.number()? } else { min };
                if self.eat('}') && (min.is_some() || max.is_some()) {
                    counts = Some((min.unwrap_or(0), max));
                } else {
                    self.at = start;
                }
            }
            _ => (),
        }
        if let Some((min, max)) = counts {
            if min >= u32::MAX as u64 || max.is_some_and(|n| n >= u32::MAX as u64) {
                return Err(self.error("repeat count too big"));
            }
            if max.is_some_and(|n| n < min) {
                return Err(self.error("min repeat greater than max repeat"));
            }
            if self.dialect == Dialect::Stdlib && matches!(atom.kind, Kind::Anchor(_)) {
                return Err(self.error("nothing to repeat"));
            }
            let lazy = self.eat('?');
            let possessive = !lazy && self.eat('+');
            let repeat = node(
                Kind::Repeat {
                    node: atom,
                    min,
                    max,
                    lazy,
                },
                self.flags,
            );
            return Ok(if possessive {
                node(Kind::Atomic(repeat), self.flags)
            } else {
                repeat
            });
        }
        if self.dialect == Dialect::Regex
            && self.peek() == Some('{')
            && let Some(fuzzy) = self.fuzzy()?
        {
            return Ok(node(Kind::Fuzzy(atom, Arc::new(fuzzy)), self.flags));
        }
        Ok(atom)
    }
    fn escape(&mut self, in_set: bool) -> Result<N> {
        let c = self
            .take()
            .ok_or_else(|| self.error("bad escape (end of pattern)"))?;
        let flags = self.flags;
        let literal = match c {
            'a' => 7,
            'f' => 12,
            'n' => 10,
            'r' => 13,
            't' => 9,
            'v' => 11,
            'b' if in_set => 8,
            'x' | 'u' | 'U' => {
                let count = if c == 'x' {
                    2
                } else if c == 'u' {
                    4
                } else {
                    8
                };
                let mut value = 0u32;
                for _ in 0..count {
                    let d = self
                        .take()
                        .and_then(|c| c.to_digit(16))
                        .ok_or_else(|| self.error("incomplete escape"))?;
                    value = value
                        .checked_mul(16)
                        .and_then(|n| n.checked_add(d))
                        .ok_or_else(|| self.error("invalid Unicode escape"))?;
                }
                if value > 0x10ffff {
                    return Err(self.error("invalid Unicode escape"));
                }
                value
            }
            'N' => {
                let saved = self.at;
                if self.dialect == Dialect::Stdlib {
                    self.require('{')?;
                    let name = self.until('}')?;
                    unicode_names2::character(&name)
                        .filter(|c| crate::lexer::assigned(*c))
                        .map(u32::from)
                        .ok_or_else(|| self.error("undefined character name"))?
                } else {
                    let mut named = None;
                    if self.eat('{') {
                        let begin = self.at;
                        while self
                            .peek()
                            .is_some_and(|c| c.is_ascii_alphanumeric() || matches!(c, ' ' | '-'))
                        {
                            self.at += 1;
                        }
                        if self.eat('}') {
                            let name: String = self.text[begin..self.at - 1].iter().collect();
                            named = Some(
                                unicode_names2::character(&name)
                                    .filter(|c| crate::lexer::assigned(*c))
                                    .map(u32::from)
                                    .ok_or_else(|| self.error("undefined character name"))?,
                            );
                        }
                    }
                    if let Some(cp) = named {
                        cp
                    } else {
                        self.at = saved;
                        'N' as u32
                    }
                }
            }
            'd' | 'D' | 'w' | 'W' | 's' | 'S' => {
                let class = match c.to_ascii_lowercase() {
                    'd' => Class::Digit,
                    'w' => Class::Word,
                    _ => Class::Space,
                };
                let mut set = Set::Class(class);
                if c.is_uppercase() {
                    set = Set::Not(Box::new(set));
                }
                return Ok(node(Kind::Class(set), flags));
            }
            'p' | 'P' if self.dialect == Dialect::Regex => return self.property_escape(c, flags),
            'A' | 'Z' | 'z' | 'b' | 'B' | 'm' | 'M' | 'G' if !in_set => {
                let anchor = match c {
                    'A' => Anchor::AbsoluteStart,
                    'Z' => Anchor::AbsoluteEnd,
                    'z' if self.dialect == Dialect::Regex => Anchor::AbsoluteEnd,
                    'b' => Anchor::Word(true),
                    'B' => Anchor::Word(false),
                    'm' if self.dialect == Dialect::Regex => Anchor::WordStart,
                    'M' if self.dialect == Dialect::Regex => Anchor::WordEnd,
                    'G' if self.dialect == Dialect::Regex => Anchor::SearchStart,
                    _ => return Err(self.error("bad escape")),
                };
                return Ok(node(Kind::Anchor(anchor), flags));
            }
            'X' if !in_set && self.dialect == Dialect::Regex => {
                return Ok(node(Kind::Grapheme, flags));
            }
            'R' if !in_set && self.dialect == Dialect::Regex => {
                return Ok(node(Kind::Linebreak, flags));
            }
            'K' if !in_set && self.dialect == Dialect::Regex => return Ok(node(Kind::Keep, flags)),
            'g' if !in_set && self.dialect == Dialect::Regex => {
                let saved = self.at;
                if self.eat('<') {
                    let start = self.at;
                    while self.peek().is_some_and(|c| c != '>') {
                        self.at += 1;
                    }
                    let name: String = self.text[start..self.at].iter().collect();
                    if self.eat('>')
                        && !name.is_empty()
                        && name.chars().all(|c| c == '_' || c.is_alphanumeric())
                        && name != "0"
                    {
                        let id = self.reference(&name)?;
                        return Ok(node(Kind::Backref(id), flags));
                    }
                }
                self.at = saved;
                'g' as u32
            }
            '0'..='9' => {
                let mut digits = String::from(c);
                while digits.len() < 3
                    && self.peek().is_some_and(|d| {
                        if c == '0' || in_set {
                            matches!(d, '0'..='7')
                        } else {
                            d.is_ascii_digit()
                        }
                    })
                {
                    digits.push(self.take().unwrap());
                }
                if c == '0'
                    || in_set
                    || digits.len() == 3 && digits.chars().all(|c| matches!(c, '0'..='7'))
                {
                    if digits.chars().any(|c| !matches!(c, '0'..='7')) {
                        return Err(self.error("invalid octal escape"));
                    }
                    let value = u32::from_str_radix(&digits, 8)
                        .map_err(|_| self.error("invalid octal escape"))?;
                    if self.dialect == Dialect::Stdlib && value > 255 {
                        return Err(self.error("octal escape outside of range"));
                    }
                    if self.dialect == Dialect::Regex && flags.ascii && c != '0' && !in_set {
                        value & 255
                    } else {
                        value
                    }
                } else if in_set {
                    return Err(self.error("bad escape"));
                } else {
                    if digits.len() == 3 {
                        self.at -= 1;
                        digits.pop();
                    }
                    let id = self.reference(&digits)?;
                    return Ok(node(Kind::Backref(id), flags));
                }
            }
            other if other.is_ascii_alphabetic() => return Err(self.error("bad escape")),
            other => other as u32,
        };
        Ok(node(Kind::Literal(vec![literal]), flags))
    }
    fn property_escape(&mut self, c: char, flags: Flags) -> Result<N> {
        let saved = self.at;
        let mut negative = c == 'P';
        let name = if self.eat('{') {
            negative ^= self.eat('^');
            let begin = self.at;
            while self
                .peek()
                .is_some_and(|c| c.is_ascii_alphanumeric() || " &_-.".contains(c))
            {
                self.at += 1;
            }
            let mut name: String = self.text[begin..self.at].iter().collect();
            let qualified = self.at;
            if matches!(self.peek(), Some('=' | ':')) {
                let separator = self.take().unwrap();
                let begin = self.at;
                while self
                    .peek()
                    .is_some_and(|c| c.is_ascii_alphanumeric() || " &_-./".contains(c))
                {
                    self.at += 1;
                }
                let value: String = self.text[begin..self.at].iter().collect();
                if value.trim().is_empty() {
                    self.at = qualified;
                } else {
                    name.push(separator);
                    name.push_str(value.trim());
                }
            }
            if !self.eat('}') {
                self.at = saved;
                return Ok(node(Kind::Literal(vec![c as u32]), flags));
            }
            name
        } else if self.peek().is_some_and(|c| "CLMNPSZ".contains(c)) {
            self.take().unwrap().to_string()
        } else {
            self.at = saved;
            return Ok(node(Kind::Literal(vec![c as u32]), flags));
        };
        let set = unicode::property_set(&name).ok_or_else(|| self.error("unknown property"))?;
        Ok(node(
            Kind::Class(if negative {
                Set::Not(Box::new(set))
            } else {
                set
            }),
            flags,
        ))
    }
    fn set_element(&mut self) -> Result<Set> {
        self.poll()?;
        if self.peek() == Some('[')
            && self.dialect == Dialect::Regex
            && self.text.get(self.at + 1) == Some(&':')
        {
            self.at += 2;
            let negative = self.eat('^');
            let start = self.at;
            while !self.starts(":]") && self.peek().is_some() {
                self.at += 1;
            }
            let name: String = self.text[start..self.at].iter().collect();
            if !self.accept(":]") {
                return Err(self.error("unterminated POSIX set"));
            }
            let key = match name.as_str() {
                "digit" => "POSIXDIGIT".to_owned(),
                "alnum" => "POSIXALNUM".into(),
                "punct" => "POSIXPUNCT".into(),
                "xdigit" => "POSIXXDIGIT".into(),
                other => other.into(),
            };
            let set =
                unicode::property_set(&key).ok_or_else(|| self.error("unknown POSIX class"))?;
            return Ok(if negative {
                Set::Not(Box::new(set))
            } else {
                set
            });
        }
        if self.eat('\\') {
            let value = self.escape(true)?;
            return match &value.kind {
                Kind::Literal(v) if v.len() == 1 => Ok(Set::Char(v[0])),
                Kind::Class(set) => Ok(set.clone()),
                _ => Err(self.error("invalid character set escape")),
            };
        }
        if self.flags.v1 && self.eat('[') {
            return self.set_body();
        }
        self.take()
            .map(|c| Set::Char(c as u32))
            .ok_or_else(|| self.error("unterminated character set"))
    }
    fn set_body(&mut self) -> Result<Set> {
        let negative = self.eat('^');
        let mut terms = vec![];
        let mut operations = vec![];
        let mut group = vec![];
        let mut first = true;
        loop {
            if self.peek().is_none() {
                return Err(self.error("unterminated character set"));
            }
            if !first && self.eat(']') {
                break;
            }
            first = false;
            if self.flags.v1 && ["&&", "--", "~~", "||"].iter().any(|op| self.starts(op)) {
                let op = self.text[self.at..self.at + 2].iter().collect::<String>();
                self.at += 2;
                terms.push(set_union(std::mem::take(&mut group)));
                operations.push(op);
                continue;
            }
            let left = self.set_element()?;
            if self.peek() == Some('-')
                && !(self.flags.v1 && self.starts("--"))
                && self.text.get(self.at + 1) != Some(&']')
            {
                self.at += 1;
                let right = self.set_element()?;
                if let (Set::Char(a), Set::Char(b)) = (&left, &right) {
                    if b < a {
                        return Err(self.error("bad character range"));
                    }
                    group.push(Set::Range(*a, *b));
                } else {
                    return Err(self.error("bad character range"));
                }
            } else {
                group.push(left);
            }
        }
        terms.push(set_union(group));
        for operator in ["--", "&&", "~~", "||"] {
            let mut at = 0;
            while at < operations.len() {
                if operations[at] == operator {
                    let a = terms.remove(at);
                    let b = terms.remove(at);
                    let joined = match operator {
                        "--" => Set::Difference(Box::new(a), Box::new(b)),
                        "&&" => Set::And(Box::new(a), Box::new(b)),
                        "~~" => Set::Xor(Box::new(a), Box::new(b)),
                        _ => Set::Union(vec![a, b]),
                    };
                    terms.insert(at, joined);
                    operations.remove(at);
                } else {
                    at += 1;
                }
            }
        }
        let set = terms.pop().unwrap_or(Set::Union(vec![]));
        Ok(if negative {
            Set::Not(Box::new(set))
        } else {
            set
        })
    }
    fn fuzzy(&mut self) -> Result<Option<Fuzzy>> {
        let start = self.at;
        self.at += 1;
        let begin = self.at;
        while self.peek().is_some_and(|c| c != '}' && c != ':') {
            self.at += 1;
        }
        let raw: String = self.text[begin..self.at].iter().collect();
        if !raw.chars().any(|c| matches!(c, 'd' | 'i' | 's' | 'e')) {
            self.at = start;
            return Ok(None);
        }
        let mut fuzzy = Fuzzy {
            minimum: [0; 4],
            maximum: [u32::MAX; 4],
            cost: [1; 3],
            max_cost: u32::MAX,
            test: None,
        };
        let mut specified = [false; 4];
        let mut equation = false;
        for part in raw.split(',') {
            let part = part.replace(' ', "");
            if part.is_empty() {
                self.at = start;
                return Ok(None);
            }
            if part.contains('+')
                || part.chars().next().is_some_and(|c| c.is_ascii_digit())
                    && !part.contains("<=e")
                    && !part.contains("<e")
                    && !part.contains("<=d")
                    && !part.contains("<d")
                    && !part.contains("<=i")
                    && !part.contains("<i")
                    && !part.contains("<=s")
                    && !part.contains("<s")
            {
                let Some((left, right, inclusive)) = split_comparison(&part) else {
                    self.at = start;
                    return Ok(None);
                };
                let max = right
                    .parse::<u32>()
                    .map_err(|_| self.error("bad fuzzy cost limit"))?;
                fuzzy.max_cost = if inclusive {
                    max
                } else {
                    max.checked_sub(1)
                        .ok_or_else(|| self.error("bad fuzzy cost limit"))?
                };
                fuzzy.cost = [0; 3];
                equation = true;
                for term in left.split('+') {
                    let Some(kind) = term.chars().last().and_then(error_kind).filter(|i| *i < 3)
                    else {
                        self.at = start;
                        return Ok(None);
                    };
                    let coefficient = &term[..term.len() - 1];
                    fuzzy.cost[kind] = if coefficient.is_empty() {
                        1
                    } else {
                        coefficient
                            .parse()
                            .map_err(|_| self.error("bad fuzzy cost"))?
                    };
                    specified[kind] = true;
                }
                continue;
            }
            let Some(position) = part
                .chars()
                .position(|c| matches!(c, 'd' | 'i' | 's' | 'e'))
            else {
                self.at = start;
                return Ok(None);
            };
            let kind = error_kind(part.chars().nth(position).unwrap()).unwrap();
            if specified[kind] {
                return Err(self.error("repeated fuzzy constraint"));
            }
            specified[kind] = true;
            let before = &part[..position];
            let after = &part[position + 1..];
            if !before.is_empty() {
                let (min, inclusive) = if let Some(raw) = before.strip_suffix("<=") {
                    (raw, true)
                } else if let Some(raw) = before.strip_suffix('<') {
                    (raw, false)
                } else {
                    self.at = start;
                    return Ok(None);
                };
                let n = min
                    .parse::<u32>()
                    .map_err(|_| self.error("bad fuzzy cost limit"))?;
                fuzzy.minimum[kind] = n.saturating_add(u32::from(!inclusive));
            }
            if !after.is_empty() {
                let (max, inclusive) = if let Some(raw) = after.strip_prefix("<=") {
                    (raw, true)
                } else if let Some(raw) = after.strip_prefix('<') {
                    (raw, false)
                } else {
                    self.at = start;
                    return Ok(None);
                };
                let n = max
                    .parse::<u32>()
                    .map_err(|_| self.error("bad fuzzy cost limit"))?;
                fuzzy.maximum[kind] = if inclusive {
                    n
                } else {
                    n.checked_sub(1)
                        .ok_or_else(|| self.error("bad fuzzy cost limit"))?
                };
            }
            if fuzzy.minimum[kind] > fuzzy.maximum[kind] {
                return Err(self.error("bad fuzzy cost limit"));
            }
        }
        if specified[..3].iter().any(|v| *v) {
            for (i, specified) in specified.iter().take(3).enumerate() {
                if !specified {
                    fuzzy.maximum[i] = 0;
                }
            }
        }
        if !equation {
            fuzzy.max_cost = fuzzy.maximum[3];
        }
        if self.eat(':') {
            fuzzy.test = Some(if self.eat('[') {
                self.set_body()?
            } else if self.eat('\\') {
                let e = self.escape(true)?;
                match &e.kind {
                    Kind::Class(s) => s.clone(),
                    Kind::Literal(v) if v.len() == 1 => Set::Char(v[0]),
                    _ => return Err(self.error("invalid fuzzy character test")),
                }
            } else {
                Set::Char(
                    self.take()
                        .ok_or_else(|| self.error("missing fuzzy character test"))?
                        as u32,
                )
            });
        }
        self.require('}')?;
        Ok(Some(fuzzy))
    }
}
fn same_flags(a: Flags, b: Flags) -> bool {
    a.ignore == b.ignore
        && a.multi == b.multi
        && a.dot == b.dot
        && a.ascii == b.ascii
        && a.full == b.full
        && a.v1 == b.v1
        && a.reverse == b.reverse
        && a.word == b.word
}
fn error_kind(c: char) -> Option<usize> {
    match c {
        'd' => Some(0),
        'i' => Some(1),
        's' => Some(2),
        'e' => Some(3),
        _ => None,
    }
}
fn split_comparison(text: &str) -> Option<(&str, &str, bool)> {
    text.split_once("<=")
        .map(|(a, b)| (a, b, true))
        .or_else(|| text.split_once('<').map(|(a, b)| (a, b, false)))
}

fn set_union(mut parts: Vec<Set>) -> Set {
    if parts.len() == 1 {
        parts.remove(0)
    } else {
        Set::Union(parts)
    }
}
