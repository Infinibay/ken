use super::{Observation, Result, finish, number, raw};
use ken_retrieval::{matrix::Matrix, numeric_ranker::NumericRanker};
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
#[derive(Deserialize)]
struct Input {
    model: Box<RawValue>,
    rows: Option<usize>,
    columns: Option<usize>,
    values: Option<Vec<Value>>,
    left: Option<Vec<Value>>,
    right: Option<Vec<Value>>,
}
pub fn run(input: &str, kind: &str) -> Observation {
    finish(
        (|| {
            let input: Input = serde_json::from_str(input)?;
            let model = NumericRanker::from_json(input.model.get())?;
            let model_json = RawValue::from_string(model.to_json()?)?;
            match kind {
                "dict" => Ok(model_json),
                "model" => {
                    #[derive(Serialize)]
                    struct Model<'a> {
                        model: &'a RawValue,
                        canonical: String,
                        fingerprint: String,
                    }
                    raw(&Model {
                        model: &model_json,
                        canonical: model.to_json()?,
                        fingerprint: model.fingerprint()?,
                    })
                }
                "predict" => {
                    let matrix = Matrix::new(
                        input.rows.unwrap_or(0),
                        input.columns.unwrap_or(0),
                        input
                            .values
                            .unwrap_or_default()
                            .iter()
                            .map(number)
                            .collect::<Result<_>>()?,
                    )?;
                    #[derive(Serialize)]
                    struct Scores {
                        scores: Vec<Value>,
                        unchanged: bool,
                    }
                    raw(&Scores {
                        scores: model
                            .predict(&matrix)?
                            .into_iter()
                            .map(super::tagged)
                            .collect(),
                        unchanged: model.to_json()? == model_json.get(),
                    })
                }
                _ => raw(&model.explain_pair(
                    &input
                        .left
                        .unwrap_or_default()
                        .iter()
                        .map(number)
                        .collect::<Result<Vec<_>>>()?,
                    &input
                        .right
                        .unwrap_or_default()
                        .iter()
                        .map(number)
                        .collect::<Result<Vec<_>>>()?,
                )?),
            }
        })(),
        Observation::new(),
    )
}
