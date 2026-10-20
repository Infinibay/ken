use ken_models::{FastEmbedModel, FastEmbedTokens};
use serde_json::json;

fn model(pooling: &str, dimension: usize) -> FastEmbedModel {
    let record = json!({"bytes":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"});
    FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/pooling",
        "assets":{"model_id":"test/pooling","revision":"1111111111111111111111111111111111111111","artifacts":{
            "model.onnx":record,"config.json":record,"tokenizer.json":record,
            "tokenizer_config.json":record,"special_tokens_map.json":record}},
        "graph":"model.onnx","dimension":dimension,"pooling":pooling,"task_id":null,"advisories":[]}).to_string()).unwrap()
}

fn tokens(batch: usize, sequence: usize, mask: &[i64]) -> FastEmbedTokens {
    FastEmbedTokens {
        shape: [batch, sequence],
        ids: vec![0; batch * sequence],
        attention_mask: mask.into(),
    }
}

#[test]
fn cls_sentence_and_raw_preserve_their_distinct_recipes() {
    let input = tokens(1, 2, &[1, 1]);
    let cls = model("cls_or_sentence_l2", 2);
    assert_eq!(
        cls.pool(&[3., 4., 100., 100.], &[1, 2, 2], &input).unwrap(),
        vec![vec![0.6, 0.8]]
    );
    assert_eq!(
        cls.pool(&[3., 4.], &[1, 2], &input).unwrap(),
        vec![vec![0.6, 0.8]]
    );
    assert_eq!(
        model("raw", 2).pool(&[3., 4.], &[1, 2], &input).unwrap(),
        vec![vec![3., 4.]]
    );
}

#[test]
fn masked_mean_promotes_before_accumulation_and_casts_only_at_the_end() {
    let input = tokens(1, 3, &[1, 1, 1]);
    assert_eq!(
        model("mean", 1)
            .pool(&[1e10, 1., -1e10], &[1, 3, 1], &input)
            .unwrap(),
        vec![vec![1.0_f32 / 3.0]]
    );
    let masked = tokens(1, 3, &[1, 0, 1]);
    assert_eq!(
        model("mean", 2)
            .pool(&[1., 3., 99., 99., 3., 5.], &[1, 3, 2], &masked)
            .unwrap(),
        vec![vec![2., 4.]]
    );
    let zero = tokens(1, 3, &[0, 0, 0]);
    assert_eq!(
        model("mean_l2", 2)
            .pool(&[1.; 6], &[1, 3, 2], &zero)
            .unwrap(),
        vec![vec![0., 0.]]
    );
    assert_eq!(
        model("mean_l2", 1)
            .pool(&[1e10, 1., -1e10], &[1, 3, 1], &input)
            .unwrap(),
        vec![vec![1.]]
    );
}

#[test]
fn normalized_mean_matches_frozen_original_final_cast_bits() {
    // Original FastEmbed0.8.0 mean_pooling + normalize, NumPy2.4.4;
    // casting the mean to F32 early changes the last two output components.
    let input = [
        1074976142, 1059643487, 1059287095, 3200899132, 3202574503, 3221800815, 3219705437,
        1068471701, 3188325342, 3206356528, 1064556899, 3210317925,
    ]
    .map(f32::from_bits);
    let result = model("mean_l2", 4)
        .pool(&input, &[1, 3, 4], &tokens(1, 3, &[1, 1, 1]))
        .unwrap();
    assert_eq!(
        result[0]
            .iter()
            .map(|value| value.to_bits())
            .collect::<Vec<_>>(),
        vec![1059166909, 3208971180, 3182147032, 1027633033]
    );
}

#[test]
fn invalid_shapes_nonfinite_data_and_overflowed_norms_cannot_become_zero_vectors() {
    let input = tokens(1, 1, &[1]);
    let cls = model("cls_or_sentence_l2", 2);
    for (values, shape) in [
        (vec![f32::NAN, 1.], vec![1, 2]),
        (vec![f32::INFINITY, 1.], vec![1, 2]),
        (vec![1e38, 1e38], vec![1, 2]),
        (vec![1., 2., 3., 4.], vec![2, 2]),
        (vec![1.], vec![1, 1]),
        (vec![1., 2.], vec![usize::MAX, 2]),
        (vec![1., 2.], vec![1, 1, 1, 2]),
    ] {
        assert!(cls.pool(&values, &shape, &input).is_err());
    }
    assert!(model("mean", 2).pool(&[1., 2.], &[1, 2], &input).is_err());
    assert!(model("raw", 2).pool(&[1., 2.], &[1, 1, 2], &input).is_err());
    let invalid = tokens(1, 1, &[-1]);
    assert!(
        model("mean", 2)
            .pool(&[1., 2.], &[1, 1, 2], &invalid)
            .is_err()
    );
}
