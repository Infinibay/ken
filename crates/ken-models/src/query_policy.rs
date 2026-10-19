//! Decide one query's language path and preserve exact code identifiers.
use crate::{ModelError, python_unicode as unicode};
use onig::{MatchParam, Regex, Region, SearchOptions};
use std::{collections::BTreeSet, sync::OnceLock};

const SPANISH: &str = "dónde donde cuál cual qué que cómo como quién quien función funcion método metodo clase prueba pruebas archivo encuentra busca devuelve convierte obtiene implementa contiene permite devuelve crea genera elimina cuando una uno los las para del con por";

#[derive(Clone, Debug)]
pub enum QueryExpansionPlan {
    Passthrough(String),
    Translate(ProtectedQuery),
}

#[derive(Clone, Debug)]
pub struct ProtectedQuery {
    text: String,
    values: Vec<String>,
}

fn protected_pattern() -> Result<&'static Regex, ModelError> {
    static PATTERN: OnceLock<Result<Regex, String>> = OnceLock::new();
    PATTERN.get_or_init(|| {
        let word = unicode::word_class();
        let decimal = unicode::decimal_class();
        let boundary = format!("(?:(?<!{word})(?={word})|(?<={word})(?!{word}))");
        // Explicit classes retain Python15 word boundaries; onig's own Unicode
        // Word/Digit categories would also admit marks and newer characters.
        let word_or_dollar = format!("(?:{word}|\\$)");
        // Choose the first underscore after the required initial character.
        // The suffix admits all subsequent underscores, so choosing a later
        // separator cannot change the longest match. This removes quadratic
        // repartitioning when a Unicode word character invalidates the end.
        let pattern = format!(
            "`[^`]+`|{boundary}[A-Za-z_$]{word_or_dollar}*(?:[.:]+{word_or_dollar}+)+{boundary}|{boundary}[A-Za-z_$][A-Za-z$]*_(?:[A-Za-z_$]|{decimal})+{boundary}"
        );
        Regex::new(&pattern).map_err(|error| error.to_string())
    }).as_ref().map_err(|error| ModelError::Tokenizer(error.clone()))
}

pub fn plan_query(query: &str) -> Result<QueryExpansionPlan, ModelError> {
    if !query.contains('¿') {
        let folded = unicode::casefold(query);
        let words: BTreeSet<_> = folded
            .split(|value| !unicode::word(value))
            .filter(|word| !word.is_empty())
            .collect();
        if words
            .iter()
            .filter(|word| SPANISH.split_whitespace().any(|spanish| spanish == **word))
            .take(2)
            .count()
            < 2
        {
            return Ok(QueryExpansionPlan::Passthrough(query.to_owned()));
        }
    }
    let mut text = String::with_capacity(query.len());
    let mut values = Vec::new();
    let mut cursor = 0;
    let pattern = protected_pattern()?;
    let mut region = Region::new();
    while pattern
        .search_with_param(
            query,
            cursor,
            query.len(),
            SearchOptions::SEARCH_OPTION_NONE,
            Some(&mut region),
            MatchParam::default(),
        )
        .map_err(|error| ModelError::Tokenizer(error.to_string()))?
        .is_some()
    {
        let (start, end) = region.pos(0).ok_or_else(|| {
            ModelError::Tokenizer("protected identifier match has no range".into())
        })?;
        text.push_str(&query[cursor..start]);
        text.push_str(&format!("ZXQ{}QXZ", values.len()));
        values.push(query[start..end].to_owned());
        cursor = end;
    }
    text.push_str(&query[cursor..]);
    Ok(QueryExpansionPlan::Translate(ProtectedQuery {
        text,
        values,
    }))
}

fn placeholder_end(text: &str, start: usize, key: &str) -> Option<usize> {
    let mut cursor = start;
    for (index, expected) in key.bytes().enumerate() {
        if index != 0 {
            while let Some(value) = text[cursor..]
                .chars()
                .next()
                .filter(|value| unicode::space(*value))
            {
                cursor += value.len_utf8();
            }
        }
        let value = text[cursor..].chars().next()?;
        // Keys contain only Z/X/Q and digits, whose Python IGNORECASE matches
        // are exactly their ASCII upper/lower spellings.
        if !value.is_ascii() || !(value as u8).eq_ignore_ascii_case(&expected) {
            return None;
        }
        cursor += value.len_utf8();
    }
    Some(cursor)
}

fn restore_key(text: &str, key: &str, original: &str) -> String {
    let mut restored = String::with_capacity(text.len());
    let mut cursor = 0;
    while cursor < text.len() {
        if let Some(end) = placeholder_end(text, cursor, key) {
            restored.push_str(original);
            cursor = end;
        } else {
            let value = text[cursor..]
                .chars()
                .next()
                .expect("cursor is before the end at a UTF8 boundary");
            restored.push(value);
            cursor += value.len_utf8();
        }
    }
    restored
}

impl ProtectedQuery {
    pub fn text(&self) -> &str {
        &self.text
    }
    pub fn protected_values(&self) -> &[String] {
        &self.values
    }

    pub fn restore(&self, decoded: &str) -> Result<String, ModelError> {
        let mut text = decoded.to_owned();
        for (index, value) in self.values.iter().enumerate() {
            text = restore_key(&text, &format!("ZXQ{index}QXZ"), value);
        }
        if text.chars().all(unicode::space) {
            return Err(ModelError::Inference(
                "local query expansion produced empty text".into(),
            ));
        }
        Ok(text)
    }
}
