use flate2::read::GzDecoder;
use ken_query::execution::{
    ExecutionError,
    regex_runtime::{Dialect, Pattern},
};
use ken_text::PythonText;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::io::Read;
#[derive(serde::Deserialize)]
struct Corpus {
    python: String,
    regex: String,
    stdlib_unicode: String,
    cases: Vec<Case>,
}
#[derive(serde::Deserialize)]
struct Case {
    id: usize,
    #[serde(deserialize_with = "original_json_text")]
    pattern: PythonText,
    #[serde(deserialize_with = "original_json_text")]
    text: PythonText,
    flags: String,
    dialects: std::collections::BTreeMap<String, Value>,
}
// The frozen Python observer writes ensure_ascii JSON: a non-BMP scalar is
// represented by a UTF16 escape pair. Reproduce Python json.loads pair joining
// while preserving isolated surrogate escapes; PythonText itself deliberately
// retains each escaped codepoint for its lossless native transport contract.
fn original_json_text<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<PythonText, D::Error> {
    let text = <PythonText as serde::Deserialize>::deserialize(deserializer)?;
    let mut points = Vec::new();
    let mut at = 0;
    let input = text.codepoints();
    while at < input.len() {
        let cp = input[at];
        if (0xd800..=0xdbff).contains(&cp)
            && input
                .get(at + 1)
                .is_some_and(|c| (0xdc00..=0xdfff).contains(c))
        {
            points.push(0x10000 + ((cp - 0xd800) << 10) + (input[at + 1] - 0xdc00));
            at += 2;
        } else {
            points.push(cp);
            at += 1;
        }
    }
    PythonText::from_codepoints(points)
        .ok_or_else(|| serde::de::Error::custom("invalid original codepoint"))
}
fn corpus() -> Corpus {
    let bytes = include_bytes!("fixtures/regex-runtime-reference.json.gz");
    assert_eq!(bytes.len(), 15885);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "437e94b2d75114725148511bb25c55cbc6ac2864c7f3f9b7c781a8aee01137ce"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let mut corpus: Corpus = serde_json::from_str(&text).unwrap();
    let bytes = include_bytes!("fixtures/regex-runtime-edges-reference.json.gz");
    assert_eq!(bytes.len(), 12287);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "31e5d28f7304060758514a0b99fd1635c5db48955f4a54812a01dd8130f19c6c"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let extra: Corpus = serde_json::from_str(&text).unwrap();
    corpus.cases.extend(extra.cases);
    let bytes = include_bytes!("fixtures/regex-runtime-extended-reference.json.gz");
    assert_eq!(bytes.len(), 9566);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "44da39b9119dac2921839c203adfaaf06e880198f512f244a57341bc14584461"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let extra: Corpus = serde_json::from_str(&text).unwrap();
    corpus.cases.extend(extra.cases);
    let bytes = include_bytes!("fixtures/regex-runtime-grammar-reference.json.gz");
    assert_eq!(bytes.len(), 7672);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "671e5896df4e4a9cb942124c21a4ac51d9e9ffa94d74e234fbd7e3bc4db0f31f"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let extra: Corpus = serde_json::from_str(&text).unwrap();
    corpus.cases.extend(extra.cases);
    corpus
}
#[test]
fn frozen_stdlib_and_regex_dialects_preserve_matching_and_rejections() {
    let f = corpus();
    assert_eq!(f.python, "3.12.9");
    assert_eq!(f.regex, "2026.7.19");
    assert_eq!(f.stdlib_unicode, "15.0.0");
    let mut errors = vec![];
    let mut checked = 0;
    for case in &f.cases {
        for (name, dialect) in [("Stdlib", Dialect::Stdlib), ("Regex", Dialect::Regex)] {
            let expected = &case.dialects[name];
            let compiled =
                Pattern::compile_text(&case.pattern, &case.flags, dialect, &mut || Ok(()));
            if expected.get("compile_error").is_some() {
                if compiled.is_ok() {
                    errors.push(format!(
                        "{} {name} accepted invalid {}",
                        case.id,
                        serde_json::to_string(&case.pattern).unwrap()
                    ));
                }
                continue;
            }
            let pattern = match compiled {
                Ok(p) => p,
                Err(e) => {
                    errors.push(format!(
                        "{} {name} unexpected compile {e}: {}",
                        case.id,
                        serde_json::to_string(&case.pattern).unwrap()
                    ));
                    continue;
                }
            };
            let result = pattern.is_match(&case.text, &mut || Ok(()));
            if expected.get("runtime_error").is_some() {
                if result.is_ok() {
                    errors.push(format!(
                        "{} {name} expected runtime failure {}",
                        case.id,
                        serde_json::to_string(&case.pattern).unwrap()
                    ));
                }
                continue;
            }
            match result {
                Ok(v) if Some(v) == expected["matched"].as_bool() => (),
                got => errors.push(format!(
                    "{} {name} {} on {}: {got:?} != {}",
                    case.id,
                    serde_json::to_string(&case.pattern).unwrap(),
                    serde_json::to_string(&case.text).unwrap(),
                    expected["matched"]
                )),
            };
            checked += 1;
        }
    }
    assert!(checked > 4000, "runtime corpus shrank: {checked}");
    let mut grouped = std::collections::BTreeMap::<String, usize>::new();
    for error in &errors {
        *grouped
            .entry(
                error
                    .split_once(' ')
                    .map_or(error.as_str(), |(_, message)| message)
                    .to_owned(),
            )
            .or_default() += 1;
    }
    assert!(
        errors.is_empty(),
        "{} differences in {} groups\n{}",
        errors.len(),
        grouped.len(),
        grouped
            .iter()
            .map(|(message, count)| format!("{count}x {message}"))
            .collect::<Vec<_>>()
            .join("\n")
    );
}
#[test]
fn matching_and_compilation_are_cooperatively_interruptible() {
    assert!(matches!(
        Pattern::compile("a", "", Dialect::Regex, &mut || Err(
            ExecutionError::Exhausted("cancelled")
        )),
        Err(ExecutionError::Exhausted("cancelled"))
    ));
    let p = Pattern::compile("(?:a|aa)*b", "", Dialect::Regex, &mut || Ok(())).unwrap();
    let mut checks = 0;
    let result = p.is_match(&"a".repeat(10000).into(), &mut || {
        checks += 1;
        if checks > 20 {
            Err(ExecutionError::Exhausted("cancelled"))
        } else {
            Ok(())
        }
    });
    assert!(matches!(
        result,
        Err(ExecutionError::Exhausted("cancelled"))
    ));
    assert!(p.is_match(&"aab".into(), &mut || Ok(())).unwrap());
}
#[test]
fn frozen_unicode_facts_include_every_recorded_property_and_surrogates() {
    let bytes = include_bytes!("../resources/regex-runtime-unicode.json");
    assert_eq!(bytes.len(), 1123541);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "84c8d934e28e6d2e927ecf2a3375ef01cec7824675a9d0406e9a3e87b3919108"
    );
    let value: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(value["properties"].as_object().unwrap().len(), 1436);
    for (dialect, pattern, text, expected) in [
        (Dialect::Stdlib, "a{e<=1}", "b", false),
        (Dialect::Regex, "a{e<=1}", "b", true),
    ] {
        assert_eq!(
            Pattern::compile(pattern, "", dialect, &mut || Ok(()))
                .unwrap()
                .is_match(&text.into(), &mut || Ok(()))
                .unwrap(),
            expected
        );
    }
    let text = PythonText::from_codepoints(vec![0xd800]).unwrap();
    assert!(
        Pattern::compile(".", "", Dialect::Regex, &mut || Ok(()))
            .unwrap()
            .is_match(&text, &mut || Ok(()))
            .unwrap()
    );
}
#[test]
fn literal_surrogate_pattern_inputs_are_lossless_too() {
    for dialect in [Dialect::Stdlib, Dialect::Regex] {
        for points in [vec![0xd800], vec![92, 0xd800], vec![92, 92, 0xd800]] {
            let pattern = PythonText::from_codepoints(points.clone()).unwrap();
            let text = PythonText::from_codepoints(if points.len() == 3 {
                vec![92, 0xd800]
            } else {
                vec![0xd800]
            })
            .unwrap();
            assert!(
                Pattern::compile_text(&pattern, "", dialect, &mut || Ok(()))
                    .unwrap()
                    .is_match(&text, &mut || Ok(()))
                    .unwrap()
            );
        }
    }
}
#[test]
fn group_names_follow_the_shared_frozen_python_identifier_contract() {
    for dialect in [Dialect::Stdlib, Dialect::Regex] {
        for name in ["a\u{301}", "π", "x\u{661}", "_"] {
            assert!(ken_text::unicode::identifier(name));
            let source = format!("(?P<{name}>a)(?P={name})");
            let pattern = Pattern::compile(&source, "", dialect, &mut || Ok(())).unwrap();
            assert!(pattern.is_match(&"aa".into(), &mut || Ok(())).unwrap());
            assert!(!pattern.is_match(&"ab".into(), &mut || Ok(())).unwrap());
        }
        for name in ["", "1x", "a-", "a²", "\u{301}a"] {
            assert!(!ken_text::unicode::identifier(name));
            assert!(
                Pattern::compile(&format!("(?P<{name}>a)"), "", dialect, &mut || Ok(())).is_err()
            );
        }
    }
}

