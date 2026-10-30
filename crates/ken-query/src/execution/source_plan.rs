//! Validate source operator records before any graph row is consumed.
use super::{ExecutionError, Result};
use crate::{
    ast::{Expr, Expression},
    relational::{PlanValue, Term},
};

#[derive(Clone)]
pub(super) enum SourceOp {
    Filter {
        role: String,
        filter: Filter,
    },
    Quantifier {
        quantifier: String,
        domain: String,
        owner: String,
        properties: Vec<(String, String)>,
    },
    EffectiveField {
        owner: String,
        field: String,
        attrs: Vec<(String, String, String)>,
        matcher: Option<Expr>,
        nominal: Option<String>,
        declaration: Option<String>,
    },
    Initializer {
        binding: String,
        construct: bool,
        target: String,
        output: Option<String>,
    },
    Usages {
        value: String,
        usage: String,
        filters: Vec<(String, String, String)>,
    },
}
#[derive(Clone)]
pub(super) enum Filter {
    Type { returns: bool, matcher: Expr },
    Status { returns: bool, known: bool },
    Initial,
    Writes { binding: String, count: String },
    Reassigned(bool),
    Completes(bool),
    Escapes { owner: String, expected: bool },
}
fn invalid() -> ExecutionError {
    ExecutionError::Invalid("invalid source operator record".into())
}
pub(super) fn tuple(v: &PlanValue, len: usize) -> Result<&[PlanValue]> {
    if let PlanValue::Tuple(v) = v
        && v.len() == len
    {
        Ok(v)
    } else {
        Err(invalid())
    }
}
pub(super) fn text(v: &PlanValue) -> Result<&str> {
    if let PlanValue::Term(Term::Text(v)) = v {
        Ok(v)
    } else {
        Err(invalid())
    }
}
fn role(v: &PlanValue) -> Result<String> {
    let s = text(v)?;
    if s.starts_with('$') && s.len() > 1 && !s.contains('.') {
        Ok(s.into())
    } else {
        Err(invalid())
    }
}
fn optional_role(v: &PlanValue) -> Result<Option<String>> {
    if matches!(v, PlanValue::None) || matches!(v,PlanValue::Term(Term::Text(s))if s.is_empty()) {
        Ok(None)
    } else {
        role(v).map(Some)
    }
}
fn expression(v: &PlanValue) -> Result<&Expr> {
    if let PlanValue::Expression(Expression::Query(v)) = v {
        Ok(v)
    } else {
        Err(invalid())
    }
}
fn literal(v: &Expr) -> Result<serde_json::Value> {
    if v.kind == "literal" && v.args.is_empty() {
        serde_json::from_str(&v.value).map_err(|_| invalid())
    } else {
        Err(invalid())
    }
}
fn boolean(v: &Expr) -> Result<bool> {
    literal(v)?.as_bool().ok_or_else(invalid)
}
fn matcher(v: &Expr) -> Result<Expr> {
    crate::source_matcher::validate_matcher(v)
        .map_err(|e| ExecutionError::Invalid(e.to_string()))?;
    Ok(v.clone())
}
impl SourceOp {
    pub fn prepare(&self, comparisons: &mut super::terms::Comparisons) -> Result<()> {
        let attrs = match self {
            Self::EffectiveField { attrs, .. } => attrs,
            Self::Usages { filters, .. } => filters,
            _ => return Ok(()),
        };
        for (_, op, value) in attrs {
            if op == "regex" {
                comparisons.prepare(value)?;
            }
        }
        Ok(())
    }
    pub fn parse(kind: &str, v: &PlanValue) -> Result<Self> {
        match kind {
            "source_initializer" => {
                let v = tuple(v, 4)?;
                let mode = text(&v[1])?;
                if !matches!(mode, "construct" | "call") {
                    return Err(invalid());
                }
                Ok(Self::Initializer {
                    binding: role(&v[0])?,
                    construct: mode == "construct",
                    target: role(&v[2])?,
                    output: optional_role(&v[3])?,
                })
            }
            "source_usages" => {
                let v = tuple(v, 3)?;
                let PlanValue::Tuple(filters) = &v[2] else {
                    return Err(invalid());
                };
                let mut out = vec![];
                let mut keys = std::collections::BTreeSet::new();
                for filter in filters {
                    let f = tuple(filter, 3)?;
                    let key = text(&f[0])?;
                    let op = text(&f[1])?;
                    let value = text(&f[2])?;
                    if !matches!(
                        key,
                        "kind" | "position" | "owner" | "consumer" | "path" | "line"
                    ) || !keys.insert(key)
                    {
                        return Err(invalid());
                    }
                    if op == "role" {
                        if !matches!(key, "owner" | "consumer")
                            || !value.starts_with('$')
                            || value.len() < 2
                        {
                            return Err(invalid());
                        }
                    } else {
                        super::plan::comparison(op)?;
                    }
                    out.push((key.into(), op.into(), value.into()));
                }
                Ok(Self::Usages {
                    value: role(&v[0])?,
                    usage: role(&v[1])?,
                    filters: out,
                })
            }
            "source_type" => {
                let PlanValue::Tuple(v) = v else {
                    return Err(invalid());
                };
                if !matches!(v.len(), 3 | 4) {
                    return Err(invalid());
                }
                let r = role(&v[0])?;
                let prop = text(&v[1])?;
                let e = expression(&v[2])?;
                if (prop == "escapes") != (v.len() == 4) {
                    return Err(invalid());
                }
                let filter = match prop {
                    "type" | "return_type" => Filter::Type {
                        returns: prop == "return_type",
                        matcher: matcher(e)?,
                    },
                    "type_status" | "return_type_status" => {
                        let val = if e.kind == "name" && e.args.is_empty() {
                            e.value.clone()
                        } else {
                            literal(e)?.as_str().ok_or_else(invalid)?.to_owned()
                        };
                        let val = val.as_str();
                        if !matches!(val, "known" | "unknown") {
                            return Err(invalid());
                        }
                        Filter::Status {
                            returns: prop == "return_type_status",
                            known: val == "known",
                        }
                    }
                    "initial" => {
                        if !literal(e)?.is_null() {
                            return Err(invalid());
                        }
                        Filter::Initial
                    }
                    "reassigned" => Filter::Reassigned(boolean(e)?),
                    "completes" => Filter::Completes(boolean(e)?),
                    "escapes" => Filter::Escapes {
                        owner: role(&v[3])?,
                        expected: boolean(e)?,
                    },
                    "writes" => {
                        if e.kind != "call"
                            || !matches!(e.value.as_str(), "exact" | "exactly")
                            || e.args.len() != 2
                            || e.args.iter().any(|a| {
                                a.kind != "argument" || !a.value.is_empty() || a.args.len() != 1
                            })
                        {
                            return Err(invalid());
                        }
                        let binding = &e.args[0].args[0];
                        let count = &e.args[1].args[0];
                        if binding.kind != "role"
                            || binding.value.is_empty()
                            || count.kind != "literal"
                            || count.value.is_empty()
                            || !count.value.bytes().all(|b| b.is_ascii_digit())
                        {
                            return Err(invalid());
                        }
                        Filter::Writes {
                            binding: format!("${}", binding.value),
                            count: count.value.clone(),
                        }
                    }
                    _ => return Err(invalid()),
                };
                Ok(Self::Filter { role: r, filter })
            }
            "source_quantifier" => {
                let v = tuple(v, 4)?;
                let quantifier = text(&v[0])?.to_owned();
                let domain = text(&v[1])?.to_owned();
                if !matches!(
                    (quantifier.as_str(), domain.as_str()),
                    ("one", "allocation" | "dispatch") | ("every" | "exists", "constructor")
                ) {
                    return Err(invalid());
                }
                let PlanValue::Tuple(props) = &v[3] else {
                    return Err(invalid());
                };
                let mut properties = vec![];
                for p in props {
                    let p = tuple(p, 2)?;
                    properties.push((text(&p[0])?.to_owned(), text(&p[1])?.to_owned()));
                }
                if domain == "constructor" {
                    if properties.len() > 1
                        || quantifier == "every" && properties.is_empty()
                        || properties.iter().any(|(k, v)| {
                            k != "visibility"
                                || !matches!(
                                    v.as_str(),
                                    "private" | "public" | "protected" | "internal" | "package"
                                )
                        })
                    {
                        return Err(invalid());
                    }
                } else if properties.first() != Some(&("count".into(), "1".into()))
                    || properties.len() > 2
                    || properties.get(1).is_some_and(|(k, v)| {
                        k != "named" || domain != "dispatch" || !v.starts_with('$') || v.len() < 2
                    })
                {
                    return Err(invalid());
                }
                Ok(Self::Quantifier {
                    quantifier,
                    domain,
                    owner: role(&v[2])?,
                    properties,
                })
            }
            "source_effective_field" => {
                let v = tuple(v, 6)?;
                let PlanValue::Tuple(attrs) = &v[2] else {
                    return Err(invalid());
                };
                let mut values = vec![];
                for a in attrs {
                    let a = tuple(a, 3)?;
                    let op = text(&a[1])?;
                    super::plan::comparison(op)?;
                    values.push((text(&a[0])?.into(), op.into(), text(&a[2])?.into()));
                }
                let m = if matches!(v[3], PlanValue::None) {
                    None
                } else {
                    Some(matcher(expression(&v[3])?)?)
                };
                let nominal = optional_role(&v[4])?;
                if nominal.is_some() && m.is_some() {
                    return Err(invalid());
                }
                Ok(Self::EffectiveField {
                    owner: role(&v[0])?,
                    field: role(&v[1])?,
                    attrs: values,
                    matcher: m,
                    nominal,
                    declaration: optional_role(&v[5])?,
                })
            }
            _ => Err(invalid()),
        }
    }
}
