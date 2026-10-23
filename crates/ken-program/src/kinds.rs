//! Auditable original grammar vocabulary; unknown syntax remains explicit.
use crate::Operation;
use serde::Deserialize;
use std::{collections::BTreeMap, sync::OnceLock};
#[derive(Deserialize)]
struct Vocabulary {
    native: BTreeMap<String, (String, String)>,
    operations: BTreeMap<String, (String, String)>,
}
pub(crate) fn classify(operation: &Operation, root: bool) -> (String, String) {
    if root {
        return ("module".into(), "declaration".into());
    }
    if operation.native_kind == "map_type" {
        return ("type_name".into(), "type".into());
    }
    if operation.native_kind == "unary_expression" {
        return ("unary".into(), "expression".into());
    }
    static VOCABULARY: OnceLock<Vocabulary> = OnceLock::new();
    let v = VOCABULARY.get_or_init(|| {
        serde_json::from_str(include_str!("kinds.json")).expect("original grammar vocabulary")
    });
    v.native
        .get(&operation.native_kind)
        .or_else(|| v.operations.get(&operation.kind))
        .cloned()
        .unwrap_or_else(|| ("opaque".into(), "opaque".into()))
}
pub(crate) fn role<'a>(kind: &str, native: &'a str) -> &'a str {
    match native {
        "consequence" | "then" => return "then",
        "alternative" => return "else",
        "initializer" | "initialization" => return "init",
        "increment" | "update" => return "step",
        _ => {}
    }
    match kind {
        "assignment" | "variable_declaration" => match native {
            "left" | "name" | "pattern" | "declarator" => "target",
            "right" => "value",
            _ => native,
        },
        "binary" | "compare" | "unary" | "update" => {
            if native == "argument" {
                "operand"
            } else {
                native
            }
        }
        "call" => {
            if matches!(native, "function" | "name") {
                "callee"
            } else {
                native
            }
        }
        _ => native,
    }
}
pub(crate) fn declaration(kind: &str) -> Option<&'static str> {
    match kind {
        "CLASS" | "INTERFACE" | "TRAIT" | "STRUCT" | "ENUM" => Some("type_declaration"),
        "CALLABLE" => Some("callable"),
        "PARAMETER" => Some("parameter"),
        _ => None,
    }
}
pub(crate) fn declarator(native: &str) -> bool {
    matches!(
        native,
        "variable_declarator"
            | "init_declarator"
            | "let_declaration"
            | "short_var_declaration"
            | "var_spec"
            | "const_spec"
    )
}
pub(crate) fn closure(native: &str) -> bool {
    matches!(
        native,
        "lambda"
            | "lambda_expression"
            | "arrow_function"
            | "closure_expression"
            | "func_literal"
            | "function_expression"
            | "generator_function"
            | "block"
            | "do_block"
    )
}
pub(crate) fn block_language(language: &str) -> bool {
    matches!(
        language,
        "javascript" | "typescript" | "java" | "csharp" | "cpp" | "go" | "rust"
    )
}
pub(crate) fn operator(token: &str) -> bool {
    matches!(
        token,
        "+" | "-"
            | "*"
            | "/"
            | "//"
            | "%"
            | "**"
            | "="
            | "+="
            | "-="
            | "*="
            | "/="
            | "%="
            | "<"
            | ">"
            | "<="
            | ">="
            | "=="
            | "!="
            | "==="
            | "!=="
            | "&&"
            | "||"
            | "and"
            | "or"
            | "not"
            | "!"
            | "&"
            | "|"
            | "^"
            | "~"
            | "<<"
            | ">>"
            | ">>>"
            | "++"
            | "--"
            | "in"
            | "is"
            | "??"
            | ":="
    )
}
