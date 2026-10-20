//! Owned FastEmbed token batches; lexical preparation is independent of weights.
use crate::{FastEmbedModel, ModelError, ModelFileSource, VerifiedModelFiles};
use serde::{
    Deserialize, Deserializer,
    de::{self, MapAccess, Visitor},
};
use serde_json::value::RawValue;
use std::{cmp::Ordering, collections::BTreeSet, fmt};
use tokenizers::{AddedToken, PaddingParams, Tokenizer, TruncationParams};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FastEmbedTokens {
    pub shape: [usize; 2],
    pub ids: Vec<i64>,
    pub attention_mask: Vec<i64>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FastEmbedInput {
    Query,
    Passage,
}

fn invalid(message: &str) -> ModelError {
    ModelError::Tokenizer(format!("FastEmbed: {message}"))
}

/// Only the object layer needs order; raw values retain integer/float spelling.
struct Object(Vec<(String, Box<RawValue>)>);

impl<'de> Deserialize<'de> for Object {
    fn deserialize<D: Deserializer<'de>>(input: D) -> Result<Self, D::Error> {
        struct Ordered;
        impl<'de> Visitor<'de> for Ordered {
            type Value = Object;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("distinct ordered JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut input: M) -> Result<Object, M::Error> {
                let mut rows = Vec::new();
                let mut names = BTreeSet::new();
                while let Some((name, value)) = input.next_entry::<String, Box<RawValue>>()? {
                    if !names.insert(name.clone()) {
                        return Err(de::Error::custom("duplicate tokenizer JSON key"));
                    }
                    rows.push((name, value));
                }
                Ok(Object(rows))
            }
        }
        input.deserialize_map(Ordered)
    }
}

impl Object {
    fn get(&self, name: &str) -> Option<&RawValue> {
        self.0
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.as_ref())
    }
}

enum Bound<'a> {
    Integer(&'a str),
    Float(f64),
}

fn digits_cmp(left: &str, right: &str) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

impl<'a> Bound<'a> {
    fn parse(value: &'a RawValue) -> Result<Self, ModelError> {
        let text = value.get();
        if !text.is_empty() && text.bytes().all(|byte| byte.is_ascii_digit()) {
            return Ok(Self::Integer(text));
        }
        text.parse::<f64>()
            .map(Self::Float)
            .map_err(|_| invalid("numeric context bound required"))
    }
    fn compare(&self, other: &Self) -> Result<Ordering, ModelError> {
        match (self, other) {
            (Self::Integer(a), Self::Integer(b)) => Ok(digits_cmp(a, b)),
            (Self::Float(a), Self::Float(b)) => a
                .partial_cmp(b)
                .ok_or_else(|| invalid("invalid context bound")),
            (Self::Integer(a), Self::Float(b)) => {
                if *b < 0. {
                    return Ok(Ordering::Greater);
                }
                if *b == f64::INFINITY {
                    return Ok(Ordering::Less);
                }
                if !b.is_finite() {
                    return Err(invalid("invalid context bound"));
                }
                let floor = format!("{:.0}", b.floor());
                let comparison = digits_cmp(a, &floor);
                Ok(if comparison == Ordering::Equal && b.fract() > 0. {
                    Ordering::Less
                } else {
                    comparison
                })
            }
            (Self::Float(_), Self::Integer(_)) => other.compare(self).map(Ordering::reverse),
        }
    }
    fn length(&self) -> Result<usize, ModelError> {
        match self {
            Self::Integer(value) => value
                .parse::<usize>()
                .ok()
                .filter(|value| *value > 0)
                .ok_or_else(|| invalid("positive context bound must fit usize")),
            Self::Float(_) => Err(invalid("selected context bound must be an integer")),
        }
    }
}