#[test]
fn bare_property_aliases_and_malformed_named_escape_follow_the_same_pinned_rules() {
    // regex_core.lookup_property defines a bare nonbinary alias as not value0.
    // Both sides use the already pinned exhaustive pid/value membership facts.
    for (bare, explicit) in [
        (r"\p{GC}", r"\P{GC=Cn}"),
        (r"\P{GC}", r"\p{GC=Cn}"),
        (r"\p{Script}", r"\P{Script=Unknown}"),
        (r"\p{WordBreak}", r"\P{WordBreak=Other}"),
    ] {
        let a = Pattern::compile(bare, "", Dialect::Regex, &mut || Ok(())).unwrap();
        let b = Pattern::compile(explicit, "", Dialect::Regex, &mut || Ok(())).unwrap();
        for cp in [
            0, 32, 65, 97, 0x301, 0x378, 0x3b1, 0x200d, 0xd800, 0x1f600, 0x10ffff,
        ] {
            let text = PythonText::from_codepoints(vec![cp]).unwrap();
            assert_eq!(
                a.is_match(&text, &mut || Ok(())).unwrap(),
                b.is_match(&text, &mut || Ok(())).unwrap(),
                "{bare} U+{cp:x}"
            );
        }
    }
    // Regex parse_named_char rewinds malformed delimiters to a literal N;
    // correctly delimited unknown names remain errors, as in stdlib re.
    for (raw, text) in [
        (r"\N", "N"),
        (r"\N{", "N{"),
        (r"\N{BAD_NAME}", "N{BAD_NAME}"),
    ] {
        assert!(
            Pattern::compile(raw, "", Dialect::Regex, &mut || Ok(()))
                .unwrap()
                .is_match(&text.into(), &mut || Ok(()))
                .unwrap()
        );
        assert!(Pattern::compile(raw, "", Dialect::Stdlib, &mut || Ok(())).is_err());
    }
    assert!(Pattern::compile(r"\N{NO SUCH NAME}", "", Dialect::Regex, &mut || Ok(())).is_err());
}
