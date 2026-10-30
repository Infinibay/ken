//! Bound materialization work before copying expanded ASTs into checked plans.
use crate::{ParseError, Result, ast::*, operands::Operand};
const MAX_WORK: usize = 65_536;
pub(crate) struct WorkBudget {
    used: usize,
    span: Span,
}
impl WorkBudget {
    pub fn new(span: &Span) -> Self {
        Self {
            used: 0,
            span: span.clone(),
        }
    }
    pub fn charge(&mut self, units: usize) -> Result<()> {
        self.used = self.used.saturating_add(units);
        if self.used > MAX_WORK {
            Err(ParseError::resource(
                "compilation work limit exceeded",
                self.span.clone(),
            ))
        } else {
            Ok(())
        }
    }
    pub fn header(&mut self, c: &Clause) -> Result<()> {
        self.charge(1 + (c.name.len() + c.role.len() + c.alias.len()) / 64)
    }
    pub fn expression(&mut self, e: Operand<'_>) -> Result<()> {
        let mut pending = vec![e];
        while let Some(e) = pending.pop() {
            self.charge(1 + e.value().len() / 64)?;
            self.charge(e.parameters().len())?;
            pending.extend(e.args());
        }
        Ok(())
    }
    pub fn clause(&mut self, c: &Clause) -> Result<()> {
        let mut pending = vec![c];
        while let Some(c) = pending.pop() {
            self.header(c)?;
            self.charge(c.parameters.len())?;
            for e in &c.expressions {
                self.expression(e.into())?;
            }
            pending.extend(c.blocks.iter().flatten());
        }
        Ok(())
    }
}
