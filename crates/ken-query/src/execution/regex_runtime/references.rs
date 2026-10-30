//! Resolve forward names after parsing and determine closed-group widths.
use super::*;
pub(super) fn resolve(
    root: &mut N,
    ids: &BTreeMap<usize, usize>,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    crate::with_stack(|| {
        check()?;
        match &mut Arc::make_mut(root).kind {
            Kind::Backref(id) | Kind::Call(id) => {
                if let Some(target) = ids.get(id) {
                    *id = *target;
                }
            }
            Kind::Conditional { group, yes, no } => {
                if let Some(target) = ids.get(group) {
                    *group = *target;
                }
                resolve(yes, ids, check)?;
                resolve(no, ids, check)?;
            }
            Kind::AssertionConditional {
                assertion, yes, no, ..
            } => {
                resolve(assertion, ids, check)?;
                resolve(yes, ids, check)?;
                resolve(no, ids, check)?;
            }
            Kind::Sequence(parts) | Kind::Alternate(parts) => {
                for part in parts {
                    resolve(part, ids, check)?;
                }
            }
            Kind::Repeat { node, .. }
            | Kind::Look { node, .. }
            | Kind::Atomic(node)
            | Kind::Capture(_, node)
            | Kind::Fuzzy(node, _) => resolve(node, ids, check)?,
            _ => (),
        }
        Ok(())
    })
}
pub(super) fn width(root: &N, groups: &[Option<N>], depth: usize) -> Option<u64> {
    if depth > 256 {
        return None;
    }
    let child = |n: &N| width(n, groups, depth + 1);
    match &root.kind {
        Kind::Empty | Kind::Anchor(_) | Kind::Look { .. } | Kind::Keep => Some(0),
        Kind::Literal(v) => Some(v.len() as u64),
        Kind::Class(_) | Kind::Any => Some(1),
        Kind::Sequence(v) => v.iter().try_fold(0u64, |n, v| n.checked_add(child(v)?)),
        Kind::Alternate(v) => {
            let first = child(v.first()?)?;
            v.iter().all(|v| child(v) == Some(first)).then_some(first)
        }
        Kind::Repeat {
            node,
            min,
            max: Some(max),
            ..
        } if min == max => child(node)?.checked_mul(*min),
        Kind::Atomic(v) | Kind::Capture(_, v) => child(v),
        Kind::Backref(id) => child(groups.get(*id)?.as_ref()?),
        Kind::Conditional { yes, no, .. } => {
            let yes = child(yes)?;
            (child(no) == Some(yes)).then_some(yes)
        }
        _ => None,
    }
}
