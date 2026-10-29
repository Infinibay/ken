//! Flat else chains are assembled backwards instead of consuming host stack frames.
use crate::{ParseError, Result, ast::*, parser::Parser};
impl Parser<'_> {
    pub(crate) fn chain_limit(&mut self, length: usize) -> Result<()> {
        if length + self.call_depth >= MAX_AST_DEPTH {
            return Err(ParseError::resource(
                "syntax nesting limit exceeded",
                self.here()?,
            ));
        }
        Ok(())
    }
    pub(crate) fn finish_chain(&self, parents: Vec<Clause>, mut tail: Clause) -> Clause {
        tail.span = self.span(&tail.span);
        for mut parent in parents.into_iter().rev() {
            parent.span = self.span(&parent.span);
            parent.blocks.push(vec![tail]);
            tail = parent;
        }
        tail
    }
    pub(crate) fn form_when(&mut self, nested: &str) -> Result<Clause> {
        let mut clauses = Vec::new();
        loop {
            self.chain_limit(clauses.len())?;
            let start = self.take()?.span;
            let condition = self.expr(false, 0)?;
            let mut c = Clause::new("when", start);
            c.expressions.push(condition);
            c.blocks.push(self.block(nested)?);
            if self.accept("else")? {
                if self.peek()? == "when" {
                    clauses.push(c);
                    continue;
                }
                c.blocks.push(self.block(nested)?);
            }
            return Ok(self.finish_chain(clauses, c));
        }
    }
}
