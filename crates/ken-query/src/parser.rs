//! Grammar coordination, byte-preserving speculation and explicit nesting limits.
use crate::{
    ParseError, ParseLimits, Result,
    ast::*,
    lexer::{Lexer, Token},
};
#[derive(Clone)]
pub(crate) struct Checkpoint {
    position: usize,
    lookahead: Token,
    last: Span,
}
pub(crate) struct Parser<'a> {
    pub lexer: Lexer<'a>,
    pub last: Span,
    pub depth: usize,
    pub max_depth: usize,
    pub call_depth: usize,
}
pub fn parse(text: &str, source: &str, limits: ParseLimits) -> Result<File> {
    let lexer = Lexer::new(text, source, limits.max_bytes)?;
    let last = lexer.span(0, 0);
    Parser {
        lexer,
        last,
        depth: 0,
        max_depth: limits.max_depth,
        call_depth: 0,
    }
    .document()
}
pub fn parse_bytes(text: &[u8], source: &str, limits: ParseLimits) -> Result<File> {
    let text = std::str::from_utf8(text).map_err(|_| {
        ParseError::new(
            "input is not valid UTF-8",
            Span {
                source: source.into(),
                start: 0,
                end: 0,
            },
        )
    })?;
    parse(text, source, limits)
}
impl Parser<'_> {
    pub fn peek(&mut self) -> Result<String> {
        Ok(self.lexer.peek()?.text.clone())
    }
    pub fn kind(&mut self) -> Result<&'static str> {
        Ok(self.lexer.peek()?.kind)
    }
    pub fn take(&mut self) -> Result<Token> {
        let t = self.lexer.take()?;
        self.last = t.span.clone();
        Ok(t)
    }
    pub fn accept(&mut self, text: &str) -> Result<bool> {
        if self.peek()? == text {
            self.take()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }
    pub fn expect(&mut self, text: &str) -> Result<Token> {
        let t = self.take()?;
        if t.text != text {
            return Err(ParseError::new(
                format!("expected {}, got {}", quote(text), quote(&t.text)),
                t.span,
            ));
        }
        Ok(t)
    }
    pub fn token(&mut self, kind: &str) -> Result<Token> {
        let t = self.take()?;
        if t.kind != kind {
            return Err(ParseError::new(
                format!("expected {kind}, got {}", quote(&t.text)),
                t.span,
            ));
        }
        Ok(t)
    }
    pub fn ident(&mut self, declaration: bool) -> Result<String> {
        let t = self.token("IDENT")?;
        if declaration && t.text != "step" && reserved(&t.text) {
            return Err(ParseError::new("reserved declaration name", t.span));
        }
        Ok(t.text)
    }
    pub fn role(&mut self) -> Result<String> {
        Ok(self.token("ROLE")?.text[1..].into())
    }
    pub fn qualified(&mut self) -> Result<String> {
        let mut s = self.ident(false)?;
        while self.accept(".")? {
            s.push('.');
            s.push_str(&self.ident(false)?);
        }
        Ok(s)
    }
    pub fn span(&self, start: &Span) -> Span {
        Span {
            source: start.source.clone(),
            start: start.start,
            end: self.last.end,
        }
    }
    pub fn here(&mut self) -> Result<Span> {
        Ok(self.lexer.peek()?.span.clone())
    }
    pub fn fail(&mut self, message: impl Into<String>) -> ParseError {
        match self.here() {
            Ok(span) => ParseError::new(message, span),
            Err(error) => error,
        }
    }
    pub fn call_enter(&mut self) -> Result<()> {
        self.call_depth += 1;
        if self.call_depth > MAX_AST_DEPTH {
            return Err(ParseError::resource(
                "syntax nesting limit exceeded",
                self.here()?,
            ));
        }
        Ok(())
    }
    pub fn enter(&mut self) -> Result<()> {
        self.depth += 1;
        if self.depth > self.max_depth {
            return Err(ParseError::resource(
                "syntax nesting limit exceeded",
                self.here()?,
            ));
        }
        Ok(())
    }
    pub fn mark(&mut self) -> Result<Checkpoint> {
        let lookahead = self.lexer.peek()?.clone();
        Ok(Checkpoint {
            position: self.lexer.pos,
            lookahead,
            last: self.last.clone(),
        })
    }
    pub fn reset(&mut self, mark: Checkpoint) {
        self.lexer.pos = mark.position;
        self.lexer.cached = Some(mark.lookahead);
        self.last = mark.last;
    }
    pub fn rewind(&mut self, byte: usize) {
        self.lexer.pos = byte;
        self.lexer.cached = None;
    }
    pub fn alias(&mut self) -> Result<String> {
        if self.accept("as")? {
            self.role()
        } else {
            Ok(String::new())
        }
    }
    fn document(&mut self) -> Result<File> {
        let start = self.expect("language")?.span;
        let token = self.token("STRING")?;
        let dialect: String = serde_json::from_str(&token.text).expect("validated JSON token");
        if dialect != "kql/2" {
            return Err(ParseError {
                message: "expected language kql/2".into(),
                span: self.last.clone(),
                code: "unsupported_dialect".into(),
            });
        }
        self.expect(";")?;
        self.expect("module")?;
        let module = self.qualified()?;
        self.expect(";")?;
        let mut imports = vec![];
        while self.accept("import")? {
            imports.push(self.qualified()?);
            self.expect(";")?;
        }
        let mut declarations = vec![];
        while self.kind()? != "EOF" {
            declarations.push(self.declaration(false)?);
        }
        self.take()?;
        Ok(File {
            language: dialect,
            module,
            imports,
            declarations,
            span: self.span(&start),
        })
    }
    pub fn qtype(&mut self) -> Result<TypeName> {
        self.call_enter()?;
        let result = crate::with_stack(|| self.qtype_inner());
        self.call_depth -= 1;
        result
    }
    fn qtype_inner(&mut self) -> Result<TypeName> {
        self.enter()?;
        let result = (|| {
            let name = self.qualified()?;
            let mut arguments = vec![];
            if self.accept("<")? {
                arguments.push(self.qtype()?);
                while self.accept(",")? {
                    arguments.push(self.qtype()?);
                }
                self.expect(">")?;
            }
            Ok(TypeName { name, arguments })
        })();
        self.depth -= 1;
        result
    }
    pub fn parameters(&mut self, end: &str, directional: bool) -> Result<Vec<Parameter>> {
        let mut params = vec![];
        if self.peek()? != end {
            loop {
                let direction = if directional {
                    let d = self.take()?.text;
                    if !matches!(d.as_str(), "in" | "out") {
                        return Err(self.fail("pattern parameter requires in or out"));
                    }
                    d
                } else {
                    "relation".into()
                };
                params.push(Parameter {
                    r#type: self.qtype()?,
                    role: self.role()?,
                    direction,
                });
                if !self.accept(",")? {
                    break;
                }
            }
        }
        Ok(params)
    }
    fn declaration(&mut self, signature: bool) -> Result<Declaration> {
        let start = self.take()?;
        let kind = start.text.as_str();
        if !matches!(
            kind,
            "pattern" | "predicate" | "query" | "enum" | "signature" | "model"
        ) {
            return Err(ParseError::new("expected declaration", start.span));
        }
        let name = self.ident(true)?;
        let mut d = Declaration::new(kind, name, self.span(&start.span));
        if kind == "pattern" && self.accept("<")? {
            loop {
                let generic = self.ident(true)?;
                self.expect(":")?;
                d.generics.push((generic, self.qualified()?));
                if !self.accept(",")? {
                    break;
                }
            }
            self.expect(">")?;
        }
        if matches!(kind, "pattern" | "predicate") {
            self.expect("(")?;
            d.parameters = self.parameters(")", kind == "pattern")?;
            self.expect(")")?;
        }
        if signature {
            if kind != "predicate" {
                return Err(self.fail("signature members must be predicates"));
            }
            self.expect(";")?;
        } else if kind == "predicate" {
            self.expect("{")?;
            d.formula = Some(self.query_expr(0)?);
            self.expect("}")?;
        } else if kind == "enum" {
            self.expect("{")?;
            d.values.push(self.ident(false)?);
            while self.accept(",")? {
                d.values.push(self.ident(false)?);
            }
            self.expect("}")?;
        } else if matches!(kind, "signature" | "model") {
            if kind == "model" {
                self.expect("implements")?;
                d.implements = self.qualified()?;
            }
            self.expect("{")?;
            while self.peek()? != "}" {
                if self.peek()? != "predicate" {
                    return Err(self.fail("expected predicate member"));
                }
                d.members.push(self.declaration(kind == "signature")?);
            }
            self.expect("}")?;
        } else {
            d.clauses = self.block(if kind == "query" {
                "query"
            } else {
                "constraint"
            })?;
        }
        d.span = self.span(&start.span);
        Ok(d)
    }
    pub fn block(&mut self, mode: &str) -> Result<Vec<Clause>> {
        self.enter()?;
        let result = (|| {
            self.expect("{")?;
            let mut clauses = vec![];
            while self.peek()? != "}" {
                if self.kind()? == "EOF" {
                    return Err(self.fail("unterminated block"));
                }
                clauses.push(self.clause(mode)?);
            }
            self.expect("}")?;
            if mode == "query" {
                let selected = clauses.iter().filter(|c| c.kind == "select").count();
                if selected != 1 {
                    return Err(self.fail("query requires exactly one select"));
                }
                let i = clauses.iter().position(|c| c.kind == "select").unwrap();
                let tail: Vec<_> = clauses[i + 1..].iter().map(|c| c.kind.as_str()).collect();
                if !matches!(
                    tail.as_slice(),
                    [] | ["order"] | ["limit"] | ["order", "limit"]
                ) {
                    return Err(self.fail("only order and limit may follow select"));
                }
            }
            Ok(clauses)
        })();
        self.depth -= 1;
        result
    }
    pub fn clause(&mut self, mode: &str) -> Result<Clause> {
        self.call_enter()?;
        let result = (|| {
            let start = self.here()?;
            let mut c = crate::with_stack(|| self.clause_inner(mode))?;
            c.span = self.span(&start);
            Ok(c)
        })();
        self.call_depth -= 1;
        result
    }
}
pub(crate) fn quote(s: &str) -> String {
    ken_program::value::string_repr(&s.into())
}
pub(crate) fn selector(s: &str) -> bool {
    "module_decl type class interface trait field property callable method function constructor param receiver var value operation macro iteration task lock region import_decl export_decl node expression statement constant".split_whitespace().any(|v|v==s)
}
fn reserved(s: &str) -> bool {
    selector(s)||"language module import pattern predicate query enum signature model implements in out from where bind use as exposes either or not exists optional fields parameters exact select order by asc desc limit body adjacent linear syntax let call argument at any name argument_pack fragment restriction between and gap until next exit initializer forbid preserve if else while for init condition step try catch when finally return throw yield resume await break continue iterate into spawn join acquire release send to receive true false null undefined forall count sum sum_by min max avg new matches edge walk tally distinct require every of".split_whitespace().any(|v|v==s)
}
