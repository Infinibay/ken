//! Values shared by query normalization and the columnar graph store.
//! Integers and Python strings stay lossless until a consumer asks for a scalar.
use crate::{Attributes, ProgramError};
use ken_text::PythonText;
use serde::{
    Deserialize, Deserializer,
    de::{MapAccess, Visitor},
};
use serde_json::value::RawValue;
use std::fmt::Write;

#[derive(Clone, Debug, PartialEq)]
pub enum GraphValue {
    Null,
    Bool(bool),
    Int(String),
    Float(f64),
    String(PythonText),
    List(Vec<Self>),
    Tuple(Vec<Self>),
    Set(Vec<Self>),
    Dict(Vec<(PythonText, Self)>),
}
impl GraphValue {
    pub fn parse(raw: &RawValue) -> Result<Self, ProgramError> {
        Self::parse_depth(raw, 0)
    }
    fn parse_depth(raw: &RawValue, depth: usize) -> Result<Self, ProgramError> {
        if depth > 512 {
            return Err(ProgramError::Invalid("graph value nesting limit exceeded"));
        }
        let s = raw.get().trim();
        Ok(match s.as_bytes().first() {
            Some(b'n') => Self::Null,
            Some(b't') => Self::Bool(true),
            Some(b'f') => Self::Bool(false),
            Some(b'"') => {
                let text: PythonText = serde_json::from_str(s)?;
                let mut points = Vec::new();
                let mut it = text.codepoints().iter().copied().peekable();
                while let Some(p) = it.next() {
                    if (0xd800..=0xdbff).contains(&p)
                        && it.peek().is_some_and(|q| (0xdc00..=0xdfff).contains(q))
                    {
                        let q = it.next().unwrap();
                        points.push(0x10000 + ((p - 0xd800) << 10) + q - 0xdc00);
                    } else {
                        points.push(p);
                    }
                }
                Self::String(PythonText::from_codepoints(points).unwrap())
            }
            Some(b'[') => Self::List(
                serde_json::from_str::<Vec<Box<RawValue>>>(s)?
                    .iter()
                    .map(|r| Self::parse_depth(r, depth + 1))
                    .collect::<Result<_, _>>()?,
            ),
            Some(b'{') => {
                let pairs: OrderedRaw = serde_json::from_str(s)?;
                let mut items: Vec<(PythonText, Self)> = Vec::new();
                let mut positions = std::collections::BTreeMap::<Vec<u32>, usize>::new();
                for (key, value) in pairs.0 {
                    let Self::String(key) = Self::parse_depth(&key, depth + 1)? else {
                        unreachable!()
                    };
                    let value = Self::parse_depth(&value, depth + 1)?;
                    if let Some(&i) = positions.get(key.codepoints()) {
                        items[i].1 = value;
                    } else {
                        positions.insert(key.codepoints().to_vec(), items.len());
                        items.push((key, value));
                    }
                }
                Self::Dict(items)
            }
            _ if s.contains(['.', 'e', 'E']) => Self::Float(
                s.parse()
                    .map_err(|_| ProgramError::Invalid("invalid graph float"))?,
            ),
            _ => Self::Int(if s == "-0" { "0".into() } else { s.to_owned() }),
        })
    }
    pub fn from_attrs(attrs: &Attributes) -> Result<Self, ProgramError> {
        Ok(Self::Dict(
            attrs
                .iter()
                .map(|(k, v)| Ok((k.as_str().into(), Self::parse(v)?)))
                .collect::<Result<_, ProgramError>>()?,
        ))
    }
    pub fn into_attrs(self) -> Result<Attributes, ProgramError> {
        let Self::Dict(items) = self else {
            return Err(ProgramError::Invalid(
                "graph attributes must be a dictionary",
            ));
        };
        items
            .into_iter()
            .map(|(k, v)| {
                Ok((
                    k.to_utf8()
                        .ok_or(ProgramError::Invalid("non UTF-8 attribute key"))?,
                    v.to_raw()?,
                ))
            })
            .collect()
    }
    pub fn to_raw(&self) -> Result<Box<RawValue>, ProgramError> {
        let text = match self {
            Self::Null => "null".into(),
            Self::Bool(v) => v.to_string(),
            Self::Int(v) => v.clone(),
            Self::Float(v) if v.is_nan() => {
                return Err(ProgramError::Invalid("NaN has no JSON representation"));
            }
            Self::Float(v) if v.is_infinite() => {
                if v.is_sign_negative() {
                    "-1e400".into()
                } else {
                    "1e400".into()
                }
            }
            Self::Float(v) => serde_json::to_string(v)?,
            Self::String(v) => serde_json::to_string(v)?,
            Self::List(v) | Self::Tuple(v) | Self::Set(v) => format!(
                "[{}]",
                v.iter()
                    .map(|v| v.to_raw().map(|r| r.get().to_owned()))
                    .collect::<Result<Vec<_>, _>>()?
                    .join(",")
            ),
            Self::Dict(v) => format!(
                "{{{}}}",
                v.iter()
                    .map(|(k, v)| Ok(format!(
                        "{}:{}",
                        serde_json::to_string(k)?,
                        v.to_raw()?.get()
                    )))
                    .collect::<Result<Vec<_>, ProgramError>>()?
                    .join(",")
            ),
        };
        Ok(RawValue::from_string(text)?)
    }
    pub fn tag(&self) -> &'static str {
        match self {
            Self::Null => "NoneType",
            Self::Bool(_) => "bool",
            Self::Int(_) => "int",
            Self::Float(_) => "float",
            Self::String(_) => "str",
            Self::List(_) => "list",
            Self::Tuple(_) => "tuple",
            Self::Set(_) => "set",
            Self::Dict(_) => "dict",
        }
    }
    pub fn truthy(&self) -> bool {
        match self {
            Self::Null => false,
            Self::Bool(v) => *v,
            Self::Int(v) => v != "0",
            Self::Float(v) => *v != 0.,
            Self::String(v) => !v.is_empty(),
            Self::List(v) | Self::Tuple(v) | Self::Set(v) => !v.is_empty(),
            Self::Dict(v) => !v.is_empty(),
        }
    }
    pub fn string(&self) -> Option<String> {
        if let Self::String(v) = self {
            v.to_utf8()
        } else {
            None
        }
    }
    pub fn comparison(&self) -> String {
        match self {
            Self::Bool(v) => v.to_string(),
            Self::String(v) => v.to_utf8().unwrap_or_else(|| self.repr()),
            _ => self.repr(),
        }
    }
    pub fn repr(&self) -> String {
        match self {
            Self::Null => "None".into(),
            Self::Bool(v) => if *v { "True" } else { "False" }.into(),
            Self::Int(v) => v.clone(),
            Self::Float(v) => float_str(*v),
            Self::String(v) => string_repr(v),
            Self::List(v) => sequence_repr(v, "[", "]"),
            Self::Tuple(v) => {
                let mut s = sequence_repr(v, "(", ")");
                if v.len() == 1 {
                    s.insert(s.len() - 1, ',');
                }
                s
            }
            Self::Set(v) => {
                if v.is_empty() {
                    "set()".into()
                } else {
                    sequence_repr(v, "{", "}")
                }
            }
            Self::Dict(v) => format!(
                "{{{}}}",
                v.iter()
                    .map(|(k, v)| format!("{}: {}", string_repr(k), v.repr()))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }
}
fn sequence_repr(v: &[GraphValue], open: &str, close: &str) -> String {
    format!(
        "{open}{}{close}",
        v.iter()
            .map(GraphValue::repr)
            .collect::<Vec<_>>()
            .join(", ")
    )
}
pub fn string_repr(text: &PythonText) -> String {
    let quote = if text.codepoints().contains(&39) && !text.codepoints().contains(&34) {
        34
    } else {
        39
    };
    let mut out = String::new();
    out.push(char::from_u32(quote).unwrap());
    for &p in text.codepoints() {
        match p {
            0x5c => out.push_str("\\\\"),
            10 => out.push_str("\\n"),
            13 => out.push_str("\\r"),
            9 => out.push_str("\\t"),
            _ if p == quote => {
                out.push('\\');
                out.push(char::from_u32(p).unwrap());
            }
            _ if !char::from_u32(p).is_some_and(ken_text::unicode::printable) => {
                if p <= 255 {
                    write!(out, "\\x{p:02x}").unwrap();
                } else if p <= 65535 {
                    write!(out, "\\u{p:04x}").unwrap();
                } else {
                    write!(out, "\\U{p:08x}").unwrap();
                }
            }
            _ => out.push(char::from_u32(p).unwrap()),
        }
    }
    out.push(char::from_u32(quote).unwrap());
    out
}
pub fn float_hex(v: f64) -> String {
    if v.is_nan() {
        return "nan".into();
    }
    if v.is_infinite() {
        return if v.is_sign_negative() { "-inf" } else { "inf" }.into();
    }
    let bits = v.to_bits();
    let sign = if bits >> 63 != 0 { "-" } else { "" };
    let exponent = ((bits >> 52) & 2047) as i32;
    let fraction = bits & ((1u64 << 52) - 1);
    if exponent == 0 && fraction == 0 {
        return format!("{sign}0x0.0p+0");
    }
    format!(
        "{sign}0x{}.{fraction:013x}p{:+}",
        if exponent == 0 { 0 } else { 1 },
        if exponent == 0 {
            -1022
        } else {
            exponent - 1023
        }
    )
}
pub fn parse_float_hex(text: &str) -> Result<f64, ProgramError> {
    match text {
        "nan" => return Ok(f64::NAN),
        "inf" => return Ok(f64::INFINITY),
        "-inf" => return Ok(f64::NEG_INFINITY),
        _ => (),
    }
    let (negative, s) = text.strip_prefix('-').map_or((false, text), |s| (true, s));
    let (mantissa, exp) = s
        .strip_prefix("0x")
        .and_then(|s| s.split_once('p'))
        .ok_or(ProgramError::Invalid("invalid hexadecimal float"))?;
    let exp: i32 = exp
        .parse()
        .map_err(|_| ProgramError::Invalid("invalid float exponent"))?;
    let (whole, fraction) = mantissa
        .split_once('.')
        .ok_or(ProgramError::Invalid("invalid float mantissa"))?;
    let digits = format!("{whole}{fraction}");
    let n = u64::from_str_radix(&digits, 16)
        .map_err(|_| ProgramError::Invalid("invalid float mantissa"))?;
    let exponent = exp - 4 * fraction.len() as i32;
    let v = if exponent < -1022 {
        (n as f64 * 2f64.powi(exponent + 1022)) * 2f64.powi(-1022)
    } else {
        n as f64 * 2f64.powi(exponent)
    };
    Ok(if negative { -v } else { v })
}
pub fn float_str(v: f64) -> String {
    if !v.is_finite() {
        return if v.is_nan() {
            "nan"
        } else if v.is_sign_negative() {
            "-inf"
        } else {
            "inf"
        }
        .into();
    }
    if v == 0. {
        return if v.is_sign_negative() { "-0.0" } else { "0.0" }.into();
    }
    let scientific = format!("{v:e}");
    let (digits, exp) = scientific.split_once('e').unwrap();
    let exponent: i32 = exp.parse().unwrap();
    if !(-4..16).contains(&exponent) {
        return format!(
            "{digits}e{}{abs:02}",
            if exponent >= 0 { "+" } else { "-" },
            abs = exponent.abs()
        );
    }
    let sign = if v.is_sign_negative() { "-" } else { "" };
    let digits = digits.trim_start_matches('-').replace('.', "");
    let point = exponent + 1;
    if point <= 0 {
        format!("{sign}0.{}{digits}", "0".repeat((-point) as usize))
    } else if point as usize >= digits.len() {
        format!(
            "{sign}{digits}{}.0",
            "0".repeat(point as usize - digits.len())
        )
    } else {
        let (a, b) = digits.split_at(point as usize);
        format!("{sign}{a}.{b}")
    }
}
struct OrderedRaw(Vec<(Box<RawValue>, Box<RawValue>)>);
impl<'de> Deserialize<'de> for OrderedRaw {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = OrderedRaw;
            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str("ordered graph dictionary")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut out = Vec::new();
                while let Some(k) = map.next_key::<PythonText>()? {
                    let raw =
                        serde_json::value::to_raw_value(&k).map_err(serde::de::Error::custom)?;
                    out.push((raw, map.next_value()?));
                }
                Ok(OrderedRaw(out))
            }
        }
        d.deserialize_map(Ordered)
    }
}
