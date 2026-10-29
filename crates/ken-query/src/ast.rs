//! Typed immutable query syntax; source expressions never become query calculations.
use serde::{Deserialize, Serialize};
use std::sync::Arc;
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Span {
    pub source: Arc<str>,
    pub start: usize,
    pub end: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct TypeName {
    pub name: String,
    pub arguments: Vec<TypeName>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Parameter {
    #[serde(rename = "type")]
    pub r#type: TypeName,
    pub role: String,
    pub direction: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Expr {
    pub kind: String,
    pub span: Span,
    pub value: String,
    pub args: Vec<Expr>,
    pub parameters: Vec<Parameter>,
    #[serde(skip)]
    pub(crate) depth: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct SourceExpr {
    pub kind: String,
    pub span: Span,
    pub value: String,
    pub args: Vec<Expression>,
    #[serde(skip)]
    pub(crate) depth: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum Expression {
    Query(Expr),
    Source(SourceExpr),
}
impl<'de> Deserialize<'de> for Expression {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let v = serde_json::Value::deserialize(d)?;
        match v.get("__class__").and_then(|v| v.as_str()) {
            Some("Expr") => serde_json::from_value(v)
                .map(Self::Query)
                .map_err(serde::de::Error::custom),
            Some("SourceExpr") => serde_json::from_value(v)
                .map(Self::Source)
                .map_err(serde::de::Error::custom),
            _ => Err(serde::de::Error::custom("unknown expression class")),
        }
    }
}
impl Expression {
    pub fn kind(&self) -> &str {
        match self {
            Self::Query(e) => &e.kind,
            Self::Source(e) => &e.kind,
        }
    }
    pub fn value(&self) -> &str {
        match self {
            Self::Query(e) => &e.value,
            Self::Source(e) => &e.value,
        }
    }
    pub fn span(&self) -> &Span {
        match self {
            Self::Query(e) => &e.span,
            Self::Source(e) => &e.span,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Clause {
    pub kind: String,
    pub span: Span,
    pub name: String,
    pub role: String,
    pub expressions: Vec<Expression>,
    pub parameters: Vec<Parameter>,
    pub blocks: Vec<Vec<Clause>>,
    pub alias: String,
    pub flags: Vec<String>,
}
impl Clause {
    pub(crate) fn new(kind: impl Into<String>, span: Span) -> Self {
        Self {
            kind: kind.into(),
            span,
            name: String::new(),
            role: String::new(),
            expressions: vec![],
            parameters: vec![],
            blocks: vec![],
            alias: String::new(),
            flags: vec![],
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct Declaration {
    pub kind: String,
    pub name: String,
    pub span: Span,
    pub parameters: Vec<Parameter>,
    pub generics: Vec<(String, String)>,
    pub clauses: Vec<Clause>,
    pub formula: Option<Expr>,
    pub members: Vec<Declaration>,
    pub values: Vec<String>,
    pub implements: String,
}
impl Declaration {
    pub(crate) fn new(kind: impl Into<String>, name: String, span: Span) -> Self {
        Self {
            kind: kind.into(),
            name,
            span,
            parameters: vec![],
            generics: vec![],
            clauses: vec![],
            formula: None,
            members: vec![],
            values: vec![],
            implements: String::new(),
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "__class__")]
pub struct File {
    pub language: String,
    pub module: String,
    pub imports: Vec<String>,
    pub declarations: Vec<Declaration>,
    pub span: Span,
}

macro_rules! record_deserializer {
    ($ty:ident, $($field:ident: $type:ty),+) => {
        impl<'de> Deserialize<'de> for $ty {
            fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct Fields {
                    #[serde(rename = "__class__")]
                    class: String,
                    $($field: $type),+
                }
                let fields = Fields::deserialize(d)?;
                if fields.class != stringify!($ty) {
                    return Err(serde::de::Error::custom("incorrect AST record class"));
                }
                Ok(Self { $($field: fields.$field),+ })
            }
        }
    };
}
macro_rules! depth_record_deserializer {
    ($ty:ident, $($field:ident: $type:ty),+) => {
        impl<'de> Deserialize<'de> for $ty {
            fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct Fields {
                    #[serde(rename = "__class__")]
                    class: String,
                    $($field: $type),+
                }
                let fields = Fields::deserialize(d)?;
                if fields.class != stringify!($ty) {
                    return Err(serde::de::Error::custom("incorrect AST record class"));
                }
                Self::checked($(fields.$field),+).map_err(serde::de::Error::custom)
            }
        }
    };
}
record_deserializer!(Span,source:Arc<str>,start:usize,end:usize);
record_deserializer!(TypeName,name:String,arguments:Vec<TypeName>);
record_deserializer!(Parameter,r#type:TypeName,role:String,direction:String);
depth_record_deserializer!(Expr,kind:String,span:Span,value:String,args:Vec<Expr>,parameters:Vec<Parameter>);
depth_record_deserializer!(SourceExpr,kind:String,span:Span,value:String,args:Vec<Expression>);
record_deserializer!(Clause,kind:String,span:Span,name:String,role:String,expressions:Vec<Expression>,parameters:Vec<Parameter>,blocks:Vec<Vec<Clause>>,alias:String,flags:Vec<String>);
record_deserializer!(Declaration,kind:String,name:String,span:Span,parameters:Vec<Parameter>,generics:Vec<(String,String)>,clauses:Vec<Clause>,formula:Option<Expr>,members:Vec<Declaration>,values:Vec<String>,implements:String);
record_deserializer!(File,language:String,module:String,imports:Vec<String>,declarations:Vec<Declaration>,span:Span);

pub const MAX_AST_DEPTH: usize = 512;
impl Expr {
    pub fn checked(
        kind: String,
        span: Span,
        value: String,
        args: Vec<Expr>,
        parameters: Vec<Parameter>,
    ) -> crate::Result<Self> {
        let depth = 1 + args.iter().map(|e| e.depth).max().unwrap_or(0);
        if depth > MAX_AST_DEPTH {
            return Err(crate::ParseError::resource(
                "syntax nesting limit exceeded",
                span,
            ));
        }
        Ok(Self {
            kind,
            span,
            value,
            args,
            parameters,
            depth,
        })
    }
}
impl SourceExpr {
    pub fn checked(
        kind: String,
        span: Span,
        value: String,
        args: Vec<Expression>,
    ) -> crate::Result<Self> {
        let depth = 1 + args.iter().map(Expression::depth).max().unwrap_or(0);
        if depth > MAX_AST_DEPTH {
            return Err(crate::ParseError::resource(
                "syntax nesting limit exceeded",
                span,
            ));
        }
        Ok(Self {
            kind,
            span,
            value,
            args,
            depth,
        })
    }
}
impl Expression {
    pub(crate) fn depth(&self) -> usize {
        match self {
            Self::Query(e) => e.depth,
            Self::Source(e) => e.depth,
        }
    }
}
macro_rules! query {
    (kind:$kind:expr,span:$span:expr,value:$value:expr,args:$args:expr,parameters:$parameters:expr$(,)?) => {
        $crate::ast::Expr::checked($kind, $span, $value, $args, $parameters)?
    };
}
macro_rules! source {
    (kind:$kind:expr,span:$span:expr,value:$value:expr,args:$args:expr$(,)?) => {
        $crate::ast::SourceExpr::checked($kind, $span, $value, $args)?
    };
}
pub(crate) use {query, source};