fn context(config: &Object) -> Result<usize, ModelError> {
    let model = config
        .get("model_max_length")
        .map(Bound::parse)
        .transpose()?;
    let max = config.get("max_length").map(Bound::parse).transpose()?;
    let selected = match (model, max) {
        (Some(a), Some(b)) => {
            if a.compare(&b)? == Ordering::Greater {
                b
            } else {
                a
            }
        }
        (Some(value), None) | (None, Some(value)) => value,
        _ => return Err(invalid("model_max_length or max_length required")),
    };
    selected.length()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TokenDefinition {
    #[serde(default)]
    content: String,
    #[serde(default)]
    single_word: bool,
    #[serde(default)]
    lstrip: bool,
    #[serde(default)]
    rstrip: bool,
    #[serde(default = "normalized")]
    normalized: bool,
    #[serde(default)]
    special: bool,
}
fn normalized() -> bool {
    true
}

pub struct FastEmbedTokenizer {
    tokenizer: Tokenizer,
    requested_name: String,
}

impl FastEmbedTokenizer {
    pub(crate) fn from_source(
        model: &FastEmbedModel,
        source: &ModelFileSource,
    ) -> Result<Self, ModelError> {
        Self::load(model, |name| {
            model.assets().read_source_artifact(source.snapshot(), name)
        })
    }

    pub(crate) fn from_files(
        model: &FastEmbedModel,
        files: &VerifiedModelFiles,
    ) -> Result<Self, ModelError> {
        if files.fingerprint() != model.assets().fingerprint() {
            return Err(invalid(
                "verified files do not belong to the declared model",
            ));
        }
        Self::load(model, |name| files.read(name))
    }

    fn load(
        model: &FastEmbedModel,
        mut read: impl FnMut(&str) -> Result<Vec<u8>, ModelError>,
    ) -> Result<Self, ModelError> {
        let model_config: Object = serde_json::from_slice(&read("config.json")?)?;
        let config: Object = serde_json::from_slice(&read("tokenizer_config.json")?)?;
        let specials: Object = serde_json::from_slice(&read("special_tokens_map.json")?)?;
        let mut tokenizer = Tokenizer::from_bytes(read("tokenizer.json")?)
            .map_err(|error| invalid(&error.to_string()))?;
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: context(&config)?,
                ..Default::default()
            }))
            .map_err(|error| invalid(&error.to_string()))?;
        if tokenizer.get_padding().is_none() {
            let id = match model_config.get("pad_token_id") {
                Some(value) => serde_json::from_str::<u32>(value.get())?,
                None => 0,
            };
            let token = config
                .get("pad_token")
                .ok_or_else(|| invalid("pad_token required without serialized padding"))?;
            let token = serde_json::from_str::<String>(token.get())?;
            tokenizer.with_padding(Some(PaddingParams {
                pad_id: id,
                pad_token: token,
                ..Default::default()
            }));
        }
        for (_, value) in specials.0 {
            let token = match value.get().as_bytes().first() {
                Some(b'"') => Some(AddedToken::from(
                    serde_json::from_str::<String>(value.get())?,
                    true,
                )),
                Some(b'{') => {
                    let definition: TokenDefinition = serde_json::from_str(value.get())?;
                    Some(
                        AddedToken::from(definition.content, definition.special)
                            .single_word(definition.single_word)
                            .lstrip(definition.lstrip)
                            .rstrip(definition.rstrip)
                            .normalized(definition.normalized),
                    )
                }
                _ => None,
            };
            if let Some(token) = token {
                tokenizer.add_special_tokens(&[token]);
            }
        }
        Ok(Self {
            tokenizer,
            requested_name: model.name().into(),
        })
    }

    pub fn tokenize(
        &self,
        texts: &[&str],
        kind: FastEmbedInput,
    ) -> Result<Vec<FastEmbedTokens>, ModelError> {
        let prompts = crate::model_policy::prompts_for(&self.requested_name);
        let prompt = match kind {
            FastEmbedInput::Query => prompts.query,
            FastEmbedInput::Passage => prompts.passage,
        };
        let mut batches = Vec::new();
        for chunk in texts.chunks(256) {
            let input: Vec<_> = chunk.iter().map(|text| format!("{prompt}{text}")).collect();
            let encodings = self
                .tokenizer
                .encode_batch(input, true)
                .map_err(|error| invalid(&error.to_string()))?;
            let length = encodings[0].get_ids().len();
            if encodings.iter().any(|encoding| {
                encoding.get_ids().len() != length || encoding.get_attention_mask().len() != length
            }) {
                return Err(invalid("rectangular tokenizer batch required"));
            }
            batches.push(FastEmbedTokens {
                shape: [chunk.len(), length],
                ids: encodings
                    .iter()
                    .flat_map(|encoding| encoding.get_ids().iter().map(|id| i64::from(*id)))
                    .collect(),
                attention_mask: encodings
                    .iter()
                    .flat_map(|encoding| {
                        encoding
                            .get_attention_mask()
                            .iter()
                            .map(|mask| i64::from(*mask))
                    })
                    .collect(),
            });
        }
        Ok(batches)
    }
}
