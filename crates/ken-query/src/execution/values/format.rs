//! Python-compatible display of query values at evidence and host boundaries.
use super::{Scalar, Value};
pub fn repr(value: &Value) -> String {
    match value {
        Value::Scalar(v) => v.repr(),
        Value::Unknown(reason) => format!(
            "Unknown(reason={})",
            Scalar::String(reason.as_str().into()).repr()
        ),
        Value::Enum { r#type, name } => format!(
            "EnumValue(type={}, name={})",
            Scalar::String(r#type.as_str().into()).repr(),
            Scalar::String(name.as_str().into()).repr()
        ),
        Value::Option { present, value } => format!(
            "Option(present={}, value={})",
            if *present { "True" } else { "False" },
            repr(value)
        ),
        Value::Tuple(values) => format!(
            "({}{})",
            values.iter().map(repr).collect::<Vec<_>>().join(", "),
            if values.len() == 1 { "," } else { "" }
        ),
        // Public optional evidence only uses repr for non-legacy-node values.
        Value::Operation(v) => format!(
            "OperationValue(snapshot={}, local_id={}, kind={}, native_kind={}, path={}, line={}, owner={}, language={}, execution={})",
            v.snapshot,
            quoted(&v.local_id),
            quoted(&v.kind),
            quoted(&v.native_kind),
            quoted(&v.path),
            v.line,
            quoted(&v.owner),
            quoted(&v.language),
            quoted(&v.execution)
        ),
        Value::Node(v) => format!(
            "Node(id={}, unit={}, local_id={}, kind={}, name={}, owner={}, line={}, end_line={}, path={}, language={})",
            v.id,
            v.unit,
            quoted(&v.local_id),
            quoted(&v.kind),
            v.name.as_ref().map_or("None".into(), |v| quoted(v)),
            v.owner.as_ref().map_or("None".into(), |v| quoted(v)),
            v.line,
            v.end_line,
            quoted(&v.path),
            quoted(&v.language)
        ),
        Value::Ast(v) => record(
            "ASTValue",
            &[
                ("snapshot", v.snapshot.to_string()),
                ("unit", v.unit.to_string()),
                ("node", ast_repr(&v.node)),
                ("path", quoted(&v.path)),
                ("language", quoted(&v.language)),
                ("namespace", quoted(&v.namespace)),
                ("scope_kind", quoted(&v.scope_kind)),
            ],
        ),
        Value::Type(v) => type_repr(v),
    }
}
fn record(name: &str, fields: &[(&str, String)]) -> String {
    format!(
        "{name}({})",
        fields
            .iter()
            .map(|(key, value)| format!("{key}={value}"))
            .collect::<Vec<_>>()
            .join(", ")
    )
}
fn tuple_repr(values: Vec<String>) -> String {
    format!(
        "({}{})",
        values.join(", "),
        if values.len() == 1 { "," } else { "" }
    )
}
fn ast_repr(node: &ken_program::Node) -> String {
    let values = serde_json::to_value(node).expect("AST nodes contain scalar fields");
    let fields = [
        "id",
        "kind",
        "category",
        "parent",
        "ordinal",
        "role",
        "native_role",
        "native_kind",
        "source_id",
        "start",
        "end",
        "line",
        "scope",
        "owner",
        "name",
        "text",
        "operator",
        "type_kind",
        "flags",
        "subtree_end",
        "argument_kind",
        "argument_name",
        "argument_position",
        "source_position",
    ];
    let fields = fields
        .iter()
        .map(|key| {
            let value = if *key == "flags" {
                tuple_repr(node.flags.iter().map(|s| quoted(s)).collect())
            } else {
                let raw = serde_json::value::RawValue::from_string(values[*key].to_string())
                    .expect("serialized AST field");
                Scalar::parse(&raw).expect("AST scalar field").repr()
            };
            (*key, value)
        })
        .collect::<Vec<_>>();
    record("Node", &fields)
}
fn type_repr(value: &ken_program::TypeRef) -> String {
    crate::with_stack(|| {
        record(
            "TypeRef",
            &[
                ("kind", quoted(&value.kind)),
                ("native", quoted(&value.native)),
                (
                    "arguments",
                    tuple_repr(value.arguments.iter().map(type_repr).collect()),
                ),
                ("bits", value.bits.map_or("None".into(), |v| v.to_string())),
                (
                    "signed",
                    value
                        .signed
                        .map_or("None", |v| if v { "True" } else { "False" })
                        .into(),
                ),
                (
                    "extent",
                    value.extent.as_ref().map_or("None".into(), |v| quoted(v)),
                ),
                ("rank", value.rank.map_or("None".into(), |v| v.to_string())),
                (
                    "qualifiers",
                    tuple_repr(value.qualifiers.iter().map(|v| quoted(v)).collect()),
                ),
            ],
        )
    })
}
fn quoted(v: &str) -> String {
    Scalar::String(v.into()).repr()
}
