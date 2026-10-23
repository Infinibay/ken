use ken_retrieval::{
    Result,
    stemming::{EnglishStems, WordStemmer},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::value::RawValue;
use std::{
    collections::BTreeMap,
    sync::{Arc, Barrier, Mutex, mpsc},
    time::Duration,
};
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Input,
    result: Box<RawValue>,
}
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
    fn stem(&self, word: &PythonText) -> Result<PythonText> {
        self.calls.lock().unwrap().push(word.clone());
        Ok(PythonText::from_codepoints(
            [
                PythonText::from(self.prefix.as_str()).codepoints(),
                word.codepoints(),
            ]
            .concat(),
        )
        .unwrap())
    }
}
#[test]
fn original_english_words_provider_ownership_and_bounded_reuse() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/numeric-reference-stems.json")).unwrap();
    assert_eq!(corpus.cases.len(), 74);
    for case in corpus.cases {
        match case.kind.as_str() {
            "stem" => {
                let expected: Vec<PythonText> = serde_json::from_str(case.result.get()).unwrap();
                assert_eq!(
                    EnglishStems::shared()
                        .stem_words(&case.input.words)
                        .unwrap(),
                    expected,
                    "{}",
                    case.id
                );
            }
            "stem_concurrent" => {
                let expected: Vec<Vec<PythonText>> =
                    serde_json::from_str(case.result.get()).unwrap();
                let provider = EnglishStems::shared();
                let groups = &case.input.groups;
                let outputs = std::thread::scope(|scope| {
                    let jobs: Vec<_> = (0..8)
                        .map(|worker| {
                            let p = &provider;
                            scope.spawn(move || {
                                groups
                                    .iter()
                                    .enumerate()
                                    .skip(worker)
                                    .step_by(8)
                                    .map(|(i, g)| (i, p.stem_words(g).unwrap()))
                                    .collect::<Vec<_>>()
                            })
                        })
                        .collect();
                    let mut out = vec![Vec::new(); groups.len()];
                    for job in jobs {
                        for (i, g) in job.join().unwrap() {
                            out[i] = g;
                        }
                    }
                    out
                });
                assert_eq!(outputs, expected, "{}", case.id);
            }
            "stem_reuse" => {
                #[derive(Deserialize)]
                struct Expected {
                    batches: Vec<Vec<PythonText>>,
                    calls: Vec<PythonText>,
                    entries: usize,
                    capacity: usize,
                }
                let expected: Expected = serde_json::from_str(case.result.get()).unwrap();
                let calls = Arc::new(Mutex::new(Vec::new()));
                let stems = EnglishStems::with_provider(Arc::new(Provider {
                    prefix: case.input.prefix.unwrap(),
                    calls: calls.clone(),
                }));
                for (words, want) in case.input.batches.iter().zip(&expected.batches) {
                    let mut got = stems.stem_words(words).unwrap();
                    assert_eq!(&got, want, "{}", case.id);
                    if !got.is_empty() {
                        got[0] = "mutated".into();
                    }
                }
                assert_eq!(*calls.lock().unwrap(), expected.calls, "{}", case.id);
                assert_eq!(stems.cached_words(), expected.entries);
                assert_eq!(expected.capacity, 32768);
            }
            "stem_capacity" => {
                #[derive(Deserialize)]
                struct Expected {
                    output: Vec<PythonText>,
                    calls: Vec<PythonText>,
                    entries: usize,
                    capacity: usize,
                }
                let expected: Expected = serde_json::from_str(case.result.get()).unwrap();
                let calls = Arc::new(Mutex::new(Vec::new()));
                let stems = EnglishStems::with_provider(Arc::new(Provider {
                    prefix: String::new(),
                    calls: calls.clone(),
                }));
                let words: Vec<_> = (0..case.input.count.unwrap())
                    .map(|i| PythonText::from(format!("term{i}")))
                    .collect();
                stems.stem_words(&words).unwrap();
                let got = stems
                    .stem_words(&[words[0].clone(), words.last().unwrap().clone()])
                    .unwrap();
                assert_eq!(got, expected.output);
                assert_eq!(*calls.lock().unwrap(), expected.calls);
                assert_eq!(stems.cached_words(), expected.entries);
                assert_eq!(expected.capacity, 32768);
            }
            "stem_providers" => {
                #[derive(Deserialize)]
                struct Expected {
                    outputs: Vec<Vec<PythonText>>,
                    calls: Vec<(String, PythonText)>,
                }
                let expected: Expected = serde_json::from_str(case.result.get()).unwrap();
                let mut providers = BTreeMap::new();
                let mut logs = BTreeMap::new();
                let mut calls = Vec::new();
                for prefix in &case.input.providers {
                    let log = Arc::new(Mutex::new(Vec::new()));
                    providers.insert(
                        prefix.clone(),
                        EnglishStems::with_provider(Arc::new(Provider {
                            prefix: prefix.clone(),
                            calls: log.clone(),
                        })),
                    );
                    logs.insert(prefix.clone(), log);
                }
                for (provider, want) in case.input.order.iter().zip(&expected.outputs) {
                    let got = providers[provider].stem_words(&case.input.words).unwrap();
                    assert_eq!(&got, want);
                    let mut log = logs[provider].lock().unwrap();
                    calls.extend(log.drain(..).map(|w| (provider.clone(), w)));
                }
                assert_eq!(calls, expected.calls);
            }
            _ => panic!("unknown stem operation"),
        }
    }
}
#[test]
fn shared_english_owner_is_reused_and_concurrent_misses_hold_no_cache_lock() {
    assert!(Arc::ptr_eq(
        &EnglishStems::shared(),
        &EnglishStems::shared()
    ));
    struct Gate(Barrier);
    impl WordStemmer for Gate {
        fn stem(&self, w: &PythonText) -> Result<PythonText> {
            self.0.wait();
            Ok(w.clone())
        }
    }
    let stems = Arc::new(EnglishStems::with_provider(Arc::new(Gate(Barrier::new(8)))));
    let (send, receive) = mpsc::channel();
    for i in 0..8 {
        let stems = stems.clone();
        let send = send.clone();
        std::thread::spawn(move || {
            let word = PythonText::from(format!("miss{i}"));
            send.send(stems.stem_words(&[word])).unwrap();
        });
    }
    for _ in 0..8 {
        assert_eq!(
            receive
                .recv_timeout(Duration::from_secs(10))
                .expect("concurrent misses must reach independent providers")
                .unwrap()
                .len(),
            1
        );
    }
    assert_eq!(stems.cached_words(), 8);
}
