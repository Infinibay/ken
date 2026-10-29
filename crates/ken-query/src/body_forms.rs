//! Focused grammar productions, called after contextual dispatch.
use crate::{Result, ast::*, parser::Parser};
impl Parser<'_> {
    pub(crate) fn form_body_macro(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.role = self.role()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_initializer(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.blocks.push(self.block("body")?);
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_adjacent(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_let(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.role = self.role()?;
        self.expect("=")?;
        if self.peek()? == "construct" {
            c.blocks.push(vec![self.construct()?]);
        } else if self.peek()? == "call" {
            c.blocks.push(vec![self.call()?]);
        } else {
            c.expressions.push(self.expr(true, 0)?);
        }
        if self.accept("writes")? {
            self.expect(":")?;
            c.name = self.take()?.text;
        }
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_clear(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.role = self.role()?;
        if self.accept("after")? {
            c.name = self.role()?;
        }
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_call(&mut self, _word: &str, start: &Span) -> Result<Clause> {
        self.rewind(start.start);
        let mut c = self.call()?;
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_resume(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.name = self.take()?.text;
        if !matches!(c.name.as_str(), "next" | "throw" | "close") {
            return Err(self.fail("resume requires next, throw or close"));
        }
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_jump(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        if word == "break" && self.peek()?.starts_with('$') {
            c.role = self.role()?;
            c.alias = self.alias()?;
            self.expect(";")?;
        } else {
            if word == "yield" && self.accept("from")? {
                c.flags.push("from".into());
            }
            if !(matches!(word, "break" | "continue")
                || word == "return" && matches!(self.peek()?.as_str(), ";" | "as" | "from"))
            {
                c.expressions.push(self.expr(true, 0)?);
            }
            if !matches!(word, "break" | "continue") {
                c.alias = self.alias()?;
            }
            if word == "return" && self.accept("from")? {
                let mut child = Clause::new("from", self.span(start));
                child.role = self.role()?;
                c.blocks.push(vec![child]);
            } else if word == "return" && self.peek()? == "copies" {
                self.take()?;
                let field = self.role()?;
                let mut child = Clause::new("copies", self.span(start));
                child.role = field;
                c.blocks.push(vec![child]);
            }
            self.expect(";")?;
        }
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_conditional(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut clauses = Vec::new();
        let mut at = start.clone();
        loop {
            self.chain_limit(clauses.len())?;
            let mut c = Clause::new(word, at.clone());
            self.expect("(")?;
            c.expressions.push(self.expr(true, 0)?);
            self.expect(")")?;
            c.alias = self.alias()?;
            c.blocks.push(self.block("body")?);
            if word == "if" && self.accept("else")? {
                if self.peek()? == "if" {
                    at = self.take()?.span;
                    clauses.push(c);
                    continue;
                }
                c.blocks.push(self.block("body")?);
            }
            return Ok(self.finish_chain(clauses, c));
        }
    }
    pub(crate) fn form_body_insert(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.expressions.push(self.expr(true, 0)?);
        self.expect("into")?;
        let place = self.expr(true, 100)?;
        match place {
            Expression::Source(ref p) if p.kind == "index" => {
                c.role = p.args[0].value().into();
                c.expressions.push(p.args[1].clone());
            }
            Expression::Source(ref p) if p.kind == "role" => {
                c.role = p.value.clone();
                if self.accept("at")? {
                    c.expressions.push(self.expr(true, 0)?);
                }
            }
            _ => return Err(self.fail("insert destination must be a place")),
        }
        if self.accept("writes")? {
            self.expect(":")?;
            c.name = self.take()?.text;
        }
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_for(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        if self.accept("{")? {
            self.expect("init")?;
            let init = self.block("body")?;
            self.expect("condition")?;
            c.expressions.push(self.expr(true, 0)?);
            self.expect(";")?;
            self.expect("step")?;
            let step = self.block("body")?;
            self.expect("body")?;
            let body = self.block("body")?;
            self.expect("}")?;
            c.kind = "for_c".into();
            c.blocks = vec![init, step, body];
        } else {
            c.role = self.role()?;
            self.expect("in")?;
            c.expressions.push(self.expr(true, 0)?);
            c.blocks.push(self.block("body")?);
        }
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_try(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.blocks.push(self.block("body")?);
        let mut catches = vec![];
        while self.accept("catch")? {
            let catch_start = self.last.clone();
            let role = self.role()?;
            let expressions = if self.accept("when")? {
                self.expect("(")?;
                let value = self.expr(true, 0)?;
                self.expect(")")?;
                vec![value]
            } else {
                vec![]
            };
            let body = self.block("body")?;
            let mut catch = Clause::new("catch", self.span(&catch_start));
            catch.role = role;
            catch.expressions = expressions;
            catch.blocks.push(body);
            catches.push(catch);
        }
        let has_catches = !catches.is_empty();
        c.blocks.push(catches);
        let otherwise = if self.accept("else")? {
            Some(self.block("body")?)
        } else {
            None
        };
        let final_block = if self.accept("finally")? {
            Some(self.block("body")?)
        } else {
            None
        };
        if !has_catches && (final_block.is_none() || otherwise.is_some()) {
            return Err(self.fail("try requires catch or finally; else requires catch"));
        }
        if otherwise.is_some() {
            c.flags.push("else".into());
        }
        if final_block.is_some() {
            c.flags.push("finally".into());
        }
        c.blocks.push(otherwise.unwrap_or_default());
        c.blocks.push(final_block.unwrap_or_default());
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_iterate(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        if self.accept("keys")? {
            self.expect("of")?;
            c.flags.push("keys".into());
        } else if self.accept("copy")? {
            self.expect("of")?;
            c.flags.push("copy".into());
        }
        c.expressions.push(self.expr(true, 0)?);
        self.expect("as")?;
        c.role = self.role()?;
        if self.accept("into")? {
            c.name = self.role()?;
        }
        c.alias = self.alias()?;
        let block = self.block("constraint")?;
        if block.iter().any(|c| {
            !matches!(
                c.kind.as_str(),
                "property" | "body" | "where" | "restriction"
            )
        }) {
            return Err(self.fail("invalid iteration constraint"));
        }
        c.blocks.push(block);
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_task(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.role = self.role()?;
        if word == "spawn" {
            self.expect("as")?;
            c.alias = self.role()?;
        }
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_channel(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        c.expressions.push(self.expr(true, 0)?);
        if word == "send" {
            self.expect("to")?;
            c.expressions.push(self.expr(true, 0)?);
        } else {
            self.expect("as")?;
            c.alias = self.role()?;
        }
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
    pub(crate) fn form_body_assignment(&mut self, word: &str, start: &Span) -> Result<Clause> {
        let mut c = Clause::new(word, start.clone());
        self.rewind(start.start);
        let place = self.expr(true, 100)?;
        if !matches!(place.kind(), "role" | "member" | "index") {
            return Err(self.fail("assignment requires a place"));
        }
        c.kind = "assign".into();
        c.name = self.take()?.text;
        if !matches!(c.name.as_str(), "=" | "+=" | "-=" | "*=" | "/=" | "%=") {
            return Err(self.fail("expected assignment operator"));
        }
        c.expressions.push(place);
        c.expressions.push(self.expr(true, 0)?);
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(start);
        Ok(c)
    }
}
