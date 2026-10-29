//! Focused grammar productions, called after contextual dispatch.
use crate::{Result, ast::*, parser::Parser};
impl Parser<'_> {
    pub(crate) fn form_initializer(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        self.expect("{")?;
        let mut expression = if self.peek()? == "construct" {
            self.construct()?
        } else if self.accept("call")? {
            let role = self.role()?;
            let blocks = vec![self.block("constraint")?];
            let mut expression = Clause::new("call", start.clone());
            expression.role = role;
            expression.blocks = blocks;
            expression
        } else {
            return Err(self.fail("declaration initializer requires construct or call expression"));
        };
        expression.alias = self.alias()?;
        self.expect(";")?;
        self.expect("}")?;
        c.kind = "declaration_initializer".into();
        c.blocks = vec![vec![expression]];
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_usages(&mut self, word: String, start: Span, mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.kind = "source_usages".into();
        if mode == "body" {
            return Err(self.fail("usages selects consumers outside BODY"));
        }
        self.expect("of")?;
        c.name = self.role()?;
        self.expect("as")?;
        c.role = self.role()?;
        c.blocks.push(self.block("constraint")?);
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_require(&mut self, word: String, start: Span, mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.kind = "source_require".into();
        if mode == "body" {
            return Err(self.fail("source requirements belong outside BODY"));
        }
        let quantifier = self.take()?.text;
        if !matches!(quantifier.as_str(), "exists" | "every" | "one") {
            return Err(self.fail("require accepts exists, every or one"));
        }
        let declaration = self.take()?.text;
        if quantifier == "one" {
            if !matches!(declaration.as_str(), "allocation" | "dispatch") {
                return Err(self.fail("one quantifies the resolved allocation or dispatch count"));
            }
        } else if declaration != "constructor" {
            return Err(self.fail("quantified source declarations currently support constructor"));
        }
        self.expect("of")?;
        c.role = self.role()?;
        let witness = if self.accept("named")? {
            if quantifier != "one" || declaration != "dispatch" {
                return Err(self.fail("named qualifies only one dispatch"));
            }
            self.role()?
        } else {
            String::new()
        };
        c.blocks
            .push(if matches!(quantifier.as_str(), "exists" | "one") {
                self.expect(";")?;
                vec![]
            } else {
                self.block("constraint")?
            });
        c.name = declaration;
        c.flags = vec![quantifier, witness];
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_edge(&mut self, word: String, start: Span, _mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.name = self.ident(false)?;
        self.expect("(")?;
        c.expressions.push(self.expr(false, 31)?);
        self.expect(",")?;
        c.expressions.push(self.expr(false, 31)?);
        self.expect(")")?;
        c.blocks.push(if self.peek()? == "{" {
            self.block("constraint")?
        } else {
            vec![]
        });
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_tally(&mut self, word: String, start: Span, _mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        self.expect("distinct")?;
        c.role = self.role()?;
        c.name = self.take()?.text;
        if !matches!(c.name.as_str(), "==" | "<=" | ">=" | "<" | ">") {
            return Err(self.fail("tally requires a count comparison"));
        }
        c.flags.push(self.token("INTEGER")?.text);
        c.blocks.push(self.block("constraint")?);
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_at_least(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        self.expect("least")?;
        let count = self.token("INTEGER")?.text;
        self.expect("distinct")?;
        c.role = self.role()?;
        c.blocks.push(self.block("constraint")?);
        self.expect(";")?;
        c.kind = "count".into();
        c.name = ">=".into();
        c.flags.push(count);
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_from(&mut self, word: String, start: Span, _mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.parameters = self.parameters(";", false)?;
        if c.parameters.is_empty() {
            return Err(self.fail("from requires a domain"));
        }
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_condition(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        if word == "bind" {
            c.role = self.role()?;
            self.expect("=")?;
        }
        c.expressions.push(self.expr(false, 0)?);
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_use(&mut self, word: String, start: Span, _mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.name = self.qualified()?;
        if self.accept("<")? {
            c.flags.push(self.qualified()?);
            while self.accept(",")? {
                c.flags.push(self.qualified()?);
            }
            self.expect(">")?;
        }
        c.expressions = self
            .arguments(true)?
            .into_iter()
            .map(Expression::Query)
            .collect();
        c.alias = self.alias()?;
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_alternatives(
        &mut self,
        word: String,
        start: Span,
        mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        let nested = if mode == "body" { "body" } else { "constraint" };
        if word == "not" {
            self.expect("exists")?;
        }
        c.blocks
            .push(self.block(if mode == "body" && word == "either" {
                "body"
            } else {
                "constraint"
            })?);
        if word == "either" {
            self.expect("or")?;
            c.blocks.push(self.block(nested)?);
            while self.accept("or")? {
                c.blocks.push(self.block(nested)?);
            }
        }
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_projection(
        &mut self,
        word: String,
        start: Span,
        mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        if mode != "query" {
            return Err(self.fail(format!("{word} only allowed in query")));
        }
        if word == "limit" {
            c.name = self.token("INTEGER")?.text;
            self.expect(";")?;
        } else {
            if word == "order" {
                self.expect("by")?;
            }
            loop {
                let expression = self.query_expr(0)?;
                let suffix = if word == "select" && self.accept("as")? {
                    self.ident(false)?
                } else if word == "order" {
                    if matches!(self.peek()?.as_str(), "asc" | "desc") {
                        self.take()?.text
                    } else {
                        "asc".into()
                    }
                } else {
                    String::new()
                };
                c.expressions.push(Expression::Query(crate::ast::query!{kind:"projection".into(),span:expression.span.clone(),value:suffix,args:vec![expression],parameters:vec![]}));
                if !self.accept(",")? {
                    break;
                }
            }
            self.expect(";")?;
        }
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_inventory(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        if matches!(word.as_str(), "fields" | "parameters") && self.accept("exact")? {
            c.flags.push("exact".into());
        }
        if word == "body" {
            if self.accept("adjacent")? {
                c.flags.push("adjacent".into());
            } else if self.accept("linear")? {
                c.flags.push("linear".into());
            }
        }
        if word == "fragment" {
            c.role = self.role()?;
        }
        c.blocks
            .push(self.block(if matches!(word.as_str(), "body" | "fragment") {
                "body"
            } else {
                "constraint"
            })?);
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_exposes(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        c.role = self.role()?;
        self.expect(";")?;
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_interval(
        &mut self,
        word: String,
        start: Span,
        _mode: &str,
    ) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        if word == "restriction" {
            self.expect("between")?;
            c.expressions.push(Expression::Query(self.point()?));
            self.expect("and")?;
            c.expressions.push(Expression::Query(self.point()?));
        } else {
            self.expect("until")?;
            let endpoint = self.take()?.text;
            if !matches!(endpoint.as_str(), "next" | "exit") {
                return Err(self.fail("gap endpoint must be next or exit"));
            }
            if endpoint == "exit" {
                c.flags.push("exit".into());
            }
        }
        c.blocks.push(self.block("effect")?);
        c.span = self.span(&start);
        Ok(c)
    }
    pub(crate) fn form_effect(&mut self, word: String, start: Span, _mode: &str) -> Result<Clause> {
        let mut c = Clause::new(&word, start.clone());
        let expression = self.expr(false, 0)?;
        if expression.kind() != "call" {
            return Err(self.fail("effect constraint requires an application"));
        }
        self.expect(";")?;
        c.expressions.push(expression);
        c.span = self.span(&start);
        Ok(c)
    }
}
