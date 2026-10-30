//! Pure physical scheduling; actions and BODY are immutable barriers.
use super::*;
use crate::Scan;
pub(super) fn prepare(program: &Program, reference: bool) -> Result<Vec<Step>> {
    let input = if program.steps.is_empty() {
        program.scans.iter().cloned().map(Step::Scan).collect()
    } else {
        program.steps.clone()
    };
    let mut output = vec![];
    let mut bound = BTreeSet::new();
    let mut scans = vec![];
    for step in input {
        match step {
            Step::Scan(scan) => scans.push(scan),
            other => {
                order(&mut scans, &mut bound, reference, &mut output)?;
                match &other {
                    Step::Action(a) if !a.role.is_empty() => {
                        bound.insert(a.role.clone());
                    }
                    Step::Body(b) => bound.extend(b.outputs.iter().cloned()),
                    _ => (),
                };
                output.push(other);
            }
        }
    }
    order(&mut scans, &mut bound, reference, &mut output)?;
    Ok(output)
}
fn order(
    scans: &mut Vec<Scan>,
    bound: &mut BTreeSet<String>,
    reference: bool,
    out: &mut Vec<Step>,
) -> Result<()> {
    while !scans.is_empty() {
        let index = if reference {
            0
        } else {
            scans
                .iter()
                .enumerate()
                .filter(|(_, s)| s.owner.as_ref().is_none_or(|o| bound.contains(o)))
                .min_by_key(|(_, s)| {
                    let score = if bound.contains(&s.role) {
                        0
                    } else if s
                        .properties
                        .iter()
                        .any(|(k, e)| k == "name" && e.kind == "literal")
                    {
                        1
                    } else if s.owner.is_some() {
                        2
                    } else {
                        3
                    };
                    (
                        score,
                        crate::capabilities::vocabulary()
                            .kinds
                            .get(&s.selector)
                            .map_or(0, Vec::len),
                    )
                })
                .map(|(i, _)| i)
                .ok_or_else(|| invalid("cyclic scan binding dependencies"))?
        };
        let scan = scans.remove(index);
        bound.insert(scan.role.clone());
        out.push(Step::Scan(scan));
    }
    Ok(())
}
pub(super) fn describe(step: &Step, reference: bool) -> Json {
    match step {
        Step::Body(b) => {
            json!({"operator":"body","owner":b.owner,"outputs":b.outputs,"barrier":true})
        }
        Step::Action(a) => {
            json!({"operator":if a.role.is_empty(){"filter"}else{"bind"},"role":a.role,"source":a.expression.span.source,"start":a.expression.span.start,"end":a.expression.span.end,"barrier":true})
        }
        Step::Scan(s) => {
            json!({"operator":"scan","role":s.role,"selector":s.selector,"owner":s.owner,"access":if reference{"reference_scan"}else if s.properties.iter().any(|(k,e)|k=="name"&&e.kind=="literal"){"name_lookup"}else if s.owner.is_some(){"owner_lookup"}else{"kind_scan"}})
        }
    }
}
