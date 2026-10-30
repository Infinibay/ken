//! Immutable checked indexed plans; no project, graph or database identities.
use crate::{Predicate, PythonRepr, ast::*};
use serde::Serialize;
use std::fmt::{self, Write};
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Scan {
    pub role: String,
    pub selector: String,
    pub owner: Option<String>,
    pub properties: Vec<(String, Expr)>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Action {
    pub role: String,
    pub expression: Expr,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct BodyPattern {
    pub owner: String,
    pub clauses: Vec<Clause>,
    pub adjacent: bool,
    pub outputs: Vec<String>,
    pub nested: Vec<(Clause, BodyPattern)>,
    pub controls: Vec<(Clause, Vec<BodyPattern>)>,
    pub linear: bool,
    pub call_aliases: Vec<String>,
}
impl BodyPattern {
    pub(crate) fn empty(owner: &str) -> Self {
        Self {
            owner: owner.into(),
            clauses: vec![],
            adjacent: false,
            outputs: vec![],
            nested: vec![],
            controls: vec![],
            linear: false,
            call_aliases: vec![],
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum Step {
    Scan(Scan),
    Action(Action),
    Body(BodyPattern),
}
#[derive(Clone, Debug, Serialize)]
#[serde(transparent)]
pub struct IntegerLiteral(Box<serde_json::value::RawValue>);
impl IntegerLiteral {
    pub fn digits(&self) -> &str {
        self.0.get()
    }
    pub(crate) fn from_digits(text: &str) -> Self {
        let digits = text.trim_start_matches('0');
        Self(
            serde_json::value::RawValue::from_string(if digits.is_empty() {
                "0".into()
            } else {
                digits.into()
            })
            .expect("validated integer literal"),
        )
    }
}
impl PartialEq for IntegerLiteral {
    fn eq(&self, other: &Self) -> bool {
        self.digits() == other.digits()
    }
}
impl Eq for IntegerLiteral {}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__", rename = "Program")]
pub struct Program {
    pub name: String,
    pub scans: Vec<Scan>,
    pub filters: Vec<Expr>,
    pub projection: Vec<Expr>,
    pub ordering: Vec<Expr>,
    pub limit: Option<IntegerLiteral>,
    pub fingerprint: String,
    pub branches: Vec<Program>,
    pub actions: Vec<(String, Expr)>,
    pub predicates: Vec<Predicate>,
    pub optional: Vec<Expr>,
    pub enums: Vec<(String, Vec<String>)>,
    pub steps: Vec<Step>,
    pub graph: Vec<Declaration>,
}
impl PythonRepr for bool {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_str(if *self { "True" } else { "False" })
    }
}
impl PythonRepr for IntegerLiteral {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_str(self.digits())
    }
}
macro_rules! record {($ty:ident,$name:literal,$($field:ident),+)=>{impl PythonRepr for $ty{fn write_python_repr(&self,out:&mut dyn Write)->fmt::Result{crate::with_stack(||crate::repr::record(out,$name,&[$((stringify!($field),&self.$field)),+]))}}};}
record!(Scan, "Scan", role, selector, owner, properties);
record!(Action, "Action", role, expression);
record!(
    BodyPattern,
    "BodyPattern",
    owner,
    clauses,
    adjacent,
    outputs,
    nested,
    controls,
    linear,
    call_aliases
);
record!(
    Program,
    "Program",
    name,
    scans,
    filters,
    projection,
    ordering,
    limit,
    fingerprint,
    branches,
    actions,
    predicates,
    optional,
    enums,
    steps,
    graph
);
impl PythonRepr for Step {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        match self {
            Self::Scan(v) => v.write_python_repr(out),
            Self::Action(v) => v.write_python_repr(out),
            Self::Body(v) => v.write_python_repr(out),
        }
    }
}
struct List<'a, T>(&'a [T]);
impl<T: PythonRepr> PythonRepr for List<'_, T> {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_char('[')?;
        for (i, v) in self.0.iter().enumerate() {
            if i > 0 {
                out.write_str(", ")?;
            }
            v.write_python_repr(out)?;
        }
        out.write_char(']')
    }
}
struct Enums<'a>(&'a [(String, Vec<String>)]);
impl PythonRepr for Enums<'_> {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_char('{')?;
        for (i, (k, v)) in self.0.iter().enumerate() {
            if i > 0 {
                out.write_str(", ")?;
            }
            k.write_python_repr(out)?;
            out.write_str(": ")?;
            v.write_python_repr(out)?;
        }
        out.write_char('}')
    }
}
impl Program {
    pub(crate) fn compute_fingerprint(&mut self) {
        use sha2::{Digest, Sha256};
        let mut out = String::from("(");
        let fields: [&dyn PythonRepr; 10] = [
            &List(&self.scans),
            &List(&self.filters),
            &self.projection,
            &self.ordering,
            &self.limit,
            &List(&self.actions),
            &self.predicates,
            &List(&self.optional),
            &Enums(&self.enums),
            &List(&self.steps),
        ];
        for (i, v) in fields.iter().enumerate() {
            if i > 0 {
                out.push_str(", ");
            }
            v.write_python_repr(&mut out).expect("string formatting");
        }
        out.push(')');
        self.fingerprint = format!("{:x}", Sha256::digest(out.as_bytes()));
    }
}

/// Compatibility name for the indexed compiler's shared program metadata.
pub type IndexedProgram = Program;
