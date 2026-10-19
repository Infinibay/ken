//! The measured JSON recipe: preserve object order and share Python ASCII escaping.
use crate::{ModelError, assets::python_json};
use serde::{
    Deserialize, Deserializer,
    de::{self, MapAccess, SeqAccess, Visitor},
};
use serde_json::{Number, Value};
use std::{collections::BTreeSet, fmt};

enum Node {
    Null,
    Bool(bool),
    Integer(Number),
    String(String),
    Array(Vec<Node>),
    Object(Vec<(String, Node)>),
}

impl<'de> Deserialize<'de> for Node {
    fn deserialize<D: Deserializer<'de>>(input: D) -> Result<Self, D::Error> {
        struct Json;
        impl<'de> Visitor<'de> for Json {
            type Value = Node;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("ordered translation JSON")
            }
            fn visit_unit<E: de::Error>(self) -> Result<Node, E> {
                Ok(Node::Null)
            }
            fn visit_bool<E: de::Error>(self, value: bool) -> Result<Node, E> {
                Ok(Node::Bool(value))
            }
            fn visit_i64<E: de::Error>(self, value: i64) -> Result<Node, E> {
                Ok(Node::Integer(value.into()))
            }
            fn visit_u64<E: de::Error>(self, value: u64) -> Result<Node, E> {
                Ok(Node::Integer(value.into()))
            }
            fn visit_f64<E: de::Error>(self, _: f64) -> Result<Node, E> {
                Err(E::custom(
                    "unsupported floating or out-of-range translation JSON number",
                ))
            }
            fn visit_str<E: de::Error>(self, value: &str) -> Result<Node, E> {
                Ok(Node::String(value.to_owned()))
            }
            fn visit_string<E: de::Error>(self, value: String) -> Result<Node, E> {
                Ok(Node::String(value))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut input: A) -> Result<Node, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = input.next_element()? {
                    values.push(value);
                }
                Ok(Node::Array(values))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut input: A) -> Result<Node, A::Error> {
                let mut values = Vec::new();
                let mut names = BTreeSet::new();
                while let Some((key, value)) = input.next_entry::<String, Node>()? {
                    if !names.insert(key.clone()) {
                        return Err(de::Error::custom("duplicate translation JSON key"));
                    }
                    values.push((key, value));
                }
                Ok(Node::Object(values))
            }
        }
        input.deserialize_any(Json)
    }
}

fn parse(input: &[u8]) -> Result<Node, ModelError> {
    if input.len() > 4 * 1024 * 1024 {
        return Err(ModelError::Registration(
            "translation JSON byte limit exceeded".into(),
        ));
    }
    Ok(serde_json::from_slice(input)?)
}

impl Node {
    fn into_value(self) -> Value {
        match self {
            Self::Null => Value::Null,
            Self::Bool(value) => Value::Bool(value),
            Self::Integer(value) => Value::Number(value),
            Self::String(value) => Value::String(value),
            Self::Array(values) => Value::Array(values.into_iter().map(Self::into_value).collect()),
            Self::Object(values) => Value::Object(
                values
                    .into_iter()
                    .map(|(key, value)| (key, value.into_value()))
                    .collect(),
            ),
        }
    }

    fn pretty(&self, depth: usize, output: &mut String) {
        match self {
            Self::Null => output.push_str("null"),
            Self::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
            Self::Integer(value) => output.push_str(&value.to_string()),
            Self::String(value) => output.push_str(&python_json(&Value::String(value.clone()))),
            Self::Array(values) => {
                output.push('[');
                for (index, value) in values.iter().enumerate() {
                    output.push_str(if index == 0 { "\n" } else { ",\n" });
                    output.push_str(&"  ".repeat(depth + 1));
                    value.pretty(depth + 1, output);
                }
                if !values.is_empty() {
                    output.push('\n');
                    output.push_str(&"  ".repeat(depth));
                }
                output.push(']');
            }
            Self::Object(values) => {
                output.push('{');
                for (index, (key, value)) in values.iter().enumerate() {
                    output.push_str(if index == 0 { "\n" } else { ",\n" });
                    output.push_str(&"  ".repeat(depth + 1));
                    output.push_str(&python_json(&Value::String(key.clone())));
                    output.push_str(": ");
                    value.pretty(depth + 1, output);
                }
                if !values.is_empty() {
                    output.push('\n');
                    output.push_str(&"  ".repeat(depth));
                }
                output.push('}');
            }
        }
    }
}

pub(crate) fn definition(input: &str) -> Result<Value, ModelError> {
    Ok(parse(input.as_bytes())?.into_value())
}
pub(crate) fn normalize(input: &[u8]) -> Result<Vec<u8>, ModelError> {
    let node = parse(input)?;
    let mut output = String::new();
    node.pretty(0, &mut output);
    Ok(output.into_bytes())
}
