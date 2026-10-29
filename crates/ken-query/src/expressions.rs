//! Two Pratt dialects share precedence, never AST expression identity.
use crate::{ParseError, Result, ast::*, parser::Parser};
impl Parser<'_> {
    pub fn node(
        &self,
        source: bool,
        start: &Span,
        kind: &str,
        value: impl Into<String>,
        args: Vec<Expression>,
    ) -> Result<Expression> {
        let span = self.span(start);
        let value = value.into();
        Ok(if source {
            Expression::Source(
                crate::ast::source! {kind:kind.into(),span:span,value:value,args:args},
            )
        } else {
            Expression::Query(
                crate::ast::query! {kind:kind.into(),span:span,value:value,args:args.into_iter().map(|e|match e{Expression::Query(e)=>e,Expression::Source(_)=>unreachable!("query calculations")}).collect(),parameters:vec![]},
            )
        })
    }

    pub fn query_expr(&mut self, bp: i32) -> Result<Expr> {
        match self.expr(false, bp)? {
            Expression::Query(e) => Ok(e),
            Expression::Source(e) => Err(ParseError::new("expected query expression", e.span)),
        }
    }
    pub fn expr(&mut self, source: bool, min_bp: i32) -> Result<Expression> {
        self.call_enter()?;
        self.enter()?;
        let result = crate::with_stack(|| self.expression_inner(source, min_bp));
        self.depth -= 1;
        self.call_depth -= 1;
        result
    }
    pub fn point(&mut self) -> Result<Expr> {
        let start = self.here()?;
        let role = self.role()?;
        self.expect(".")?;
        let point = self.ident(false)?;
        if !matches!(
            point.as_str(),
            "before" | "after" | "after_normal" | "after_exceptional" | "entry" | "exit"
        ) {
            return Err(self.fail("invalid point accessor"));
        }
        Ok(
            crate::ast::query! {kind:"member".into(),span:self.span(&start),value:point,args:vec![crate::ast::query!{kind:"role".into(),span:start,value:role,args:vec![],parameters:vec![]}],parameters:vec![]},
        )
    }
    pub fn matcher(&mut self) -> Result<Expr> {
        if self.peek()? == "/" {
            let t = self.lexer.regex()?;
            self.last = t.span.clone();
            return Ok(
                crate::ast::query! {kind:"regex".into(),span:t.span,value:t.text,args:vec![],parameters:vec![]},
            );
        }
        if self.kind()? == "IDENT" {
            let saved = self.lexer.peek()?.clone();
            let mark = self.mark()?;
            let name = self.qualified()?;
            if self.accept("<")? {
                let mut args = vec![self.type_argument()?];
                while self.accept(",")? {
                    args.push(self.type_argument()?);
                }
                self.expect(">")?;
                return Ok(
                    crate::ast::query! {kind:"source_type".into(),span:self.span(&saved.span),value:name,args:args,parameters:vec![]},
                );
            }
            self.reset(mark);
        }
        self.query_expr(0)
    }
    pub fn arguments(&mut self, named_only: bool) -> Result<Vec<Expr>> {
        self.expect("(")?;
        let mut args = vec![];
        if self.peek()? != ")" {
            loop {
                let mut name = String::new();
                if self.kind()? == "IDENT" {
                    let mark = self.mark()?;
                    let saved = self.take()?;
                    if self.accept(":")? {
                        name = saved.text;
                    } else {
                        self.reset(mark);
                    }
                }
                if named_only && name.is_empty() {
                    return Err(self.fail("use requires named arguments"));
                }
                let value = self.query_expr(31)?;
                args.push(crate::ast::query!{kind:"argument".into(),span:value.span.clone(),value:name,args:vec![value],parameters:vec![]});
                if !self.accept(",")? {
                    break;
                }
            }
        }
        self.expect(")")?;
        Ok(args)
    }
    fn expression_inner(&mut self, source: bool, min_bp: i32) -> Result<Expression> {
        let token = self.take()?;
        let mut origin = token.span.clone();
        let mut left;
        if matches!(token.text.as_str(), "not" | "+" | "-")
            || source && matches!(token.text.as_str(), "~" | "++" | "--")
        {
            let value = self.expr(source, 80)?;
            left = self.node(source, &origin, "unary", &token.text, vec![value])?;
        } else if matches!(token.kind, "STRING" | "INTEGER" | "FLOAT")
            || matches!(token.text.as_str(), "true" | "false" | "null" | "undefined")
        {
            left = self.node(source, &origin, "literal", &token.text, vec![])?;
        } else if token.kind == "ROLE" {
            left = self.node(source, &origin, "role", &token.text[1..], vec![])?;
        } else if token.text == "_" {
            left = self.node(source, &origin, "wildcard", "", vec![])?;
        } else if token.text == "(" {
            left = self.expr(source, 0)?;
            self.expect(")")?;
        } else if token.text == "[" && !source {
            let mut values = vec![];
            if self.peek()? != "]" {
                values.push(self.expr(false, 31)?);
                while self.accept(",")? {
                    values.push(self.expr(false, 31)?);
                }
            }
            self.expect("]")?;
            left = self.node(false, &origin, "list", "", values)?;
        } else if !source
            && matches!(
                token.text.as_str(),
                "exists" | "forall" | "count" | "sum" | "sum_by" | "min" | "max" | "avg"
            )
        {
            self.expect("(")?;
            let parameters = self.parameters("|", false)?;
            if parameters.is_empty() {
                return Err(self.fail("quantifier requires a finite domain"));
            }
            self.expect("|")?;
            let mut parts = vec![self.query_expr(0)?];
            if token.text != "exists" {
                self.expect("|")?;
                parts.push(self.query_expr(if token.text == "forall" { 0 } else { 31 })?);
            }
            self.expect(")")?;
            left = Expression::Query(
                crate::ast::query! {kind:if matches!(token.text.as_str(),"exists"|"forall"){"quantifier"}else{"aggregate"}.into(),span:self.span(&origin),value:token.text.clone(),args:parts,parameters:parameters},
            );
        } else if source && token.text == "new" {
            let role = self.role()?;
            let args = self
                .arguments(false)?
                .into_iter()
                .map(Expression::Query)
                .collect();
            left = self.node(true, &origin, "new", role, args)?;
        } else if token.kind == "IDENT" {
            let mut name = token.text.clone();
            while self.accept(".")? {
                name.push('.');
                name.push_str(&self.ident(false)?);
            }
            if self.peek()? == "(" {
                let args = self
                    .arguments(false)?
                    .into_iter()
                    .map(Expression::Query)
                    .collect();
                left = self.node(source, &origin, "call", name, args)?;
            } else if source {
                return Err(ParseError::new(
                    "source expressions require a role or application",
                    origin,
                ));
            } else {
                left = self.node(false, &origin, "name", name, vec![])?;
            }
        } else {
            return Err(ParseError::new(
                format!(
                    "expected expression, got {}",
                    crate::parser::quote(&token.text)
                ),
                origin,
            ));
        }
        let mut compared = false;
        loop {
            let mut op = self.peek()?;
            if op == "." {
                self.take()?;
                if self.peek()?.starts_with('$') {
                    let declaration = self.here()?;
                    let field = self.role()?;
                    let role = Expression::Query(
                        crate::ast::query! {kind:"role".into(),span:self.span(&declaration),value:field,args:vec![],parameters:vec![]},
                    );
                    left = self.node(source, &origin, "member", "", vec![left, role])?;
                    continue;
                }
                let member = self.ident(false)?;
                let mut args = vec![left];
                if !source && self.peek()? == "(" {
                    args.extend(self.arguments(false)?.into_iter().map(Expression::Query));
                }
                left = self.node(source, &origin, "member", member, args)?;
                continue;
            }
            if source && op == "[" {
                self.take()?;
                let index = self.expr(true, 0)?;
                self.expect("]")?;
                left = self.node(true, &origin, "index", "", vec![left, index])?;
                continue;
            }
            if source && matches!(op.as_str(), "++" | "--") {
                self.take()?;
                left = self.node(true, &origin, "postfix", op, vec![left])?;
                break;
            }
            if source
                && matches!(op.as_str(), "<" | ">")
                && self.lexer.text[self.lexer.pos..].starts_with(&op)
            {
                op.push_str(&op.clone());
            }
            if op == "not" {
                let token = self.take()?;
                origin = token.span.clone();
                if self.peek()? != "in" {
                    return Err(ParseError::new("expected 'in' after 'not'", token.span));
                }
                self.take()?;
                if compared {
                    return Err(self.fail("comparisons cannot be chained"));
                }
                compared = true;
                let right = self.expr(source, 31)?;
                left = self.node(source, &origin, "binary", "not in", vec![left, right])?;
                continue;
            }
            let bp = binding_power(&op, source);
            if bp < min_bp {
                break;
            }
            if bp == 30 && compared {
                return Err(self.fail("comparisons cannot be chained"));
            }
            compared |= bp == 30;
            self.take()?;
            if matches!(op.as_str(), "<<" | ">>") {
                self.expect(&op[..1])?;
            }
            let right = if op == "matches" && self.peek()? == "/" {
                let regex = self.lexer.regex()?;
                self.last = regex.span.clone();
                Expression::Query(
                    crate::ast::query! {kind:"regex".into(),span:regex.span,value:regex.text,args:vec![],parameters:vec![]},
                )
            } else {
                self.expr(source, if op == "**" { bp } else { bp + 1 })?
            };
            left = self.node(source, &origin, "binary", op, vec![left, right])?;
        }
        Ok(left)
    }
}
fn binding_power(op: &str, source: bool) -> i32 {
    match op {
        "or" => 10,
        "and" => 20,
        "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" => 30,
        "matches" if !source => 30,
        "|" if source => 35,
        "^" if source => 40,
        "&" if source => 45,
        "<<" | ">>" if source => 50,
        "+" | "-" => 60,
        "*" | "/" | "%" => 70,
        "**" if source => 90,
        _ => -1,
    }
}
