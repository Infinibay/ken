//! Closed declaration inventories and three-valued finite quantifiers.
use super::source_operators::{count_equal, decimal};
use super::{
    ExecutionError, Result,
    source::{Knowledge, SourceRuntime, Truth, attr, string},
};
use ken_program::value::GraphValue as V;
use std::collections::BTreeSet;
impl SourceRuntime<'_> {
    fn spelling(&mut self, id: &str) -> Result<Option<String>> {
        if let Some(e) = self.entity(id)? {
            if !e.name.is_empty() {
                return Ok(Some(e.name.clone()));
            }
            if let Some(n) = string(&e.attrs, "name")?
                && !n.is_empty()
            {
                return Ok(Some(n));
            }
        }
        for f in self.rows("ENTITY", Some(id), None)? {
            if let Some(n) = string(&f.attrs, "name")?
                && !n.is_empty()
            {
                return Ok(Some(n));
            }
        }
        Ok(None)
    }
    pub(super) fn inventory(
        &mut self,
        domain: &str,
        owner: &str,
        witness: Option<&str>,
        properties: &[(String, String)],
    ) -> Result<(Vec<String>, bool, Vec<Truth>)> {
        let (members, complete) = match domain {
            "allocation" => {
                let rows = self.rows("RESOLVED_ALLOCATION_COUNT", Some(owner), None)?;
                let complete = rows.len() == 1
                    && string(&rows[0].attrs, "basis")?.as_deref()
                        == Some("explicit-resolved-sites");
                (
                    rows.iter().map(|f| f.object.clone()).collect::<Vec<_>>(),
                    complete,
                )
            }
            "dispatch" => {
                let name = if let Some(w) = witness {
                    self.spelling(w)?
                } else {
                    None
                }
                .or(self.spelling(owner)?);
                let mut count = 0;
                let mut known = name.is_some();
                for call in self.rows("HAS_CALL", Some(owner), None)? {
                    if string(&call.attrs, "execution")?.as_deref() != Some("possible") {
                        continue;
                    }
                    let Some(entity) = self.entity(&call.object)? else {
                        known = false;
                        break;
                    };
                    let callee = string(&entity.attrs, "name")?;
                    if callee.as_ref().is_none_or(String::is_empty) {
                        known = false;
                        break;
                    }
                    if callee == name {
                        count += 1;
                    }
                }
                let statuses = self.rows("CFG_STATUS", Some(owner), None)?;
                let complete = known
                    && statuses.len() == 1
                    && statuses[0].object == "structured"
                    && string(&statuses[0].attrs, "level")?.as_deref() == Some("statement");
                (
                    if complete {
                        vec![count.to_string()]
                    } else {
                        vec![]
                    },
                    complete,
                )
            }
            "constructor" => {
                let mut members = BTreeSet::new();
                for fact in self.rows("HAS_METHOD", Some(owner), None)? {
                    if let Some(e) = self.entity(&fact.object)?
                        && attr(&e.attrs, "instance_constructor")? == V::Bool(true)
                    {
                        members.insert(e.id.clone());
                    }
                }
                let statuses = self.rows("CONSTRUCTOR_INVENTORY", Some(owner), None)?;
                let complete = statuses.len() == 1
                    && statuses[0].object == "supported"
                    && count_equal(
                        &attr(&statuses[0].attrs, "explicit")?,
                        &members.len().to_string(),
                    );
                (members.into_iter().collect(), complete)
            }
            _ => unreachable!(),
        };
        let mut values = vec![];
        for member in &members {
            (self.tick)()?;
            if properties.first().is_some_and(|(k, _)| k == "count") {
                values.push(match decimal(member) {
                    Some(v) => Knowledge::Known(Some(v) == decimal(&properties[0].1)),
                    None => Knowledge::Unknown("invalid_count"),
                });
                continue;
            }
            let entity = self
                .entity(member)?
                .ok_or_else(|| ExecutionError::Invalid("constructor entity missing".into()))?;
            let mut truth = Knowledge::Known(true);
            for (key, expected) in properties {
                if key == "visibility" {
                    let actual = string(&entity.attrs, key)?;
                    let supported = string(&entity.attrs, "visibility_status")?.as_deref()
                        == Some("supported")
                        && actual.as_deref().is_some_and(|v| {
                            matches!(
                                v,
                                "private"
                                    | "public"
                                    | "protected"
                                    | "internal"
                                    | "package"
                                    | "internal protected"
                                    | "private protected"
                            )
                        });
                    truth = if supported {
                        Knowledge::Known(actual.as_ref() == Some(expected))
                    } else {
                        Knowledge::Unknown("visibility")
                    };
                }
            }
            values.push(truth);
        }
        Ok((members, complete, values))
    }
}
pub(super) fn quantify(q: &str, values: &[Truth], complete: bool) -> Truth {
    match q {
        "exists" => {
            if values.contains(&Knowledge::Known(true)) {
                Knowledge::Known(true)
            } else if complete && values.iter().all(|v| *v == Knowledge::Known(false)) {
                Knowledge::Known(false)
            } else {
                Knowledge::Unknown("inventory")
            }
        }
        "every" => {
            if values.contains(&Knowledge::Known(false)) {
                Knowledge::Known(false)
            } else if complete && values.iter().all(|v| *v == Knowledge::Known(true)) {
                Knowledge::Known(true)
            } else {
                Knowledge::Unknown("inventory")
            }
        }
        "one" => {
            if values.iter().any(|v| matches!(v, Knowledge::Unknown(_))) {
                Knowledge::Unknown("inventory")
            } else if values
                .iter()
                .filter(|v| **v == Knowledge::Known(true))
                .count()
                == 1
            {
                Knowledge::Known(true)
            } else if complete {
                Knowledge::Known(false)
            } else {
                Knowledge::Unknown("inventory")
            }
        }
        _ => unreachable!(),
    }
}
