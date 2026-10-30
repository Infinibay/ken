//! Region visibility is checked before formatting or admitting persisted instructions.
use super::{Function, Program, Region, Result};
use crate::ProgramError;
use std::collections::BTreeSet;
fn fail(message: &'static str) -> ProgramError {
    ProgramError::Invalid(message)
}
fn signature(opcode: &str) -> Option<&'static [&'static str]> {
    Some(match opcode {
        "slot.declare" | "slot.load" => &["place"],
        "slot.store" => &["place", "value"],
        "field.addr" | "memory.load" | "if" | "choose" | "short_circuit" | "iterate" => &["value"],
        "index.addr" | "memory.store" => &["value", "value"],
        "loop" | "const" | "iteration.value" => &[],
        _ => return None,
    })
}
fn known(opcode: &str) -> bool {
    matches!(
        opcode,
        "const"
            | "slot.declare"
            | "slot.load"
            | "slot.store"
            | "field.addr"
            | "index.addr"
            | "memory.load"
            | "memory.store"
            | "call"
            | "construct"
            | "binary"
            | "unary"
            | "compare"
            | "if"
            | "loop"
            | "return"
            | "break"
            | "continue"
            | "throw"
            | "yield"
            | "yield.delegate"
            | "await"
            | "native"
            | "choose"
            | "short_circuit"
            | "iterate"
            | "iteration.value"
    )
}
pub(super) fn verify(program: &Program) -> Result<()> {
    if program.schema != "ken-instructions/1" {
        return Err(fail("incompatible instruction schema"));
    }
    let mut functions = BTreeSet::new();
    for function in &program.functions {
        if !functions.insert(function.id.as_str()) {
            return Err(fail("duplicate function"));
        }
        if function
            .parameters
            .iter()
            .any(|p| !function.places.iter().any(|(id, _)| id == p))
        {
            return Err(fail("parameter has no place"));
        }
        let mut verifier = Verifier {
            function,
            ids: BTreeSet::new(),
            definitions: BTreeSet::new(),
        };
        verifier.region(&function.body, &BTreeSet::new(), 0, false)?;
    }
    Ok(())
}
struct Verifier<'a> {
    function: &'a Function,
    ids: BTreeSet<&'a str>,
    definitions: BTreeSet<&'a str>,
}
impl<'a> Verifier<'a> {
    fn region(
        &mut self,
        region: &'a Region,
        incoming: &BTreeSet<&'a str>,
        depth: usize,
        iteration_body: bool,
    ) -> Result<()> {
        if depth > 128 || !self.ids.insert(&region.id) {
            return Err(fail("invalid or duplicate region"));
        }
        let mut visible = incoming.clone();
        for (position, instruction) in region.instructions.iter().enumerate() {
            let code = instruction.opcode.as_str();
            if !known(code) || !self.ids.insert(&instruction.id) {
                return Err(fail("invalid or duplicate instruction"));
            }
            if signature(code).is_some_and(|expected| {
                instruction
                    .operands
                    .iter()
                    .map(|o| o.kind.as_str())
                    .collect::<Vec<_>>()
                    != expected
            }) {
                return Err(fail("invalid instruction operands"));
            }
            if instruction
                .result_type
                .get("kind")
                .and_then(serde_json::Value::as_str)
                .is_none()
            {
                return Err(fail("invalid result type"));
            }
            let void = matches!(
                code,
                "slot.declare"
                    | "slot.store"
                    | "memory.store"
                    | "if"
                    | "loop"
                    | "return"
                    | "break"
                    | "continue"
                    | "throw"
                    | "iterate"
            );
            if void != instruction.result.is_none() {
                return Err(fail("invalid instruction result"));
            }
            for operand in &instruction.operands {
                match operand.kind.as_str() {
                    "value" if !visible.contains(operand.r#ref.as_str()) => {
                        return Err(fail("value used before definition or outside its region"));
                    }
                    "place"
                        if !self
                            .function
                            .places
                            .iter()
                            .any(|(id, _)| id == &operand.r#ref) =>
                    {
                        return Err(fail("unknown place"));
                    }
                    "value" | "place" | "symbol" => {}
                    _ => return Err(fail("invalid operand kind")),
                }
            }
            let layout = instruction
                .regions
                .iter()
                .map(|r| r.kind.as_str())
                .collect::<Vec<_>>();
            if !layout.is_empty()
                && !matches!(code, "if" | "loop" | "choose" | "short_circuit" | "iterate")
            {
                return Err(fail("regions on a non-control instruction"));
            }
            match code {
                "choose"
                    if (layout != ["consequence", "alternative"]
                        || instruction.regions.iter().any(|r| r.outputs.len() != 1)) =>
                {
                    return Err(fail("choose requires two single-result arms"));
                }
                "short_circuit" => {
                    if layout != ["rhs"]
                        || instruction.regions[0].outputs.len() != 1
                        || !matches!(
                            instruction.attrs["operator"].as_str(),
                            Some("and" | "or" | "&&" | "||" | "??")
                        )
                    {
                        return Err(fail("invalid short circuit region"));
                    }
                    if !matches!(
                        instruction.attrs["result_policy"].as_str(),
                        Some("selected-operand" | "boolean")
                    ) {
                        return Err(fail("invalid short circuit result policy"));
                    }
                }
                "if" if ((layout != ["consequence"]
                    && layout != ["consequence", "alternative"])
                    || instruction.regions.iter().any(|r| !r.outputs.is_empty())) =>
                {
                    return Err(fail("invalid if regions"));
                }
                "loop" => {
                    let expected: &[&str] = match instruction.attrs["form"].as_str() {
                        Some("while") => &["test", "body"],
                        Some("do") => &["body", "test"],
                        Some("for") => &["init", "test", "body", "update"],
                        _ => return Err(fail("invalid loop regions")),
                    };
                    if layout != expected
                        || instruction
                            .regions
                            .iter()
                            .any(|r| r.outputs.len() != usize::from(r.kind == "test"))
                    {
                        return Err(fail("invalid loop regions"));
                    }
                }
                "iterate" => {
                    if layout != ["body"] || !instruction.regions[0].outputs.is_empty() {
                        return Err(fail("iterate requires one body without outputs"));
                    }
                    let body = &instruction.regions[0].instructions;
                    if body.first().is_none_or(|i| i.opcode != "iteration.value")
                        || body
                            .iter()
                            .filter(|i| i.opcode == "iteration.value")
                            .count()
                            != 1
                    {
                        return Err(fail("iterate requires one leading element definition"));
                    }
                }
                "iteration.value" if !iteration_body || position != 0 => {
                    return Err(fail("element outside iteration body"));
                }
                _ => {}
            }
            for child in &instruction.regions {
                self.region(child, &visible, depth + 1, code == "iterate")?;
            }
            if let Some(result) = instruction.result.as_deref() {
                if !self.definitions.insert(result) {
                    return Err(fail("duplicate value definition"));
                }
                visible.insert(result);
            }
        }
        if region
            .outputs
            .iter()
            .any(|id| !visible.contains(id.as_str()))
        {
            return Err(fail("region output is undefined"));
        }
        Ok(())
    }
}
