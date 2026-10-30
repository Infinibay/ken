//! Typed query values. Source identity, scalar identity and missing knowledge differ.
use super::{ExecutionError, Result};
use ken_program::{TypeRef, value::GraphValue as Scalar};
use ken_text::PythonText;
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{FromPrimitive, Signed, ToPrimitive, Zero};
use serde::{Deserialize, Serialize, Serializer, ser::SerializeMap};
use std::{cmp::Ordering, collections::BTreeMap, sync::Arc};

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceNode {
    pub id: i64,
    pub unit: i64,
    pub local_id: String,
    pub kind: String,
    pub name: Option<String>,
    pub owner: Option<String>,
    pub line: i64,
    pub end_line: i64,
    pub path: String,
    pub language: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperationValue {
    pub snapshot: i64,
    pub local_id: String,
    pub kind: String,
    pub native_kind: String,
    pub path: String,
    pub line: i64,
    pub owner: String,
    pub language: String,
    pub execution: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct AstValue {
    pub snapshot: i64,
    pub unit: i64,
    pub node: ken_program::Node,
    pub path: String,
    pub language: String,
    pub namespace: String,
    pub scope_kind: String,
}
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Scalar(Scalar),
    Node(Arc<SourceNode>),
    Operation(Arc<OperationValue>),
    Ast(Arc<AstValue>),
    Type(Arc<TypeRef>),
    Unknown(String),
    Option { present: bool, value: Box<Value> },
    Enum { r#type: String, name: String },
    Tuple(Arc<Vec<Value>>),
}
pub type Bindings = BTreeMap<String, Value>;
impl Value {
    pub fn literal(raw: &str) -> Result<Self> {
        if raw == "undefined" {
            return Ok(Self::Enum {
                r#type: "SourceLiteral".into(),
                name: "undefined".into(),
            });
        }
        if raw.len() > 65536
            && raw
                .as_bytes()
                .first()
                .is_some_and(|c| c.is_ascii_digit() || *c == b'-')
        {
            return Err(ExecutionError::Exhausted("numeric"));
        }
        let raw = serde_json::value::RawValue::from_string(raw.into())
            .map_err(|e| ExecutionError::Invalid(e.to_string()))?;
        let value = match Scalar::parse(&raw)? {
            Scalar::String(text) => Scalar::String(text.joined_surrogates()),
            other => other,
        };
        Ok(Self::Scalar(value))
    }
    pub fn null() -> Self {
        Self::Scalar(Scalar::Null)
    }
    pub fn boolean(v: bool) -> Self {
        Self::Scalar(Scalar::Bool(v))
    }
    pub fn string(v: impl Into<PythonText>) -> Self {
        Self::Scalar(Scalar::String(v.into()))
    }
    pub fn integer(v: impl ToString) -> Self {
        Self::Scalar(Scalar::Int(v.to_string()))
    }
    pub fn unknown(reason: impl Into<String>) -> Self {
        Self::Unknown(reason.into())
    }
    pub fn tuple(values: Vec<Self>) -> Self {
        Self::Tuple(Arc::new(values))
    }
    pub fn none() -> Self {
        Self::Option {
            present: false,
            value: Box::new(Self::null()),
        }
    }
    pub fn some(value: Self) -> Self {
        Self::Option {
            present: true,
            value: Box::new(value),
        }
    }
    pub fn is_unknown(&self) -> bool {
        matches!(self, Self::Unknown(_))
    }
    pub fn is_true(&self) -> bool {
        matches!(self, Self::Scalar(Scalar::Bool(true)))
    }
    pub fn is_false(&self) -> bool {
        matches!(self, Self::Scalar(Scalar::Bool(false)))
    }
    pub fn text(&self) -> Option<String> {
        if let Self::Scalar(Scalar::String(v)) = self {
            v.to_utf8()
        } else {
            None
        }
    }
    pub fn local_id(&self) -> Option<&str> {
        match self {
            Self::Node(n) => Some(&n.local_id),
            Self::Operation(n) => Some(&n.local_id),
            _ => None,
        }
    }
    pub fn and(self, other: Self) -> Self {
        if self.is_false() || other.is_false() {
            Self::boolean(false)
        } else if self.is_unknown() {
            self
        } else if other.is_unknown() {
            other
        } else {
            Self::boolean(true)
        }
    }
    pub fn or(self, other: Self) -> Self {
        if self.is_true() || other.is_true() {
            Self::boolean(true)
        } else if self.is_unknown() {
            self
        } else if other.is_unknown() {
            other
        } else {
            Self::boolean(false)
        }
    }
    pub fn negate(self) -> Self {
        if self.is_unknown() {
            self
        } else {
            Self::boolean(self.is_false())
        }
    }
    /// Type tags are recursive: True,1,1.0 and tuples containing them never unify.
    pub fn identity(&self) -> Result<String> {
        self.identity_at(0)
    }
    fn identity_at(&self, depth: usize) -> Result<String> {
        crate::with_stack(|| {
            if depth > 128 {
                return Err(ExecutionError::Exhausted("value_identity"));
            }
            let (tag, content) = match self {
                Self::Scalar(Scalar::Float(v)) if *v == 0.0 => ("float", "0.0".into()),
                Self::Scalar(v) => (v.tag(), v.to_raw()?.get().into()),
                Self::Node(v) => ("Node", encoded(v.as_ref())?),
                Self::Operation(v) => ("OperationValue", encoded(v.as_ref())?),
                Self::Ast(v) => ("ASTValue", encoded(v.as_ref())?),
                Self::Type(v) => ("TypeRef", encoded(v.as_ref())?),
                Self::Unknown(v) => ("Unknown", encoded(v)?),
                Self::Enum { r#type, name } => ("EnumValue", encoded(&(r#type, name))?),
                Self::Option { present, value } => (
                    "Option",
                    encoded(&(*present, value.identity_at(depth + 1)?))?,
                ),
                Self::Tuple(values) => {
                    let keys = values
                        .iter()
                        .map(|v| v.identity_at(depth + 1))
                        .collect::<Result<Vec<_>>>()?;
                    ("tuple", encoded(&keys)?)
                }
            };
            Ok(format!("{tag}:{content}"))
        })
    }
}
fn encoded<T: Serialize + ?Sized>(value: &T) -> Result<String> {
    serde_json::to_string(value).map_err(|e| ExecutionError::Invalid(e.to_string()))
}
impl Serialize for Value {
    fn serialize<S: Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        match self {
            Self::Scalar(v) => v.to_raw().map_err(serde::ser::Error::custom)?.serialize(s),
            Self::Node(v) => v.serialize(s),
            Self::Operation(v) => v.serialize(s),
            Self::Ast(v) => v.serialize(s),
            Self::Type(v) => v.serialize(s),
            Self::Tuple(v) => v.serialize(s),
            Self::Unknown(reason) => {
                let mut m = s.serialize_map(Some(1))?;
                m.serialize_entry("reason", reason)?;
                m.end()
            }
            Self::Option { present, value } => {
                let mut m = s.serialize_map(Some(2))?;
                m.serialize_entry("present", present)?;
                m.serialize_entry("value", value)?;
                m.end()
            }
            Self::Enum { r#type, name } => {
                let mut m = s.serialize_map(Some(2))?;
                m.serialize_entry("type", r#type)?;
                m.serialize_entry("name", name)?;
                m.end()
            }
        }
    }
}
fn invalid(message: &str) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
fn integer(raw: &str) -> Result<BigInt> {
    if raw.len() > 65536 {
        return Err(ExecutionError::Exhausted("numeric"));
    }
    raw.parse().map_err(|_| invalid("invalid integer value"))
}
fn real(value: &Scalar) -> Result<f64> {
    match value {
        Scalar::Float(v) => Ok(*v),
        Scalar::Int(v) => integer(v)?
            .to_f64()
            .filter(|n| n.is_finite())
            .ok_or_else(|| invalid("integer too large to convert to float")),
        _ => Err(invalid("numeric operator requires a number")),
    }
}
fn number(value: &Value) -> Result<&Scalar> {
    if let Value::Scalar(value @ (Scalar::Int(_) | Scalar::Float(_))) = value {
        Ok(value)
    } else {
        Err(invalid("numeric operator requires a number"))
    }
}
fn checked_float(value: f64) -> Result<Value> {
    if value.is_finite() {
        Ok(Value::Scalar(Scalar::Float(value)))
    } else {
        Err(invalid("nonfinite calculation result"))
    }
}
/// Correctly rounded integer ratio, including huge operands and subnormal output.
fn ratio(a: &BigInt, b: &BigInt) -> Result<f64> {
    if b.is_zero() {
        return Err(invalid("division by zero"));
    }
    let negative = a.sign() != b.sign();
    if a.is_zero() {
        return Ok(if negative { -0.0 } else { 0.0 });
    }
    let a = a.abs();
    let b = b.abs();
    let mut exponent = a.bits() as i64 - b.bits() as i64;
    if exponent >= 0 {
        if a < (&b << exponent as usize) {
            exponent -= 1;
        }
    } else if (&a << (-exponent) as usize) < b {
        exponent -= 1;
    }
    if exponent > 1023 {
        return Err(invalid("integer division result too large for a float"));
    }
    let sign = if negative { 1u64 << 63 } else { 0 };
    if exponent < -1075 {
        return Ok(f64::from_bits(sign));
    }
    let scale = if exponent < -1022 {
        1074
    } else {
        52 - exponent
    };
    let (numerator, denominator) = if scale >= 0 {
        (&a << scale as usize, b)
    } else {
        (a, &b << (-scale) as usize)
    };
    let (mut quotient, remainder) = numerator.div_rem(&denominator);
    let twice = &remainder << 1usize;
    if twice > denominator || twice == denominator && quotient.is_odd() {
        quotient += 1;
    }
    let mut mantissa = quotient
        .to_u64()
        .ok_or_else(|| invalid("invalid floating division mantissa"))?;
    if exponent < -1022 {
        return Ok(f64::from_bits(sign | mantissa));
    }
    if mantissa >= 1u64 << 53 {
        mantissa >>= 1;
        exponent += 1;
    }
    if exponent > 1023 {
        return Err(invalid("integer division result too large for a float"));
    }
    Ok(f64::from_bits(
        sign | ((exponent + 1023) as u64) << 52 | (mantissa - (1u64 << 52)),
    ))
}
pub fn arithmetic(op: &str, a: &Value, b: &Value) -> Result<Value> {
    if a.is_unknown() {
        return Ok(a.clone());
    }
    if b.is_unknown() {
        return Ok(b.clone());
    }
    let (a, b) = (number(a)?, number(b)?);
    if let (Scalar::Int(a), Scalar::Int(b)) = (a, b) {
        let (a, b) = (integer(a)?, integer(b)?);
        if op == "/" {
            return checked_float(ratio(&a, &b)?);
        }
        let value = match op {
            "+" => a + b,
            "-" => a - b,
            "*" => a * b,
            "%" => {
                if b.is_zero() {
                    return Err(invalid("integer modulo by zero"));
                }
                a.mod_floor(&b)
            }
            _ => return Err(invalid("unsupported arithmetic operator")),
        };
        if value.bits() > 220000 {
            return Err(ExecutionError::Exhausted("numeric"));
        }
        return Ok(Value::integer(value));
    }
    let (a, b) = (real(a)?, real(b)?);
    let value = match op {
        "+" => a + b,
        "-" => a - b,
        "*" => a * b,
        "/" => {
            if b == 0.0 {
                return Err(invalid("float division by zero"));
            }
            a / b
        }
        "%" => {
            if b == 0.0 {
                return Err(invalid("float modulo by zero"));
            }
            let r = a % b;
            if r == 0.0 {
                r.copysign(b)
            } else if r.is_sign_negative() != b.is_sign_negative() {
                r + b
            } else {
                r
            }
        }
        _ => return Err(invalid("unsupported arithmetic operator")),
    };
    checked_float(value)
}
pub fn unary(op: &str, value: &Value) -> Result<Value> {
    if op == "not" {
        return Ok(value.clone().negate());
    }
    if value.is_unknown() {
        return Ok(value.clone());
    }
    match number(value)? {
        Scalar::Int(v) => Ok(Value::integer(if op == "+" {
            integer(v)?
        } else if op == "-" {
            -integer(v)?
        } else {
            return Err(invalid("unsupported unary operator"));
        })),
        Scalar::Float(v) => checked_float(if op == "+" {
            *v
        } else if op == "-" {
            -*v
        } else {
            return Err(invalid("unsupported unary operator"));
        }),
        _ => unreachable!(),
    }
}
fn compare_integer_float(integer: &BigInt, float: f64) -> Result<Ordering> {
    if !float.is_finite() {
        return if float.is_nan() {
            Err(invalid("NaN cannot be ordered"))
        } else {
            Ok(if float.is_sign_negative() {
                Ordering::Greater
            } else {
                Ordering::Less
            })
        };
    }
    let truncated =
        BigInt::from_f64(float).ok_or_else(|| invalid("invalid floating comparison"))?;
    let order = integer.cmp(&truncated);
    Ok(if order != Ordering::Equal || float.fract() == 0.0 {
        order
    } else if float.is_sign_negative() {
        Ordering::Greater
    } else {
        Ordering::Less
    })
}
pub fn compare(a: &Value, b: &Value) -> Result<Ordering> {
    match (a, b) {
        (Value::Scalar(Scalar::String(a)), Value::Scalar(Scalar::String(b))) => {
            Ok(a.codepoints().cmp(b.codepoints()))
        }
        (Value::Scalar(Scalar::Int(a)), Value::Scalar(Scalar::Int(b))) => {
            Ok(integer(a)?.cmp(&integer(b)?))
        }
        (Value::Scalar(Scalar::Float(a)), Value::Scalar(Scalar::Float(b))) => a
            .partial_cmp(b)
            .ok_or_else(|| invalid("NaN cannot be ordered")),
        (Value::Scalar(Scalar::Int(a)), Value::Scalar(Scalar::Float(b))) => {
            compare_integer_float(&integer(a)?, *b)
        }
        (Value::Scalar(Scalar::Float(a)), Value::Scalar(Scalar::Int(b))) => {
            compare_integer_float(&integer(b)?, *a).map(Ordering::reverse)
        }
        _ => Err(invalid("values cannot be ordered")),
    }
}

mod format;
pub use format::repr;
