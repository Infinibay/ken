//! Source selectors share one semantic service and keep open-world evidence.
use super::{
    ExecutionError, Result,
    engine::Engine,
    evidence::{Proof, Row},
    source::{Knowledge, SourceRuntime, Truth, attr, string},
    source_inventory::quantify,
    source_plan::{Filter, SourceOp},
};
use ken_program::value::GraphValue as V;
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
pub(super) fn bound<'a>(row: &'a Row, role: &str) -> Result<&'a str> {
    row.bindings
        .get(role)
        .map(String::as_str)
        .ok_or_else(|| ExecutionError::Invalid(format!("unbound source role {role}")))
}
pub(super) fn decimal(v: &str) -> Option<String> {
    let v = v.trim();
    let (negative, v) = v.strip_prefix('-').map_or((false, v), |s| (true, s));
    let v = v.strip_prefix('+').unwrap_or(v);
    if v.is_empty() || !v.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let digits = v.trim_start_matches('0');
    Some(if digits.is_empty() {
        "0".into()
    } else if negative {
        format!("-{digits}")
    } else {
        digits.into()
    })
}
/// Formatting with zero fractional digits expands the exact binary integer;
/// shortest round-trip display and converting the expected integer to f64 lose it.
fn float_integer(value: f64) -> Option<String> {
    value.is_finite().then(|| format!("{:.0}", value.trunc()))
}
pub(super) fn count_equal(value: &V, count: &str) -> bool {
    match value {
        V::Int(value) => decimal(value) == decimal(count),
        V::Bool(value) => decimal(if *value { "1" } else { "0" }) == decimal(count),
        V::Float(value) => {
            value.is_finite()
                && value.fract() == 0.0
                && float_integer(*value).and_then(|v| decimal(&v)) == decimal(count)
        }
        _ => false,
    }
}
fn accept(mut row: Row, truth: Truth, reason: &str, out: &mut Vec<Row>) {
    match truth {
        Knowledge::Known(false) => (),
        Knowledge::Known(true) => out.push(row),
        Knowledge::Unknown(_) => {
            row.unknown.insert(reason.into());
            out.push(row);
        }
    }
}
impl Engine<'_> {
    pub(super) fn with_source<T>(
        &mut self,
        f: impl FnOnce(&mut SourceRuntime<'_>) -> Result<T>,
    ) -> Result<T> {
        let graph = self.graph;
        let mut cache = std::mem::take(&mut self.source);
        let result = f(&mut SourceRuntime {
            graph,
            cache: &mut cache,
            tick: &mut || self.tick(),
        });
        self.source = cache;
        result
    }
    pub fn source_apply(&mut self, op: &SourceOp, row: Row, out: &mut Vec<Row>) -> Result<()> {
        match op {
            SourceOp::Initializer {
                binding,
                construct,
                target,
                output,
            } => {
                self.source_initializer(&row, binding, *construct, target, output.as_deref(), out)?
            }
            SourceOp::Usages {
                value,
                usage,
                filters,
            } => self.source_usages(&row, value, usage, filters, out)?,
            SourceOp::Filter { role, filter } => {
                let subject = bound(&row, role)?.to_owned();
                let (truth, reason) = self.with_source(|s| s.filter(&subject, filter, &row))?;
                accept(row, truth, reason, out);
            }
            SourceOp::Quantifier {
                quantifier,
                domain,
                owner,
                properties,
            } => {
                let owner = bound(&row, owner)?.to_owned();
                let spelling = properties
                    .iter()
                    .find(|(k, _)| k == "named")
                    .map(|(_, v)| bound(&row, v).map(str::to_owned))
                    .transpose()?;
                let (members, complete, values) = self.with_source(|s| {
                    s.inventory(domain, &owner, spelling.as_deref(), properties)
                })?;
                let truth = quantify(quantifier, &values, complete);
                let proof = json!({"subject":owner,"relation":"source_quantifier","object":quantifier,"declaration":domain,"members":members,"complete":complete,"constraints":properties.iter().cloned().collect::<BTreeMap<_,_>>()});
                let row = Row {
                    evidence: row.append(Proof::Source(Arc::new(proof))),
                    ..row
                };
                accept(
                    row,
                    truth,
                    &format!("source_quantifier:{domain}:incomplete_inventory"),
                    out,
                );
            }
            SourceOp::EffectiveField {
                owner,
                field,
                attrs,
                matcher,
                nominal,
                declaration,
            } => {
                let owner = bound(&row, owner)?.to_owned();
                let visible = self.with_source(|s| s.visible(&owner))?;
                for place in visible {
                    self.tick()?;
                    if row.bindings.get(field).is_some_and(|v| v != &place.access) {
                        continue;
                    }
                    let mut bindings = row.bindings.clone();
                    bindings.insert(field.clone(), place.access.clone());
                    let mut unknown = row.unknown.clone();
                    let id = place.declaration.as_deref().unwrap_or(&place.access);
                    let entity = self.graph.entity(id)?.ok_or_else(|| {
                        ExecutionError::Invalid("effective field entity missing".into())
                    })?;
                    if let Some(reason) = place.reason {
                        unknown.insert(format!("effective_field:{reason}"));
                    }
                    if let Some(role) = declaration {
                        if bindings
                            .get(role)
                            .is_some_and(|v| place.declaration.as_ref().is_some_and(|d| v != d))
                        {
                            continue;
                        }
                        bindings.insert(
                            role.clone(),
                            place.declaration.clone().unwrap_or_else(|| {
                                format!("unknown:effective-field-declaration:{}", place.access)
                            }),
                        );
                    }
                    if place.reason.is_none() {
                        let mut accepted = true;
                        for (key, op, value) in attrs {
                            self.tick()?;
                            let actual = if key == "name" {
                                V::String(entity.name.as_str().into())
                            } else {
                                attr(&entity.attrs, key)?
                            };
                            if !self.comparisons.compare(&actual, op, value)? {
                                accepted = false;
                                break;
                            }
                        }
                        if !accepted {
                            continue;
                        }
                    }
                    if let Some(role) = nominal {
                        let types = if let Some(id) = &place.declaration {
                            self.with_source(|s| {
                                Ok(s.rows("TYPE", Some(id), None)?
                                    .iter()
                                    .map(|f| f.object.clone())
                                    .collect::<BTreeSet<_>>())
                            })?
                        } else {
                            BTreeSet::new()
                        };
                        if place.reason.is_some() || types.is_empty() {
                            bindings.entry(role.clone()).or_insert_with(|| {
                                format!("unknown:effective-field-type:{}", place.access)
                            });
                            unknown.insert("effective_field:type_unknown".into());
                        } else if let Some(v) = bindings.get(role) {
                            if !types.contains(v) {
                                continue;
                            }
                        } else if types.len() == 1 {
                            bindings.insert(role.clone(), types.first().unwrap().clone());
                        } else {
                            bindings.insert(
                                role.clone(),
                                format!("unknown:effective-field-type:{}", place.access),
                            );
                            unknown.insert("effective_field:type_ambiguous".into());
                        }
                    } else if let Some(matcher) = matcher
                        && place.reason.is_none()
                    {
                        let truth = self.with_source(|s| {
                            let actual =
                                s.type_of(place.declaration.as_deref().unwrap_or(""), false)?;
                            s.matches(&actual, matcher)
                        })?;
                        match truth {
                            Knowledge::Known(false) => continue,
                            Knowledge::Unknown(_) => {
                                unknown.insert("effective_field:type_unknown".into());
                            }
                            _ => (),
                        }
                    }
                    let proof = json!({"effective_field":place.access,"declaration":place.declaration,"ancestry":place.chain,"basis":"lexical-field-declaration"});
                    out.push(Row {
                        bindings,
                        evidence: row.append(Proof::Source(Arc::new(proof))),
                        unknown,
                    });
                }
            }
        }
        Ok(())
    }
}
impl SourceRuntime<'_> {
    fn filter(&mut self, id: &str, filter: &Filter, row: &Row) -> Result<(Truth, &'static str)> {
        Ok(match filter {
            Filter::Type { returns, matcher } => {
                let actual = self.type_of(id, *returns)?;
                (self.matches(&actual, matcher)?, "source_type:unknown")
            }
            Filter::Status { returns, known } => {
                let actual = self.type_of(id, *returns)?;
                (
                    Knowledge::Known(matches!(actual, Knowledge::Known(_)) == *known),
                    "source_type:unknown",
                )
            }
            Filter::Initial => {
                let statuses = self.rows("FIELD_INITIAL_STATUS", Some(id), None)?;
                let values = self.rows("FIELD_INITIAL_VALUE", Some(id), None)?;
                let truth = if statuses.is_empty()
                    || statuses.iter().any(|f| f.object != "supported")
                    || values.len() != 1
                {
                    Knowledge::Unknown("source_storage")
                } else {
                    Knowledge::Known(values[0].object == "NULL")
                };
                (truth, "source_storage:unknown")
            }
            Filter::Writes { binding, count } => {
                let binding = bound(row, binding)?;
                let statuses = self.rows("BINDING_WRITE_STATUS", Some(id), None)?;
                let truth =
                    if !statuses.is_empty() && statuses.iter().all(|f| f.object == "supported") {
                        let counts = self.rows("BINDING_WRITE_COUNT", Some(id), Some(binding))?;
                        if counts.len() != 1 {
                            Knowledge::Unknown("binding_write_count")
                        } else {
                            let actual = attr(&counts[0].attrs, "count")?;
                            Knowledge::Known(count_equal(&actual, count))
                        }
                    } else {
                        let statuses = self.rows("STORAGE_WRITE_STATUS", Some(binding), None)?;
                        let counts = self.rows("STORAGE_WRITE_COUNT", Some(binding), None)?;
                        if statuses.is_empty()
                            || statuses.iter().any(|f| f.object != "supported")
                            || counts.len() != 1
                        {
                            Knowledge::Unknown("storage_write_count")
                        } else {
                            let value = if counts[0].attrs.contains_key("count") {
                                attr(&counts[0].attrs, "count")?
                            } else {
                                V::String(counts[0].object.as_str().into())
                            };
                            let value = match value {
                                V::String(v) => v.to_utf8().unwrap_or_default(),
                                V::Int(v) => v,
                                V::Bool(v) => {
                                    if v {
                                        "1".into()
                                    } else {
                                        "0".into()
                                    }
                                }
                                V::Float(v) => float_integer(v).unwrap_or_default(),
                                _ => String::new(),
                            };
                            match decimal(&value) {
                                Some(value) => Knowledge::Known(Some(value) == decimal(count)),
                                None => Knowledge::Unknown("storage_write_count"),
                            }
                        }
                    };
                (truth, "source_storage:unknown")
            }
            Filter::Reassigned(expected) => {
                let statuses = self.rows("STORAGE_WRITE_STATUS", Some(id), None)?;
                let counts = self.rows("STORAGE_WRITE_COUNT", Some(id), None)?;
                let truth = if statuses.is_empty()
                    || statuses.iter().any(|f| f.object != "supported")
                    || counts.len() != 1
                {
                    Knowledge::Unknown("parameter_writes")
                } else if let Some(n) = decimal(&counts[0].object) {
                    Knowledge::Known((n != "0" && !n.starts_with('-')) == *expected)
                } else {
                    Knowledge::Unknown("parameter_writes")
                };
                (truth, "parameter_writes:unknown")
            }
            Filter::Completes(expected) => {
                let mut bodies = vec![];
                for f in self.rows("HAS_OPERATION", Some(id), None)? {
                    if self
                        .rows("OPERATION", Some(&f.object), None)?
                        .iter()
                        .any(|f| string(&f.attrs, "role").ok().flatten().as_deref() == Some("body"))
                    {
                        bodies.push(f.object.clone());
                    }
                }
                let mut completions = BTreeSet::new();
                for body in &bodies {
                    for f in self.rows("NORMAL_COMPLETION", Some(body), None)? {
                        completions.insert(f.object.clone());
                    }
                }
                let truth = if bodies.len() != 1 || completions.is_empty() {
                    Knowledge::Unknown("normal_completion")
                } else {
                    Knowledge::Known(completions.contains("possible") == *expected)
                };
                (truth, "normal_completion:unknown")
            }
            Filter::Escapes { owner, expected } => {
                let truth =
                    self.receiver_escape(bound(row, owner)?, id, 0, &mut BTreeSet::new())?;
                (
                    match truth {
                        Knowledge::Known(v) => Knowledge::Known(v == *expected),
                        Knowledge::Unknown(r) => Knowledge::Unknown(r),
                    },
                    "receiver_escape:unknown",
                )
            }
        })
    }
}
