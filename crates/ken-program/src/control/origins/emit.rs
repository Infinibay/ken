//! Derived evidence retains origin/write correlation and stable field-state identities.
use super::*;
use sha2::{Digest, Sha256};
fn repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for c in value.chars() {
        if c == quote || c == '\\' {
            out.push('\\');
            out.push(c);
        } else {
            match c {
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                _ if !ken_text::unicode::printable(c) => {
                    let code = c as u32;
                    out.push_str(&if code <= 0xff {
                        format!("\\x{code:02x}")
                    } else if code <= 0xffff {
                        format!("\\u{code:04x}")
                    } else {
                        format!("\\U{code:08x}")
                    });
                }
                _ => out.push(c),
            }
        }
    }
    out.push(quote);
    out
}
impl Owner<'_, '_> {
    pub(super) fn emit(&self, output: &mut Vec<Fact>, result: &mut ReturnOrigins) -> Result<()> {
        let entity = self.entity()?;
        let evidence = |line| Some(format!("{}:{line}", entity.path));
        for &i in &self.return_ops {
            let op = self.input.ctx.op(i);
            let cases = &self.pending[&op.id];
            let key = (self.id.clone(), self.input.returns[&op.id].clone());
            let result = result.entry(key).or_default();
            let origins = cases
                .iter()
                .map(|(value, _)| value)
                .collect::<BTreeSet<_>>();
            let definitions = cases
                .iter()
                .map(|(_, definition)| definition)
                .collect::<BTreeSet<_>>();
            for (value, definition) in cases {
                let value = value.as_ref().expect("admitted return origin");
                result.insert(value.clone());
                output.push(fact(&op.id,"RETURN_ORIGIN",value,evidence(op.line),json!({"basis":"flow","analysis":"structured-locals/3","modality":if origins.len()>1{"may"}else{"must"}})));
                if let Some(definition) = definition {
                    output.push(fact(&op.id,"RETURN_REACHES",definition,evidence(op.line),json!({"basis":"flow","analysis":"structured-locals/3","modality":if definitions.len()>1{"may"}else{"must"}})));
                }
            }
        }
        for id in &self.arg_order {
            let call = &self.input.op_entities[id];
            let op = self.input.ctx.op(self.input.ctx.ids[id.as_str()]);
            for ((position, storage), cases) in &self.arg_pending[id] {
                let unknown = cases.iter().any(|(v, _)| v.is_none());
                let sources = cases
                    .iter()
                    .filter_map(|(v, _)| v.as_ref())
                    .collect::<BTreeSet<_>>();
                let definitions = cases
                    .iter()
                    .filter(|(v, _)| v.is_some())
                    .filter_map(|(_, d)| d.as_ref())
                    .collect::<BTreeSet<_>>();
                let modality = if !unknown && sources.len() == 1 {
                    "must"
                } else {
                    "may"
                };
                output.push(fact(call,"ARGUMENT_ORIGIN",storage,evidence(op.line),json!({"basis":"flow","analysis":"argument-origins/1","position":position,"modality":modality,"origins":sources,"unknown":unknown,"cases":cases.iter().map(|(v,d)|json!([v,d])).collect::<Vec<_>>()})));
                for definition in &definitions {
                    output.push(fact(call,"ARGUMENT_REACHES",definition,evidence(op.line),json!({"basis":"flow","analysis":"argument-origins/1","position":position,"operand":storage,"modality":if unknown||definitions.len()>1{"may"}else{"must"}})));
                }
                for source in sources {
                    output.push(fact(call,"ARGUMENT_VALUE_ORIGIN",source,evidence(op.line),json!({"position":position,"basis":"argument-origins/1","modality":modality})));
                }
            }
        }
        for (read, basis, order, pending) in [
            (
                "READ_ORIGIN",
                "evaluated-read-input/1",
                &self.read_order,
                &self.read_pending,
            ),
            (
                "ASSIGNMENT_ORIGIN",
                "evaluated-assignment-input/1",
                &self.assignment_order,
                &self.assignment_pending,
            ),
        ] {
            for id in order {
                let origins = pending[id].iter().map(|(v, _)| v).collect::<BTreeSet<_>>();
                let op = self.input.ctx.op(self.input.ctx.ids[id.as_str()]);
                for origin in origins.iter().filter_map(|v| v.as_ref()) {
                    output.push(fact(
                        id,
                        read,
                        origin,
                        evidence(op.line),
                        json!({"basis":basis,"modality":if origins.len()==1{"must"}else{"may"}}),
                    ));
                }
            }
        }
        for expression in &self.expression_order {
            for (position, cases) in &self.expression_pending[expression] {
                let origins = cases.iter().map(|(v, _)| v).collect::<BTreeSet<_>>();
                for origin in origins.iter().filter_map(|v| v.as_ref()) {
                    output.push(fact(expression,"VALUE_DEPENDS_ON",origin,evidence(entity.line),json!({"position":position,"basis":"evaluated-expression-inputs/1","modality":if origins.len()==1{"must"}else{"may"}})));
                }
            }
        }
        for ((returned, origin, field, write), count) in &self.field_returns {
            let tuple = format!("({}, {}, {})", repr(origin), repr(field), repr(write));
            let hash = format!("{:x}", Sha256::digest(tuple.as_bytes()));
            let state = format!("{returned}/field-state/{}", &hash[..24]);
            let ev = evidence(self.input.ctx.op(self.input.ctx.ids[write.as_str()]).line);
            output.push(fact(returned,"RETURN_FIELD_STATE",&state,ev.clone(),json!({"analysis":"structured-locals/3","basis":"flow","modality":if *count==self.return_states[returned]{"must"}else{"may"},"field":field})));
            output.push(fact(
                &state,
                "FIELD_STATE_ORIGIN",
                origin,
                ev.clone(),
                json!({}),
            ));
            output.push(fact(&state, "FIELD_STATE_WRITE", write, ev, json!({})));
        }
        Ok(())
    }
}
