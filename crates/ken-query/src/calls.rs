//! Invocation and construction operands shared with BODY and initializers.
use crate::{Result, ast::*, parser::Parser};
impl Parser<'_> {
    pub fn call(&mut self) -> Result<Clause> {
        let start = self.expect("call")?.span;
        let mut c = Clause::new("call", start.clone());
        for flag in ["on", "qualify", "alongside"] {
            if self.accept(flag)? {
                c.flags.push(flag.into());
                break;
            }
        }
        c.role = self.role()?;
        if self.accept("[")? {
            let container = Expression::Source(
                crate::ast::source! {kind:"role".into(),span:start.clone(),value:c.role.clone(),args:vec![]},
            );
            let key = self.expr(true, 0)?;
            self.expect("]")?;
            c.expressions.push(Expression::Source(crate::ast::source!{kind:"index".into(),span:self.span(&start),value:String::new(),args:vec![container,key]}));
        }
        self.expect("{")?;
        let mut constraints = vec![];
        while self.peek()? != "}" {
            if self.peek()? == "argument" {
                constraints.push(self.argument()?);
            } else if self.peek()? == "argument_pack" {
                let arg_start = self.take()?.span;
                let pack = self.role()?;
                let mut constraint = Clause::new("argument_pack", self.span(&arg_start));
                constraint.role = pack;
                constraint.blocks.push(self.block("constraint")?);
                constraints.push(constraint);
            } else {
                let constraint = self.clause("constraint")?;
                if !matches!(constraint.kind.as_str(), "property" | "where") {
                    return Err(self.fail("invalid call constraint"));
                }
                constraints.push(constraint);
            }
        }
        self.expect("}")?;
        c.span = self.span(&start);
        c.blocks.push(constraints);
        Ok(c)
    }
    pub fn argument(&mut self) -> Result<Clause> {
        let start = self.take()?.span;
        let value = if self.peek()? == "from" {
            None
        } else {
            Some(self.expr(true, 0)?)
        };
        let derived = if self.accept("from")? {
            let span = self.span(&start);
            Some(Expression::Source(
                crate::ast::source! {kind:"from".into(),span:span,value:self.role()?,args:vec![]},
            ))
        } else {
            None
        };
        let parameter = if self.accept("for")? {
            self.role()?
        } else {
            String::new()
        };
        if parameter.is_empty() {
            self.expect("at")?;
        }
        let position = if !parameter.is_empty() {
            String::new()
        } else if self.accept("name")? {
            self.expect("(")?;
            let position = self.token("STRING")?.text;
            self.expect(")")?;
            position
        } else if self.accept("any")? {
            "any".into()
        } else {
            self.token("INTEGER")?.text
        };
        let alias = self.alias()?;
        self.expect(";")?;
        let mut c = Clause::new("argument", self.span(&start));
        c.name = position;
        c.role = parameter;
        c.alias = alias;
        c.expressions.extend(value);
        c.expressions.extend(derived);
        Ok(c)
    }
    pub fn construct(&mut self) -> Result<Clause> {
        let start = self.expect("construct")?.span;
        let role = self.role()?;
        self.expect("{")?;
        let mut constraints = vec![];
        while self.peek()? != "}" {
            if self.peek()? == "argument" {
                constraints.push(self.argument()?);
                continue;
            }
            if self.peek()? == "initializer" {
                let item_start = self.take()?.span;
                let place = self.role()?;
                let values = if self.accept("from")? {
                    vec![self.expr(true, 0)?]
                } else {
                    vec![]
                };
                let properties = if self.peek()? == "{" {
                    self.block("constraint")?
                } else {
                    vec![]
                };
                self.expect(";")?;
                let mut c = Clause::new("initializer", self.span(&item_start));
                c.role = place;
                c.expressions = values;
                c.blocks.push(properties);
                constraints.push(c);
                continue;
            }
            let c = self.clause("constraint")?;
            if !matches!(c.kind.as_str(), "property" | "where" | "argument") {
                return Err(self.fail("invalid construct constraint"));
            }
            constraints.push(c);
        }
        self.expect("}")?;
        let mut c = Clause::new("construct", self.span(&start));
        c.role = role;
        c.blocks.push(constraints);
        Ok(c)
    }
}
