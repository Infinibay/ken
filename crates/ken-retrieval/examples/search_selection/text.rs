use super::raw;
use ken_retrieval::{
    EntityKey, Passage, Result,
    description::describe_owner,
    intent::{interpret, requested_piece_kind, requested_piece_path},
    query::SearchRequest,
    source_locator::{module_name, symbol_locator},
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
pub(super) fn run(input: &str, kind: &str) -> Result<Box<RawValue>> {
    match kind {
        "intent" => {
            let i: SearchRequest = serde_json::from_str(input)?;
            #[derive(Serialize)]
            struct Output {
                intent: ken_retrieval::intent::QueryIntent,
                piece_kind: String,
                path: Option<PythonText>,
            }
            raw(&Output {
                intent: interpret(&i),
                piece_kind: requested_piece_kind(&i),
                path: requested_piece_path(&i),
            })
        }
        "locator" => {
            #[derive(Deserialize)]
            struct Input {
                query: PythonText,
                entities: Vec<EntityKey>,
            }
            let i: Input = serde_json::from_str(input)?;
            let locator = symbol_locator(&i.query);
            #[derive(Serialize)]
            struct Output {
                locator: Option<ken_retrieval::source_locator::SymbolLocator>,
                matches: Vec<bool>,
            }
            let matches = i
                .entities
                .iter()
                .map(|e| locator.as_ref().is_some_and(|l| l.matches(e)))
                .collect();
            raw(&Output { locator, matches })
        }
        "module" => {
            #[derive(Deserialize)]
            struct Input {
                path: String,
            }
            let i: Input = serde_json::from_str(input)?;
            raw(&module_name(&i.path))
        }
        "identifier" => {
            #[derive(Deserialize)]
            struct Input {
                text: PythonText,
            }
            let i: Input = serde_json::from_str(input)?;
            raw(&i
                .text
                .to_utf8()
                .is_some_and(|s| ken_text::unicode::identifier(&s)))
        }
        "description" => {
            #[derive(Deserialize)]
            struct Input {
                passages: Vec<Passage>,
            }
            let i: Input = serde_json::from_str(input)?;
            raw(&describe_owner(&i.passages)?)
        }
        _ => unreachable!("bounded text operation"),
    }
}
