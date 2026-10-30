//! Assembly names values by first display encounter, preserving place insertion order.
use super::{Program, Region, Result};
use serde_json::Value;
use std::collections::BTreeMap;
fn string(text: &str, ascii: bool) -> String {
    let raw = serde_json::to_string(text).expect("scalar text");
    if !ascii {
        return raw;
    }
    let mut result = String::new();
    for c in raw.chars() {
        if c as u32 <= 0x7f {
            result.push(c);
        } else {
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                result.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    result
}
fn json(value: &Value, ascii: bool) -> String {
    match value {
        Value::String(s) => string(s, ascii),
        Value::Array(items) => format!(
            "[{}]",
            items
                .iter()
                .map(|v| json(v, ascii))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(fields) => format!(
            "{{{}}}",
            fields
                .iter()
                .map(|(k, v)| format!("{}: {}", string(k, ascii), json(v, ascii)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => value.to_string(),
    }
}
struct Names {
    places: BTreeMap<String, String>,
    values: BTreeMap<String, String>,
}
impl Names {
    fn value(&mut self, id: &str) -> String {
        let next = self.values.len();
        self.values
            .entry(id.into())
            .or_insert_with(|| format!("%{next}"))
            .clone()
    }
    fn region(&mut self, region: &Region, level: usize, lines: &mut Vec<String>) {
        let pad = "  ".repeat(level);
        lines.push(format!("{pad}{} {{", region.kind));
        for instruction in &region.instructions {
            let operands = instruction
                .operands
                .iter()
                .map(|operand| {
                    let value = match operand.kind.as_str() {
                        "value" => self.value(&operand.r#ref),
                        "place" => self.places[&operand.r#ref].clone(),
                        _ => string(&operand.r#ref, true),
                    };
                    if operand.role.is_empty() {
                        value
                    } else {
                        format!("{}={value}", operand.role)
                    }
                })
                .collect::<Vec<_>>()
                .join(", ");
            let output = instruction
                .result
                .as_deref()
                .map(|id| {
                    format!(
                        "{} : {} = ",
                        self.value(id),
                        instruction.result_type["kind"]
                            .as_str()
                            .unwrap_or("unknown")
                    )
                })
                .unwrap_or_default();
            let attrs = if instruction.attrs.as_object().is_some_and(|o| !o.is_empty()) {
                format!(" {}", json(&instruction.attrs, false))
            } else {
                String::new()
            };
            let effects = if instruction.effects.is_empty() {
                String::new()
            } else {
                format!(
                    " effects={}",
                    json(
                        &serde_json::to_value(&instruction.effects).expect("effect strings"),
                        true
                    )
                )
            };
            lines.push(format!(
                "{pad}  {output}{} {operands}{attrs}{effects}",
                instruction.opcode
            ));
            for child in &instruction.regions {
                self.region(child, level + 2, lines);
            }
        }
        if !region.outputs.is_empty() {
            let outputs = region
                .outputs
                .iter()
                .map(|id| self.value(id))
                .collect::<Vec<_>>()
                .join(", ");
            lines.push(format!("{pad}  outputs {outputs}"));
        }
        lines.push(format!("{pad}}}"));
    }
}
pub(super) fn format(program: &Program) -> Result<String> {
    program.verify()?;
    let mut lines = vec![format!(
        "{} source={}",
        program.schema, program.source_version
    )];
    for function in &program.functions {
        let mut names = Names {
            places: function
                .places
                .iter()
                .enumerate()
                .map(|(i, (id, _))| (id.clone(), format!("@p{i}")))
                .collect(),
            values: BTreeMap::new(),
        };
        lines.push(format!(
            "func {} [{}, {}] {{",
            string(&function.name, false),
            function.language,
            function.status
        ));
        for (id, place) in &function.places {
            lines.push(format!(
                "  slot {} {} : {}",
                names.places[id],
                string(&place.name, true),
                place.data_type["kind"].as_str().unwrap_or("unknown")
            ));
        }
        names.region(&function.body, 1, &mut lines);
        if !function.reasons.is_empty() {
            lines.push(format!(
                "  partial: {}",
                json(
                    &serde_json::to_value(&function.reasons).expect("reason strings"),
                    true
                )
            ));
        }
        lines.push("}".into());
    }
    Ok(lines.join("\n") + "\n")
}
