//! Ordered iterative search with explicit backtracking, captures and atomic cuts.
use super::*;
#[derive(Clone)]
enum Task {
    Node(N),
    Character(Set, Flags),
    SaveEnd(usize, usize),
    Repeat {
        node: N,
        min: u64,
        max: Option<u64>,
        count: u64,
        lazy: bool,
        zero: bool,
    },
    AfterRepeat {
        node: N,
        min: u64,
        max: Option<u64>,
        count: u64,
        lazy: bool,
        before: usize,
    },
    Cut(usize),
    FuzzyExit,
}
#[derive(Clone)]
struct FuzzyState {
    rules: Arc<Fuzzy>,
    counts: [u32; 4],
}
#[derive(Clone)]
struct State {
    position: usize,
    tasks: Vec<Task>,
    captures: Vec<Option<(usize, usize)>>,
    fuzzy: Vec<FuzzyState>,
}
struct Answer {
    state: Option<State>,
    skip: Option<usize>,
}
pub(super) fn search(pattern: &Pattern, text: &[u32], control: &mut Control<'_>) -> Result<bool> {
    let direction = if pattern.flags.reverse { -1 } else { 1 };
    let mut start = if direction == 1 { 0 } else { text.len() };
    loop {
        control.poll()?;
        let answer = run(
            pattern,
            pattern.root.clone(),
            text,
            start,
            vec![None; pattern.groups.len()],
            direction,
            control,
            0,
        )?;
        if answer.state.is_some() {
            return Ok(true);
        }
        if direction == 1 {
            if start == text.len() {
                break;
            }
            start = answer
                .skip
                .unwrap_or(start + 1)
                .max(start + 1)
                .min(text.len());
        } else {
            if start == 0 {
                break;
            }
            start = answer.skip.unwrap_or(start - 1).min(start - 1);
        }
    }
    Ok(false)
}
fn next(text: &[u32], position: usize, direction: i32) -> Option<(u32, usize)> {
    if direction == 1 {
        text.get(position).map(|c| (*c, position + 1))
    } else {
        position
            .checked_sub(1)
            .and_then(|p| text.get(p).map(|c| (*c, p)))
    }
}
#[expect(
    clippy::too_many_arguments,
    reason = "The regex invocation keeps direction, captures, budget and recursion depth explicit"
)]
fn run(
    pattern: &Pattern,
    root: N,
    text: &[u32],
    start: usize,
    captures: Vec<Option<(usize, usize)>>,
    direction: i32,
    control: &mut Control<'_>,
    depth: usize,
) -> Result<Answer> {
    crate::with_stack(|| {
        if depth > 256 {
            return Err(ExecutionError::Exhausted("regex_timeout"));
        }
        let mut skip = None;
        let mut pending = vec![State {
            position: start,
            tasks: vec![Task::Node(root)],
            captures,
            fuzzy: vec![],
        }];
        while let Some(mut state) = pending.pop() {
            control.poll()?;
            let mut failed = false;
            while let Some(task) = state.tasks.pop() {
                control.poll()?;
                if state.tasks.len() > 100_000 || pending.len() > 1_000_000 {
                    return Err(ExecutionError::Exhausted("regex_timeout"));
                }
                match task {
                    Task::SaveEnd(group, begin) => {
                        state.captures[group] =
                            Some((begin.min(state.position), begin.max(state.position)));
                    }
                    Task::Cut(mark) => pending.truncate(mark),
                    Task::FuzzyExit => {
                        let context = state.fuzzy.last().expect("fuzzy exit has context");
                        if let Some((cp, after)) = next(text, state.position, direction) {
                            let mut insertion = state.clone();
                            if edit(&mut insertion, 1, Some(cp), pattern) {
                                insertion.position = after;
                                insertion.tasks.push(Task::FuzzyExit);
                                pending.push(insertion);
                            }
                        }
                        if !context
                            .counts
                            .iter()
                            .zip(&context.rules.minimum)
                            .all(|(got, min)| got >= min)
                        {
                            failed = true;
                            break;
                        }
                        state.fuzzy.pop();
                    }
                    Task::AfterRepeat {
                        node,
                        min,
                        max,
                        count,
                        lazy,
                        before,
                    } => {
                        let zero = state.position == before;
                        let count = if zero {
                            (count + 1).max(min)
                        } else {
                            count + 1
                        };
                        state.tasks.push(Task::Repeat {
                            node,
                            min,
                            max,
                            count,
                            lazy,
                            zero,
                        });
                    }
                    Task::Repeat {
                        node,
                        min,
                        max,
                        count,
                        lazy,
                        zero,
                    } => {
                        let stop = count >= min;
                        let more = !zero && max.is_none_or(|m| count < m);
                        if !more {
                            if !stop {
                                failed = true;
                                break;
                            }
                            continue;
                        }
                        let mut again = state.clone();
                        again.tasks.push(Task::AfterRepeat {
                            node: node.clone(),
                            min,
                            max,
                            count,
                            lazy,
                            before: state.position,
                        });
                        again.tasks.push(Task::Node(node));
                        if stop {
                            if lazy {
                                pending.push(again);
                            } else {
                                pending.push(state);
                                state = again;
                            }
                        } else {
                            state = again;
                        }
                    }
                    Task::Character(set, flags) => {
                        let input = next(text, state.position, direction);
                        let matched = input
                            .is_some_and(|(c, _)| unicode::set(&set, c, flags, pattern.dialect));
                        if !state.fuzzy.is_empty() {
                            // Exact paths retain priority. Error paths preserve the
                            // complete capture/atomic/fuzzy state independently.
                            let mut alternatives = vec![];
                            if let Some((cp, after)) = input {
                                let mut insertion = state.clone();
                                if edit(&mut insertion, 1, Some(cp), pattern) {
                                    insertion.position = after;
                                    insertion.tasks.push(Task::Character(set.clone(), flags));
                                    alternatives.push(insertion);
                                }
                                if !matched {
                                    let mut substitute = state.clone();
                                    if edit(&mut substitute, 2, Some(cp), pattern) {
                                        substitute.position = after;
                                        alternatives.push(substitute);
                                    }
                                }
                            }
                            let mut deletion = state.clone();
                            if edit(&mut deletion, 0, None, pattern) {
                                alternatives.push(deletion);
                            }
                            for alternative in alternatives.into_iter().rev() {
                                pending.push(alternative);
                            }
                        }
                        if matched {
                            state.position = input.unwrap().1;
                        } else {
                            failed = true;
                            break;
                        }
                    }
                    Task::Node(node) => {
                        let flags = node.flags;
                        match &node.kind {
                            Kind::Empty | Kind::Keep => (),
                            Kind::Fail => {
                                failed = true;
                                break;
                            }
                            Kind::Literal(values) => {
                                if flags.ignore
                                    && flags.full
                                    && pattern.dialect == Dialect::Regex
                                    && !flags.ascii
                                    && state.fuzzy.is_empty()
                                {
                                    let wanted: Vec<_> =
                                        values.iter().flat_map(|c| unicode::fold(*c)).collect();
                                    let mut consumed = vec![];
                                    let mut position = state.position;
                                    while consumed.len() < wanted.len() {
                                        control.poll()?;
                                        let Some((cp, after)) = next(text, position, direction)
                                        else {
                                            break;
                                        };
                                        let folded = unicode::fold(cp);
                                        if direction == 1 {
                                            consumed.extend(folded);
                                        } else {
                                            let mut f = folded;
                                            f.reverse();
                                            consumed.extend(f);
                                        }
                                        position = after;
                                    }
                                    let wanted = if direction == 1 {
                                        wanted
                                    } else {
                                        wanted.into_iter().rev().collect()
                                    };
                                    if consumed.len() != wanted.len()
                                        || !wanted.iter().zip(&consumed).all(|(a, b)| {
                                            unicode::equal(*a, *b, flags, pattern.dialect)
                                        })
                                    {
                                        failed = true;
                                        break;
                                    }
                                    state.position = position;
                                } else if direction == 1 {
                                    for cp in values.iter().rev() {
                                        state.tasks.push(Task::Character(Set::Char(*cp), flags));
                                    }
                                } else {
                                    for cp in values {
                                        state.tasks.push(Task::Character(Set::Char(*cp), flags));
                                    }
                                }
                            }
                            Kind::Class(set) => {
                                state.tasks.push(Task::Character(set.clone(), flags))
                            }
                            Kind::Any => {
                                let set = if flags.dot {
                                    Set::Range(0, 0x10ffff)
                                } else if flags.word && pattern.dialect == Dialect::Regex {
                                    Set::Not(Box::new(Set::Union(vec![
                                        Set::Char(10),
                                        Set::Char(11),
                                        Set::Char(12),
                                        Set::Char(13),
                                        Set::Char(0x85),
                                        Set::Char(0x2028),
                                        Set::Char(0x2029),
                                    ])))
                                } else {
                                    Set::Not(Box::new(Set::Char(10)))
                                };
                                state.tasks.push(Task::Character(set, flags));
                            }
                            Kind::Anchor(anchor) => {
                                if !anchor_matches(
                                    *anchor,
                                    text,
                                    state.position,
                                    flags,
                                    pattern.dialect,
                                    pattern.flags.reverse,
                                    control,
                                )? {
                                    failed = true;
                                    break;
                                }
                            }
                            Kind::Sequence(nodes) => {
                                if direction == 1 {
                                    for node in nodes.iter().rev() {
                                        state.tasks.push(Task::Node(node.clone()));
                                    }
                                } else {
                                    for node in nodes {
                                        state.tasks.push(Task::Node(node.clone()));
                                    }
                                }
                            }
                            Kind::Alternate(nodes) => {
                                if let Some(first) = nodes.first() {
                                    for node in nodes[1..].iter().rev() {
                                        let mut other = state.clone();
                                        other.tasks.push(Task::Node(node.clone()));
                                        pending.push(other);
                                    }
                                    state.tasks.push(Task::Node(first.clone()));
                                } else {
                                    failed = true;
                                    break;
                                }
                            }
                            Kind::Repeat {
                                node,
                                min,
                                max,
                                lazy,
                            } => state.tasks.push(Task::Repeat {
                                node: node.clone(),
                                min: *min,
                                max: *max,
                                count: 0,
                                lazy: *lazy,
                                zero: false,
                            }),
                            Kind::Atomic(child) => {
                                state.tasks.push(Task::Cut(pending.len()));
                                state.tasks.push(Task::Node(child.clone()));
                            }
                            Kind::Capture(group, child) => {
                                state.captures[*group] = None;
                                state.tasks.push(Task::SaveEnd(*group, state.position));
                                state.tasks.push(Task::Node(child.clone()));
                            }
                            Kind::Backref(group) => {
                                let Some((begin, end)) =
                                    state.captures.get(*group).copied().flatten()
                                else {
                                    failed = true;
                                    break;
                                };
                                state.tasks.push(Task::Node(super::node(
                                    Kind::Literal(text[begin..end].to_vec()),
                                    flags,
                                )));
                            }
                            Kind::Look {
                                node,
                                positive,
                                behind,
                            } => {
                                let result = run(
                                    pattern,
                                    node.clone(),
                                    text,
                                    state.position,
                                    state.captures.clone(),
                                    if *behind { -1 } else { 1 },
                                    control,
                                    depth + 1,
                                )?;
                                if result.state.is_some() != *positive {
                                    failed = true;
                                    break;
                                }
                                if let Some(found) = result.state
                                    && *positive
                                {
                                    state.captures = found.captures;
                                }
                            }
                            Kind::AssertionConditional {
                                assertion,
                                positive,
                                behind,
                                yes,
                                no,
                            } => {
                                let result = run(
                                    pattern,
                                    assertion.clone(),
                                    text,
                                    state.position,
                                    state.captures.clone(),
                                    if *behind { -1 } else { 1 },
                                    control,
                                    depth + 1,
                                )?;
                                let success = result.state.is_some() == *positive;
                                if *positive && let Some(found) = result.state {
                                    state.captures = found.captures;
                                }
                                state.tasks.push(Task::Node(if success {
                                    yes.clone()
                                } else {
                                    no.clone()
                                }));
                            }
                            Kind::Conditional { group, yes, no } => {
                                let present =
                                    state.captures.get(*group).is_some_and(Option::is_some);
                                state.tasks.push(Task::Node(if present {
                                    yes.clone()
                                } else {
                                    no.clone()
                                }));
                            }
                            Kind::Call(group) => {
                                let Some(root) = pattern.groups.get(*group).and_then(Clone::clone)
                                else {
                                    return Err(invalid("unknown group call"));
                                };
                                state.tasks.push(Task::Node(root));
                            }
                            Kind::Fuzzy(child, rules) => {
                                state.fuzzy.push(FuzzyState {
                                    rules: rules.clone(),
                                    counts: [0; 4],
                                });
                                state.tasks.push(Task::FuzzyExit);
                                state.tasks.push(Task::Node(child.clone()));
                            }
                            Kind::Linebreak => {
                                let input = next(text, state.position, direction);
                                let Some((cp, mut after)) = input else {
                                    failed = true;
                                    break;
                                };
                                if !matches!(cp, 10..=13 | 0x85 | 0x2028 | 0x2029) {
                                    failed = true;
                                    break;
                                }
                                if direction == 1 && cp == 13 && text.get(after) == Some(&10) {
                                    after += 1;
                                } else if direction == -1
                                    && cp == 10
                                    && after > 0
                                    && text[after - 1] == 13
                                {
                                    after -= 1;
                                }
                                state.position = after;
                            }
                            Kind::Grapheme => {
                                if direction == 1 {
                                    if state.position == text.len() {
                                        failed = true;
                                        break;
                                    }
                                    state.position =
                                        unicode::grapheme_end(text, state.position, control)?;
                                } else {
                                    if state.position == 0 {
                                        failed = true;
                                        break;
                                    }
                                    let mut begin = 0;
                                    while begin < state.position {
                                        control.poll()?;
                                        let end = unicode::grapheme_end(text, begin, control)?;
                                        if end >= state.position {
                                            break;
                                        }
                                        begin = end;
                                    }
                                    state.position = begin;
                                }
                            }
                            Kind::Prune => pending.clear(),
                            Kind::Skip => {
                                pending.clear();
                                skip = Some(state.position);
                            }
                        }
                    }
                }
            }
            if !failed {
                return Ok(Answer {
                    state: Some(state),
                    skip,
                });
            }
        }
        Ok(Answer { state: None, skip })
    })
}
fn edit(state: &mut State, kind: usize, character: Option<u32>, pattern: &Pattern) -> bool {
    for context in &mut state.fuzzy {
        if kind != 0
            && character.is_some_and(|cp| {
                context
                    .rules
                    .test
                    .as_ref()
                    .is_some_and(|s| !unicode::set(s, cp, pattern.flags, pattern.dialect))
            })
        {
            return false;
        }
        context.counts[kind] = context.counts[kind].saturating_add(1);
        context.counts[3] = context.counts[3].saturating_add(1);
        if context
            .counts
            .iter()
            .zip(&context.rules.maximum)
            .any(|(n, max)| n > max)
        {
            return false;
        }
        let cost = context.counts[..3]
            .iter()
            .zip(&context.rules.cost)
            .map(|(n, c)| u64::from(*n) * u64::from(*c))
            .sum::<u64>();
        if cost > u64::from(context.rules.max_cost) {
            return false;
        }
    }
    true
}
fn anchor_matches(
    anchor: Anchor,
    text: &[u32],
    position: usize,
    flags: Flags,
    dialect: Dialect,
    reverse: bool,
    control: &mut Control<'_>,
) -> Result<bool> {
    let word = |index: Option<usize>| {
        index
            .and_then(|i| text.get(i))
            .is_some_and(|cp| unicode::class(Class::Word, *cp, dialect, flags.ascii))
    };
    let left = word(position.checked_sub(1));
    let right = word(Some(position));
    let unicode_word = flags.word && dialect == Dialect::Regex;
    let boundary = if unicode_word {
        boundaries::word(text, position, control)?
    } else {
        left != right
    };
    Ok(match anchor {
        Anchor::AbsoluteStart => position == 0,
        Anchor::AbsoluteEnd => position == text.len(),
        Anchor::SearchStart => position == if reverse { text.len() } else { 0 },
        Anchor::Start => boundaries::line_start(text, position, flags.multi, unicode_word),
        Anchor::End => boundaries::line_end(text, position, flags.multi, unicode_word),
        Anchor::Word(positive) => {
            if positive {
                boundary
            } else {
                !boundary && (dialect == Dialect::Regex || !text.is_empty())
            }
        }
        Anchor::WordStart => boundary && right,
        Anchor::WordEnd => boundary && left,
    })
}
