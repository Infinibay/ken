//! Read-only traversal of the two expression dialects without erasing identity.
use crate::ast::*;
#[derive(Clone, Copy)]
pub(crate) enum Operand<'a> {
    Query(&'a Expr),
    Source(&'a SourceExpr),
}
impl<'a> From<&'a Expression> for Operand<'a> {
    fn from(e: &'a Expression) -> Self {
        match e {
            Expression::Query(e) => Self::Query(e),
            Expression::Source(e) => Self::Source(e),
        }
    }
}
pub(crate) enum Arguments<'a> {
    Query(std::slice::Iter<'a, Expr>),
    Source(std::slice::Iter<'a, Expression>),
}
impl<'a> Iterator for Arguments<'a> {
    type Item = Operand<'a>;
    fn next(&mut self) -> Option<Self::Item> {
        match self {
            Self::Query(v) => v.next().map(Operand::Query),
            Self::Source(v) => v.next().map(Operand::from),
        }
    }
}
impl<'a> Operand<'a> {
    pub fn kind(self) -> &'a str {
        match self {
            Self::Query(e) => &e.kind,
            Self::Source(e) => &e.kind,
        }
    }
    pub fn value(self) -> &'a str {
        match self {
            Self::Query(e) => &e.value,
            Self::Source(e) => &e.value,
        }
    }
    pub fn span(self) -> &'a Span {
        match self {
            Self::Query(e) => &e.span,
            Self::Source(e) => &e.span,
        }
    }
    pub fn args(self) -> Arguments<'a> {
        match self {
            Self::Query(e) => Arguments::Query(e.args.iter()),
            Self::Source(e) => Arguments::Source(e.args.iter()),
        }
    }
    pub fn len(self) -> usize {
        match self {
            Self::Query(e) => e.args.len(),
            Self::Source(e) => e.args.len(),
        }
    }
    pub fn arg(self, i: usize) -> Option<Self> {
        self.args().nth(i)
    }
    pub fn parameters(self) -> &'a [Parameter] {
        match self {
            Self::Query(e) => &e.parameters,
            Self::Source(_) => &[],
        }
    }
}
pub(crate) fn free(e: Operand<'_>) -> std::collections::BTreeSet<String> {
    crate::with_stack(|| {
        let mut found = std::collections::BTreeSet::new();
        if e.kind() == "role" {
            found.insert(e.value().into());
        }
        for arg in e.args() {
            found.extend(free(arg));
        }
        for p in e.parameters() {
            found.remove(&p.role);
        }
        found
    })
}
