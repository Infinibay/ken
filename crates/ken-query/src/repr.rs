//! Streaming Python dataclass/tuple identities, independent of JSON serialization.
use crate::ast::*;
use std::{
    fmt::{self, Write},
    sync::Arc,
};
pub trait PythonRepr {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result;
    fn python_repr(&self) -> String {
        let mut out = String::new();
        self.write_python_repr(&mut out).expect("string formatting");
        out
    }
}
impl PythonRepr for str {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_str(&ken_program::value::string_repr(&self.into()))
    }
}
impl PythonRepr for String {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        self.as_str().write_python_repr(out)
    }
}
impl PythonRepr for Arc<str> {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        self.as_ref().write_python_repr(out)
    }
}
impl PythonRepr for usize {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        write!(out, "{self}")
    }
}
impl<T: PythonRepr> PythonRepr for Vec<T> {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_char('(')?;
        for (i, v) in self.iter().enumerate() {
            if i > 0 {
                out.write_str(", ")?;
            }
            v.write_python_repr(out)?;
        }
        if self.len() == 1 {
            out.write_char(',')?;
        }
        out.write_char(')')
    }
}
impl<T: PythonRepr> PythonRepr for Option<T> {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        if let Some(v) = self {
            v.write_python_repr(out)
        } else {
            out.write_str("None")
        }
    }
}
impl<A: PythonRepr, B: PythonRepr> PythonRepr for (A, B) {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        out.write_char('(')?;
        self.0.write_python_repr(out)?;
        out.write_str(", ")?;
        self.1.write_python_repr(out)?;
        out.write_char(')')
    }
}
pub(crate) fn record(
    out: &mut dyn Write,
    name: &str,
    fields: &[(&str, &dyn PythonRepr)],
) -> fmt::Result {
    write!(out, "{name}(")?;
    for (i, (key, v)) in fields.iter().enumerate() {
        if i > 0 {
            out.write_str(", ")?;
        }
        write!(out, "{key}=")?;
        v.write_python_repr(out)?;
    }
    out.write_char(')')
}
macro_rules! repr_record {
    ($ty:ident, $name:literal, $($field:ident => $label:literal),+) => {
        impl PythonRepr for $ty {
            fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
                crate::with_stack(|| record(out, $name, &[$(($label, &self.$field)),+]))
            }
        }
    };
}
repr_record!(Span,"Span",source=>"source",start=>"start",end=>"end");
repr_record!(TypeName,"TypeName",name=>"name",arguments=>"arguments");
repr_record!(Parameter,"Parameter",r#type=>"type",role=>"role",direction=>"direction");
repr_record!(Expr,"Expr",kind=>"kind",span=>"span",value=>"value",args=>"args",parameters=>"parameters");
repr_record!(SourceExpr,"SourceExpr",kind=>"kind",span=>"span",value=>"value",args=>"args");
repr_record!(Clause,"Clause",kind=>"kind",span=>"span",name=>"name",role=>"role",expressions=>"expressions",parameters=>"parameters",blocks=>"blocks",alias=>"alias",flags=>"flags");
repr_record!(Declaration,"Declaration",kind=>"kind",name=>"name",span=>"span",parameters=>"parameters",generics=>"generics",clauses=>"clauses",formula=>"formula",members=>"members",values=>"values",implements=>"implements");
repr_record!(File,"File",language=>"language",module=>"module",imports=>"imports",declarations=>"declarations",span=>"span");
impl PythonRepr for Expression {
    fn write_python_repr(&self, out: &mut dyn Write) -> fmt::Result {
        match self {
            Self::Query(e) => e.write_python_repr(out),
            Self::Source(e) => e.write_python_repr(out),
        }
    }
}
