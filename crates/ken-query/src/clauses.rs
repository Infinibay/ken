//! Context decides whether a spelling is a property, selector or BODY operation.
use crate::{
    Result,
    ast::*,
    parser::{Parser, quote, selector},
};
impl Parser<'_> {
    pub fn clause_inner(&mut self, mode: &str) -> Result<Clause> {
        let start = self.here()?;
        let word = self.peek()?;
        let nested = if mode == "body" { "body" } else { "constraint" };
        if self.kind()? == "IDENT" {
            let mark = self.mark()?;
            let first = self.take()?;
            if self.accept(":")? {
                if matches!(mode, "query" | "body") {
                    return Err(self.fail("property needs a selector or constraint block"));
                }
                let value = self.matcher()?;
                self.expect(";")?;
                let mut c = Clause::new("property", self.span(&start));
                c.name = first.text;
                c.expressions.push(Expression::Query(value));
                return Ok(c);
            }
            self.reset(mark);
        }
        if word == "{" {
            let mut blocks = vec![self.block(nested)?];
            self.expect("or")?;
            blocks.push(self.block(nested)?);
            while self.accept("or")? {
                blocks.push(self.block(nested)?);
            }
            let mut c = Clause::new("either", self.span(&start));
            c.blocks = blocks;
            return Ok(c);
        }
        if word == "when" {
            return self.form_when(nested);
        }
        if mode == "effect" && !matches!(word.as_str(), "forbid" | "preserve") {
            return Err(self.fail("effect block accepts properties, forbid and preserve"));
        }
        if word == "type_parameter" {
            if mode == "body" {
                return Err(self.fail("type parameters belong to a declaration block"));
            }
            self.take()?;
            let role = self.role()?;
            let block = if self.peek()? == "{" {
                self.block("constraint")?
            } else {
                vec![]
            };
            self.expect(";")?;
            let mut c = Clause::new("selector", self.span(&start));
            c.name = "type_parameter".into();
            c.role = role;
            c.blocks.push(block);
            return Ok(c);
        }
        if selector(&word) && !(word == "macro" && mode == "body")
            || word == "call" && mode != "body"
        {
            self.take()?;
            let role = self.role()?;
            let block = self.block("constraint")?;
            let alias = self.alias()?;
            if !alias.is_empty() {
                self.expect(";")?;
            }
            let mut c = Clause::new("selector", self.span(&start));
            c.name = word;
            c.role = role;
            c.blocks.push(block);
            c.alias = alias;
            return Ok(c);
        }
        self.take()?;
        match word.as_str() {
            "initializer" if mode != "body" => self.form_initializer(word, start, mode),
            "usages" => self.form_usages(word, start, mode),
            "require" => self.form_require(word, start, mode),
            "edge" | "walk" => self.form_edge(word, start, mode),
            "tally" => self.form_tally(word, start, mode),
            "at" => self.form_at_least(word, start, mode),
            "from" => self.form_from(word, start, mode),
            "where" | "bind" => self.form_condition(word, start, mode),
            "use" => self.form_use(word, start, mode),
            "either" | "not" | "optional" => self.form_alternatives(word, start, mode),
            "select" | "order" | "limit" => self.form_projection(word, start, mode),
            "return" if mode != "body" => {
                Err(self.fail("return requires a callable BODY block: callable $owner { body { return $value; } }. Bind $value inside BODY and use --backend indexed."))
            }
            _ if mode == "query" => {
                Err(self.fail(format!("{} is not a query clause", quote(&word))))
            }
            "fields" | "parameters" | "body" | "syntax" | "fragment" => {
                self.form_inventory(word, start, mode)
            }
            "exposes" => self.form_exposes(word, start, mode),
            "restriction" | "gap" => self.form_interval(word, start, mode),
            "forbid" | "preserve" if mode == "effect" => self.form_effect(word, start, mode),
            _ if mode != "body" => {
                Err(self.fail(format!("unexpected constraint {}", quote(&word))))
            }
            _ => self.body_clause(&word, &start),
        }
    }
}
