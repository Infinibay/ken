use ken_models::ModelTokenizer;
use serde_json::Value;

#[test]
fn matches_reference_tokens() {
    let tokenizer = ModelTokenizer::load(include_bytes!("fixtures/potion-tokenizer.json")).unwrap();
    let oracle: Value = serde_json::from_str(include_str!(
        "../../../docs/validation/rust-migration-2026-10-18/m2-static/potion-reference.json"
    ))
    .unwrap();
    for (case, result) in oracle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .zip(oracle["results"].as_array().unwrap())
    {
        for (call, expected) in case["calls"]
            .as_array()
            .unwrap()
            .iter()
            .zip(result["calls"].as_array().unwrap())
        {
            if call["op"] == "tokens" {
                let limit = call["max_length"].as_u64().map(|x| x as usize);
                let actual = tokenizer
                    .token_ids(call["text"].as_str().unwrap(), limit)
                    .unwrap();
                assert_eq!(
                    serde_json::to_value(actual).unwrap(),
                    *expected,
                    "{}",
                    case["id"]
                );
            }
        }
    }
}

#[test]
fn bounded_encode_preserves_character_prefix_and_unknown_policy() {
    let tokenizer = ModelTokenizer::load(include_bytes!("fixtures/policy-tokenizer.json")).unwrap();
    assert_eq!(
        tokenizer.token_ids("x a b", Some(2)).unwrap(),
        Vec::<u32>::new()
    );
    assert_eq!(tokenizer.token_ids("x a b", None).unwrap(), [3, 4]);
    assert_eq!(tokenizer.token_ids("[PAD]", None).unwrap(), [1]);
    assert_eq!(
        tokenizer.token_ids("a b", Some(0)).unwrap(),
        Vec::<u32>::new()
    );
}

#[test]
fn count_has_no_hidden_limit() {
    let tokenizer = ModelTokenizer::load(include_bytes!("fixtures/policy-tokenizer.json")).unwrap();
    assert_eq!(tokenizer.token_count(&"a ".repeat(900)).unwrap(), 900);
    assert_eq!(tokenizer.token_ids("a b", None).unwrap(), [3, 4]);
}

#[test]
fn unicode_length_is_not_utf8_bytes() {
    let tokenizer = ModelTokenizer::load(include_bytes!("fixtures/policy-tokenizer.json")).unwrap();
    assert_eq!(tokenizer.token_ids("é a", Some(3)).unwrap(), [2, 3]);
}

#[test]
fn corrupt_or_sparse_vocabulary_is_rejected() {
    assert!(ModelTokenizer::load(b"{}").is_err());
    let mut sparse: Value =
        serde_json::from_slice(include_bytes!("fixtures/policy-tokenizer.json")).unwrap();
    sparse["model"]["vocab"]["a"] = 99.into();
    assert!(ModelTokenizer::load(&serde_json::to_vec(&sparse).unwrap()).is_err());
}
