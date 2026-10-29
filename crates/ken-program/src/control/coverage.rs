//! Coverage decisions belong to the source control model, not its SQL reader.
use crate::{Fact, ProgramError, value::GraphValue};
/// Await and abrupt-exit inventories preserve general statement order only when
/// every status supports the same claim. Unknown and yield scopes stay uncovered.
pub fn supports_general_walk(statuses: &[Fact]) -> Result<bool, ProgramError> {
    if statuses.is_empty() {
        return Ok(false);
    }
    for allowed in [
        ["await", "await_expression"],
        ["raise_statement", "throw_statement"],
    ] {
        let mut all = true;
        for fact in statuses {
            if fact.object == "structured" {
                continue;
            }
            if fact.object != "partial" {
                all = false;
                break;
            }
            let reasons = fact
                .attrs
                .get("reasons")
                .map(|v| GraphValue::parse(v))
                .transpose()?;
            let Some(
                GraphValue::List(reasons) | GraphValue::Tuple(reasons) | GraphValue::Set(reasons),
            ) = reasons
            else {
                all = false;
                break;
            };
            if reasons.is_empty()
                || reasons
                    .iter()
                    .any(|r| r.string().is_none_or(|r| !allowed.contains(&r.as_str())))
            {
                all = false;
                break;
            }
        }
        if all {
            return Ok(true);
        }
    }
    Ok(false)
}
