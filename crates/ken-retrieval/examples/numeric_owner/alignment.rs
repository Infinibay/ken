use super::{Observation, Result, finish, invalid, number, raw, tagged};
use ken_retrieval::{
    alignment::{FloatMatrix, FloatVector, TermAlignment, TermCoverage},
    matrix::Matrix,
};
use serde::Deserialize;
use serde_json::{Value, json};
#[derive(Deserialize)]
struct Input {
    query: Numbers,
    weights: Numbers,
    documents: Option<Numbers>,
    similarities: Option<Numbers>,
    maxima: Option<Numbers>,
    present: Option<Vec<bool>>,
}
#[derive(Deserialize)]
struct Numbers {
    dtype: String,
    rows: Option<usize>,
    columns: Option<usize>,
    values: Vec<Value>,
}
impl Numbers {
    fn matrix(&self) -> Result<FloatMatrix> {
        let values = self.values.iter().map(number).collect::<Result<Vec<_>>>()?;
        let rows = self.rows.ok_or_else(|| invalid("matrix rows required"))?;
        let columns = self
            .columns
            .ok_or_else(|| invalid("matrix columns required"))?;
        match self.dtype.as_str() {
            "float32" => Ok(FloatMatrix::F32(Matrix::new(
                rows,
                columns,
                values.into_iter().map(|v| v as f32).collect(),
            )?)),
            "float64" => Ok(FloatMatrix::F64(Matrix::new(rows, columns, values)?)),
            _ => Err(invalid("float32 or float64 required")),
        }
    }
    fn vector(&self) -> Result<FloatVector> {
        let values = self.values.iter().map(number).collect::<Result<Vec<_>>>()?;
        match self.dtype.as_str() {
            "float32" => Ok(FloatVector::F32(
                values.into_iter().map(|v| v as f32).collect(),
            )),
            "float64" => Ok(FloatVector::F64(values)),
            _ => Err(invalid("float32 or float64 required")),
        }
    }
}
fn summary(c: TermCoverage) -> Value {
    json!({"mean":tagged(c.mean),"minimum":tagged(c.minimum),"quartile":tagged(c.quartile),"above50":tagged(c.above50),"above70":tagged(c.above70),"weighted":tagged(c.weighted)})
}
pub fn run(input: &str, kind: &str) -> Observation {
    finish(
        (|| {
            let input: Input = serde_json::from_str(input)?;
            let alignment = TermAlignment::new(input.query.matrix()?, input.weights.vector()?)?;
            let required = |v: Option<Numbers>| v.ok_or_else(|| invalid("matrix input required"));
            match kind {
                "similarities" | "coverage" => {
                    let documents = required(input.documents)?.matrix()?;
                    let matrix = alignment.similarities(&documents)?;
                    let (rows, columns, dtype, values) = match matrix {
                        FloatMatrix::F32(m) => (
                            m.rows(),
                            m.columns(),
                            "float32",
                            m.values()
                                .iter()
                                .map(|n| tagged(*n as f64))
                                .collect::<Vec<_>>(),
                        ),
                        FloatMatrix::F64(m) => (
                            m.rows(),
                            m.columns(),
                            "float64",
                            m.values().iter().map(|n| tagged(*n)).collect(),
                        ),
                    };
                    let mut value =
                        json!({"rows":rows,"columns":columns,"dtype":dtype,"values":values});
                    if kind == "coverage" {
                        value["coverage"] = summary(alignment.coverage(&documents)?);
                    }
                    raw(&value)
                }
                "summarize" => raw(&summary(
                    alignment.summarize(&required(input.similarities)?.matrix()?)?,
                )),
                _ => raw(&alignment
                    .summarize_maxima(
                        &required(input.maxima)?.matrix()?,
                        &input
                            .present
                            .ok_or_else(|| invalid("presence mask required"))?,
                    )?
                    .into_iter()
                    .map(summary)
                    .collect::<Vec<_>>()),
            }
        })(),
        Observation::new(),
    )
}
