pub mod feature_support;
use feature_support as f;
use ken_retrieval::coverage::coverage;
use serde_json::Value;
#[test]
fn complete_original_coverage_and_block_call_observations() {
    for case in f::cases().into_iter().filter(|c| c.kind == "coverage") {
        let encoder = f::Encoder::new(&case.input);
        let stems = f::Stems::new(&case.input);
        let fields: Vec<_> = case.input.fields.iter().map(String::as_str).collect();
        let got = coverage(
            case.input.query.as_ref().unwrap(),
            &case.input.documents,
            &fields,
            &encoder,
            case.input
                .stemmer
                .as_ref()
                .map(|_| &stems as &dyn ken_retrieval::stemming::WordStemmer),
        );
        if let Some(expected) = &case.error {
            let error =
                got.expect_err("nonfinite active field maxima must not become finite evidence");
            f::error(error, expected, &case.id);
            f::check_calls(&case, &encoder, &stems);
            continue;
        }
        let got = got.unwrap();
        let want: Vec<std::collections::BTreeMap<String, Value>> =
            serde_json::from_str(case.result.as_ref().unwrap().get()).unwrap();
        assert_eq!(got.len(), want.len(), "{}", case.id);
        for (a, b) in got.iter().zip(&want) {
            assert_eq!(
                a.keys().collect::<Vec<_>>(),
                b.keys().collect::<Vec<_>>(),
                "{}",
                case.id
            );
            for (k, v) in a {
                f::close(*v, f::number(&b[k]), &format!("{}/{k}", case.id));
            }
        }
        f::check_calls(&case, &encoder, &stems);
    }
}
