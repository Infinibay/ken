use super::{Observation, Result, finish, invalid, raw};
use ken_retrieval::stemming::{EnglishStems, WordStemmer};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};
#[derive(Deserialize)]
struct Input {
    #[serde(default)]
    words: Vec<PythonText>,
    #[serde(default)]
    groups: Vec<Vec<PythonText>>,
    #[serde(default)]
    batches: Vec<Vec<PythonText>>,
    prefix: Option<String>,
    count: Option<usize>,
    #[serde(default)]
    providers: Vec<String>,
    #[serde(default)]
    order: Vec<String>,
}
struct Provider {
    prefix: String,
    calls: Arc<Mutex<Vec<PythonText>>>,
}
impl WordStemmer for Provider {
    fn stem(&self, w: &PythonText) -> Result<PythonText> {
        self.calls
            .lock()
            .map_err(|_| invalid("stem provider poisoned"))?
            .push(w.clone());
        Ok(PythonText::from_codepoints(
            [
                PythonText::from(self.prefix.as_str()).codepoints(),
                w.codepoints(),
            ]
            .concat(),
        )
        .expect("owned codepoints"))
    }
}
pub fn run(input: &str, kind: &str) -> Observation {
    finish(
        (|| {
            let input: Input = serde_json::from_str(input)?;
            match kind {
                "stem" => raw(&EnglishStems::shared().stem_words(&input.words)?),
                "stem_concurrent" => {
                    let provider = EnglishStems::shared();
                    let groups = &input.groups;
                    let outputs = std::thread::scope(|scope| -> Result<Vec<Vec<PythonText>>> {
                        let jobs: Vec<_> = (0..8)
                            .map(|worker| {
                                let p = &provider;
                                scope.spawn(move || -> Result<Vec<_>> {
                                    groups
                                        .iter()
                                        .enumerate()
                                        .skip(worker)
                                        .step_by(8)
                                        .map(|(i, g)| Ok((i, p.stem_words(g)?)))
                                        .collect()
                                })
                            })
                            .collect();
                        let mut outputs = vec![Vec::new(); groups.len()];
                        for job in jobs {
                            for (i, g) in
                                job.join().map_err(|_| invalid("stem worker panicked"))??
                            {
                                outputs[i] = g;
                            }
                        }
                        Ok(outputs)
                    })?;
                    raw(&outputs)
                }
                "stem_reuse" | "stem_capacity" => {
                    let calls = Arc::new(Mutex::new(Vec::new()));
                    let stems = EnglishStems::with_provider(Arc::new(Provider {
                        prefix: input.prefix.unwrap_or_default(),
                        calls: calls.clone(),
                    }));
                    if kind == "stem_reuse" {
                        let mut batches = Vec::new();
                        for words in input.batches {
                            let mut output = stems.stem_words(&words)?;
                            batches.push(output.clone());
                            if !output.is_empty() {
                                output[0] = "mutated".into();
                            }
                        }
                        {
                            #[derive(Serialize)]
                            struct Reuse<'a> {
                                batches: Vec<Vec<PythonText>>,
                                calls: &'a [PythonText],
                                entries: usize,
                                capacity: usize,
                            }
                            raw(&Reuse {
                                batches,
                                calls: &calls.lock().unwrap(),
                                entries: stems.cached_words(),
                                capacity: 32768,
                            })
                        }
                    } else {
                        let count = input
                            .count
                            .ok_or_else(|| invalid("stem capacity count required"))?;
                        if count == 0 || count > 65536 {
                            return Err(invalid("bounded stem capacity count required"));
                        }
                        let words: Vec<_> = (0..count)
                            .map(|i| PythonText::from(format!("term{i}")))
                            .collect();
                        stems.stem_words(&words)?;
                        let output =
                            stems.stem_words(&[words[0].clone(), words[count - 1].clone()])?;
                        {
                            #[derive(Serialize)]
                            struct Capacity<'a> {
                                output: Vec<PythonText>,
                                calls: &'a [PythonText],
                                entries: usize,
                                capacity: usize,
                            }
                            raw(&Capacity {
                                output,
                                calls: &calls.lock().unwrap(),
                                entries: stems.cached_words(),
                                capacity: 32768,
                            })
                        }
                    }
                }
                _ => {
                    let mut providers = BTreeMap::new();
                    let mut logs = BTreeMap::new();
                    let mut calls = Vec::new();
                    let mut outputs = Vec::new();
                    for prefix in input.providers {
                        let log = Arc::new(Mutex::new(Vec::new()));
                        providers.insert(
                            prefix.clone(),
                            EnglishStems::with_provider(Arc::new(Provider {
                                prefix: prefix.clone(),
                                calls: log.clone(),
                            })),
                        );
                        logs.insert(prefix, log);
                    }
                    for name in input.order {
                        let provider = providers
                            .get(&name)
                            .ok_or_else(|| invalid("unknown explicit stem provider"))?;
                        outputs.push(provider.stem_words(&input.words)?);
                        calls.extend(
                            logs[&name]
                                .lock()
                                .unwrap()
                                .drain(..)
                                .map(|w| (name.clone(), w)),
                        );
                    }
                    {
                        #[derive(Serialize)]
                        struct Providers {
                            outputs: Vec<Vec<PythonText>>,
                            calls: Vec<(String, PythonText)>,
                        }
                        raw(&Providers { outputs, calls })
                    }
                }
            }
        })(),
        Observation::new(),
    )
}
