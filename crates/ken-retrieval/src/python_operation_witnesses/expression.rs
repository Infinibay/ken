//! Structural expression identity corresponding to ast.dump without locations.
//! Context and literal kind remain significant; source spelling and trivia do not.
use ruff_python_ast::{self as py, Expr, FStringPart, InterpolatedStringElement, Number};
use ruff_text_size::{Ranged, TextRange};
use serde_json::{Value, json};
pub fn same(a: &Expr, b: &Expr, source: &str) -> bool {
    match (key(a, source), key(b, source)) {
        (Some(a), Some(b)) => a == b,
        _ => false,
    }
}
fn raw(source: &str, range: TextRange) -> &str {
    &source[range.start().to_usize()..range.end().to_usize()]
}
fn optional(value: Option<&Expr>, s: &str) -> Option<Value> {
    value.map_or(Some(Value::Null), |e| key(e, s))
}
fn list(values: &[Expr], s: &str) -> Option<Vec<Value>> {
    values.iter().map(|e| key(e, s)).collect()
}
fn integer(value: &py::Int) -> Option<String> {
    let text = value.to_string().replace('_', "");
    let py_literal::Value::Integer(value) = text.parse::<py_literal::Value>().ok()? else {
        return None;
    };
    Some(value.to_string())
}
fn generators(values: &[py::Comprehension], s: &str) -> Option<Vec<Value>> {
    values
        .iter()
        .map(|v| {
            Some(json!([
                key(&v.target, s)?,
                key(&v.iter, s)?,
                list(&v.ifs, s)?,
                v.is_async
            ]))
        })
        .collect()
}
fn parameter(p: &py::Parameter, s: &str) -> Option<Value> {
    Some(json!([
        p.name.as_str(),
        optional(p.annotation.as_deref(), s)?
    ]))
}
fn parameters(p: Option<&py::Parameters>, s: &str) -> Option<Value> {
    let Some(p) = p else {
        return Some(json!([[], [], null, [], null, [], []]));
    };
    let names = |ps: &[py::ParameterWithDefault]| {
        ps.iter()
            .map(|p| parameter(&p.parameter, s))
            .collect::<Option<Vec<_>>>()
    };
    let defaults = p
        .posonlyargs
        .iter()
        .chain(&p.args)
        .filter_map(|p| p.default.as_deref())
        .map(|e| key(e, s))
        .collect::<Option<Vec<_>>>()?;
    Some(json!([
        names(&p.posonlyargs)?,
        names(&p.args)?,
        p.vararg
            .as_deref()
            .map_or(Some(Value::Null), |p| parameter(p, s))?,
        names(&p.kwonlyargs)?,
        p.kwarg
            .as_deref()
            .map_or(Some(Value::Null), |p| parameter(p, s))?,
        defaults,
        p.kwonlyargs
            .iter()
            .map(|p| optional(p.default.as_deref(), s))
            .collect::<Option<Vec<_>>>()?
    ]))
}
fn points(literal: &py::StringLiteral, s: &str) -> Option<Vec<u32>> {
    Some(
        ken_syntax::decode_python_string_literal(raw(s, literal.range))?
            .codepoints()
            .to_vec(),
    )
}
fn string_parts(value: &py::StringLiteralValue, s: &str) -> Option<Vec<u32>> {
    let mut out = Vec::new();
    for part in value.iter() {
        out.extend(points(part, s)?);
    }
    Some(out)
}
fn text_key(points: Vec<u32>, kind: Option<&str>) -> Value {
    json!(["Constant", "Str", points, kind])
}
fn string_kind(literal: &py::StringLiteral, s: &str) -> Option<&'static str> {
    raw(s, literal.range).starts_with('u').then_some("u")
}
fn append_text(out: &mut Vec<Value>, points: Vec<u32>, kind: Option<&str>) {
    if let Some(last) = out.last_mut()
        && last[0] == "Constant"
        && last[1] == "Str"
    {
        last[2]
            .as_array_mut()
            .unwrap()
            .extend(points.into_iter().map(Value::from));
        return;
    }
    out.push(text_key(points, kind));
}
// An empty constant can carry `kind="u"` into the next contiguous text.
// Drop it only when a formatted value or the JoinedStr end closes the run.
fn close_text(out: &mut Vec<Value>) {
    if out.last().is_some_and(|v| {
        v[0] == "Constant" && v[1] == "Str" && v[2].as_array().is_some_and(Vec::is_empty)
    }) {
        out.pop();
    }
}
fn segment(raw: &str, is_raw: bool) -> Option<Vec<u32>> {
    let raw = raw
        .replace("{{", "{")
        .replace("}}", "}")
        .replace("\r\n", "\n")
        .replace('\r', "\n");
    if is_raw {
        return Some(raw.chars().map(u32::from).collect());
    }
    let mut quoted = String::from("\"\"\"");
    let mut chars = raw.chars();
    while let Some(c) = chars.next() {
        match c {
            '\\' => {
                quoted.push(c);
                // A backslash immediately before an interpolation is literal.
                quoted.push(chars.next().unwrap_or('\\'));
            }
            '"' => quoted.push_str("\\\""),
            _ => quoted.push(c),
        }
    }
    quoted.push_str("\"\"\"");
    Some(
        ken_syntax::decode_python_string_literal(&quoted)?
            .codepoints()
            .to_vec(),
    )
}
fn elements(
    values: &py::InterpolatedStringElements,
    s: &str,
    is_raw: bool,
    out: &mut Vec<Value>,
) -> Option<()> {
    for part in values {
        match part {
            InterpolatedStringElement::Literal(l) => {
                append_text(out, segment(raw(s, l.range), is_raw)?, None)
            }
            InterpolatedStringElement::Interpolation(i) => {
                if let Some(debug) = &i.debug_text {
                    append_text(
                        out,
                        format!(
                            "{}{}{}",
                            debug.leading,
                            raw(s, i.expression.range()),
                            debug.trailing
                        )
                        .chars()
                        .map(u32::from)
                        .collect(),
                        None,
                    );
                }
                let mut conversion = i.conversion as i8;
                if conversion == -1 && i.debug_text.is_some() && i.format_spec.is_none() {
                    conversion = b'r' as i8;
                }
                let format = if let Some(spec) = &i.format_spec {
                    let mut parts = Vec::new();
                    elements(&spec.elements, s, is_raw, &mut parts)?;
                    close_text(&mut parts);
                    json!(["JoinedStr", parts])
                } else {
                    Value::Null
                };
                close_text(out);
                out.push(json!([
                    "FormattedValue",
                    key(&i.expression, s)?,
                    conversion,
                    format
                ]));
            }
        }
    }
    Some(())
}
fn key(e: &Expr, s: &str) -> Option<Value> {
    Some(match e {
        Expr::Name(n) => json!(["Name", n.id.as_str(), format!("{:?}", n.ctx)]),
        Expr::Attribute(n) => json!([
            "Attribute",
            key(&n.value, s)?,
            n.attr.as_str(),
            format!("{:?}", n.ctx)
        ]),
        Expr::Subscript(n) => json!([
            "Subscript",
            key(&n.value, s)?,
            key(&n.slice, s)?,
            format!("{:?}", n.ctx)
        ]),
        Expr::Starred(n) => json!(["Starred", key(&n.value, s)?, format!("{:?}", n.ctx)]),
        Expr::Tuple(n) => json!(["Tuple", list(&n.elts, s)?, format!("{:?}", n.ctx)]),
        Expr::List(n) => json!(["List", list(&n.elts, s)?, format!("{:?}", n.ctx)]),
        Expr::Set(n) => json!(["Set", list(&n.elts, s)?]),
        Expr::Dict(n) => json!([
            "Dict",
            n.items
                .iter()
                .map(|i| Some(json!([optional(i.key.as_ref(), s)?, key(&i.value, s)?])))
                .collect::<Option<Vec<_>>>()?
        ]),
        Expr::BoolOp(n) => json!(["BoolOp", format!("{:?}", n.op), list(&n.values, s)?]),
        Expr::Named(n) => json!(["NamedExpr", key(&n.target, s)?, key(&n.value, s)?]),
        Expr::BinOp(n) => json!([
            "BinOp",
            key(&n.left, s)?,
            format!("{:?}", n.op),
            key(&n.right, s)?
        ]),
        Expr::UnaryOp(n) => json!(["UnaryOp", format!("{:?}", n.op), key(&n.operand, s)?]),
        Expr::Lambda(n) => json!([
            "Lambda",
            parameters(n.parameters.as_deref(), s)?,
            key(&n.body, s)?
        ]),
        Expr::If(n) => json!([
            "IfExp",
            key(&n.test, s)?,
            key(&n.body, s)?,
            key(&n.orelse, s)?
        ]),
        Expr::Compare(n) => json!([
            "Compare",
            key(&n.left, s)?,
            n.ops.iter().map(|v| format!("{v:?}")).collect::<Vec<_>>(),
            list(&n.comparators, s)?
        ]),
        Expr::Call(n) => json!([
            "Call",
            key(&n.func, s)?,
            list(&n.arguments.args, s)?,
            n.arguments
                .keywords
                .iter()
                .map(|k| Some(json!([
                    k.arg.as_ref().map(|n| n.as_str()),
                    key(&k.value, s)?
                ])))
                .collect::<Option<Vec<_>>>()?
        ]),
        Expr::Await(n) => json!(["Await", key(&n.value, s)?]),
        Expr::Yield(n) => json!(["Yield", optional(n.value.as_deref(), s)?]),
        Expr::YieldFrom(n) => json!(["YieldFrom", key(&n.value, s)?]),
        Expr::Slice(n) => json!([
            "Slice",
            optional(n.lower.as_deref(), s)?,
            optional(n.upper.as_deref(), s)?,
            optional(n.step.as_deref(), s)?
        ]),
        Expr::ListComp(n) => json!(["ListComp", key(&n.elt, s)?, generators(&n.generators, s)?]),
        Expr::SetComp(n) => json!(["SetComp", key(&n.elt, s)?, generators(&n.generators, s)?]),
        Expr::DictComp(n) => json!([
            "DictComp",
            key(&n.key, s)?,
            key(&n.value, s)?,
            generators(&n.generators, s)?
        ]),
        Expr::Generator(n) => json!([
            "GeneratorExp",
            key(&n.elt, s)?,
            generators(&n.generators, s)?
        ]),
        Expr::StringLiteral(n) => text_key(
            string_parts(&n.value, s)?,
            string_kind(n.value.iter().next()?, s),
        ),
        Expr::BytesLiteral(n) => json!([
            "Constant",
            "Bytes",
            n.value
                .iter()
                .flat_map(|v| v.value.iter().copied())
                .collect::<Vec<_>>(),
            null
        ]),
        Expr::NumberLiteral(n) => match &n.value {
            Number::Int(v) => json!(["Constant", "Int", integer(v)?, null]),
            Number::Float(v) => json!(["Constant", "Float", v.to_bits(), null]),
            Number::Complex { real, imag } => {
                json!(["Constant", "Complex", real.to_bits(), imag.to_bits(), null])
            }
        },
        Expr::BooleanLiteral(n) => json!(["Constant", "Bool", n.value, null]),
        Expr::NoneLiteral(_) => json!(["Constant", "None", null]),
        Expr::EllipsisLiteral(_) => json!(["Constant", "Ellipsis", null]),
        Expr::FString(n) => {
            let mut parts = Vec::new();
            for p in n.value.iter() {
                match p {
                    FStringPart::Literal(l) => {
                        append_text(&mut parts, points(l, s)?, string_kind(l, s))
                    }
                    FStringPart::FString(f) => {
                        elements(&f.elements, s, f.flags.prefix().is_raw(), &mut parts)?;
                    }
                }
            }
            close_text(&mut parts);
            json!(["JoinedStr", parts])
        }
        Expr::TString(_) | Expr::IpyEscapeCommand(_) => return None,
    })
}
