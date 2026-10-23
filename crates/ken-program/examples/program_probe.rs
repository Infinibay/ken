//! Bounded input-only adapter for actual native common-model observations.
use ken_program::{
    BodyRange, Environment, Program, ProgramError, Resolution, StructuralIr, TypeRef, body_ranges,
    normalize, parse_type,
};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use std::{
    collections::BTreeSet,
    io::{self, Read, Write},
};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    cases: Vec<Case>,
}
enum Case {
    Normalize {
        id: String,
        ir: Box<StructuralIr>,
        lookups: Vec<Lookup>,
    },
    Codec {
        id: String,
        program: Box<RawValue>,
    },
    Type {
        id: String,
        annotation: String,
        language: String,
    },
}
impl<'de> Deserialize<'de> for Case {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        use serde::de::Error;
        // Internally tagged serde enums buffer values and cannot retain RawValue.
        // Select the strict wire struct from the original JSON token instead.
        let raw = Box::<RawValue>::deserialize(deserializer)?;
        #[derive(Deserialize)]
        struct Header {
            kind: String,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Normalize {
            id: String,
            #[serde(rename = "kind")]
            _kind: String,
            ir: Box<StructuralIr>,
            lookups: Vec<Lookup>,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Codec {
            id: String,
            #[serde(rename = "kind")]
            _kind: String,
            program: Box<RawValue>,
        }
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Type {
            id: String,
            #[serde(rename = "kind")]
            _kind: String,
            annotation: String,
            language: String,
        }
        let header: Header = serde_json::from_str(raw.get()).map_err(D::Error::custom)?;
        match header.kind.as_str() {
            "normalize" => {
                let value: Normalize = serde_json::from_str(raw.get()).map_err(D::Error::custom)?;
                Ok(Self::Normalize {
                    id: value.id,
                    ir: value.ir,
                    lookups: value.lookups,
                })
            }
            "codec" => {
                let value: Codec = serde_json::from_str(raw.get()).map_err(D::Error::custom)?;
                Ok(Self::Codec {
                    id: value.id,
                    program: value.program,
                })
            }
            "type" => {
                let value: Type = serde_json::from_str(raw.get()).map_err(D::Error::custom)?;
                Ok(Self::Type {
                    id: value.id,
                    annotation: value.annotation,
                    language: value.language,
                })
            }
            _ => Err(D::Error::custom("unknown program request kind")),
        }
    }
}
impl Case {
    fn id(&self) -> &str {
        match self {
            Self::Normalize { id, .. } | Self::Codec { id, .. } | Self::Type { id, .. } => id,
        }
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Lookup {
    name: String,
    scope: i64,
    point: i64,
}
#[derive(Serialize)]
struct Failure {
    kind: &'static str,
    message: String,
}
impl From<ProgramError> for Failure {
    fn from(error: ProgramError) -> Self {
        Self {
            kind: "invalid_program",
            message: error.to_string(),
        }
    }
}
#[derive(Serialize)]
#[serde(untagged)]
enum LookupResult {
    Success { result: Resolution },
    Error { error: Failure },
}
#[derive(Serialize)]
struct ObservedLookup {
    #[serde(flatten)]
    query: Lookup,
    #[serde(flatten)]
    result: LookupResult,
}
#[derive(Serialize)]
#[serde(untagged)]
enum Outcome {
    Normalize {
        program: Program,
        bodies: Vec<BodyRange>,
        lookups: Vec<ObservedLookup>,
    },
    Codec {
        program: Program,
    },
    Type {
        descriptor: TypeRef,
    },
    Error {
        error: Failure,
    },
}
#[derive(Serialize)]
struct Observed {
    id: String,
    #[serde(flatten)]
    outcome: Outcome,
}
#[derive(Serialize)]
struct Response {
    format: &'static str,
    cases: Vec<Observed>,
}
fn observe(case: Case) -> Observed {
    match case {
        Case::Normalize { id, ir, lookups } => {
            let outcome = match normalize(&ir) {
                Err(error) => Outcome::Error {
                    error: error.into(),
                },
                Ok(program) => {
                    let environment = Environment::new(&program);
                    let lookups = lookups
                        .into_iter()
                        .map(|query| {
                            let result =
                                match environment.resolve(&query.name, query.scope, query.point) {
                                    Ok(result) => LookupResult::Success { result },
                                    Err(error) => LookupResult::Error {
                                        error: error.into(),
                                    },
                                };
                            ObservedLookup { query, result }
                        })
                        .collect();
                    let bodies = body_ranges(&program);
                    Outcome::Normalize {
                        program,
                        bodies,
                        lookups,
                    }
                }
            };
            Observed { id, outcome }
        }
        Case::Codec { id, program } => Observed {
            id,
            outcome: match Program::from_json(program.get()) {
                Ok(program) => Outcome::Codec { program },
                Err(error) => Outcome::Error {
                    error: error.into(),
                },
            },
        },
        Case::Type {
            id,
            annotation,
            language,
        } => Observed {
            id,
            outcome: Outcome::Type {
                descriptor: parse_type(&annotation, &language),
            },
        },
    }
}
fn run() -> Result<(), Box<dyn std::error::Error>> {
    const INPUT: u64 = 8 * 1024 * 1024;
    let mut bytes = Vec::new();
    io::stdin().take(INPUT + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > INPUT {
        return Err("program request exceeds8MiB".into());
    }
    let request: Request = serde_json::from_slice(&bytes)?;
    if request.cases.len() > 4096 {
        return Err("program case limit exceeded".into());
    }
    let mut ids = BTreeSet::new();
    let mut lookups = 0;
    for case in &request.cases {
        if !ids.insert(case.id()) {
            return Err("duplicate program identity".into());
        }
        if let Case::Normalize {
            lookups: queries, ..
        } = case
        {
            lookups += queries.len();
        }
    }
    if lookups > 8192 {
        return Err("program lookup limit exceeded".into());
    }
    let response = Response {
        format: "ken-program-observation/1",
        cases: request.cases.into_iter().map(observe).collect(),
    };
    let bytes = serde_json::to_vec(&response)?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("program response exceeds16MiB".into());
    }
    let mut out = io::stdout().lock();
    out.write_all(&bytes)?;
    out.flush()?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("program_probe: {error}");
        std::process::exit(1);
    }
}
