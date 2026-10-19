use ken_models::{QueryExpansionPlan, plan_query};
use serde_json::Value;

fn original() -> Value {
    serde_json::from_str(include_str!("fixtures/translation/policy.json")).unwrap()
}

#[test]
fn every_original_lexicon_member_counts_once_and_casefolds_before_the_decision() {
    let oracle = original();
    for value in oracle["lexicon"].as_array().unwrap() {
        let word = value.as_str().unwrap();
        let anchor = if word == "busca" { "clase" } else { "busca" };
        assert!(
            matches!(
                plan_query(&format!("{word} {word}")).unwrap(),
                QueryExpansionPlan::Passthrough(_)
            ),
            "{word}"
        );
        assert!(
            matches!(
                plan_query(&format!("{} {anchor}", word.to_uppercase())).unwrap(),
                QueryExpansionPlan::Translate(_)
            ),
            "{word}"
        );
    }
    for other in ["archivoes", "devolver", "los_", "creas", "no-spanish-match"] {
        assert!(matches!(
            plan_query(&format!("busca {other}")).unwrap(),
            QueryExpansionPlan::Passthrough(_)
        ));
    }
}

#[test]
fn original_query_decisions_and_exact_matches_survive_unicode_and_regex_boundaries() {
    let oracle = original();
    for row in oracle["cases"].as_array().unwrap() {
        let query = row["query"].as_str().unwrap();
        match plan_query(query).unwrap() {
            QueryExpansionPlan::Passthrough(text) => {
                assert_eq!(row["needs_translation"], false, "{query:?}");
                assert_eq!(text, query);
            }
            QueryExpansionPlan::Translate(prepared) => {
                assert_eq!(row["needs_translation"], true, "{query:?}");
                assert_eq!(
                    prepared.text(),
                    row["prepared"].as_str().unwrap(),
                    "{query:?}"
                );
                assert_eq!(
                    serde_json::to_value(prepared.protected_values()).unwrap(),
                    row["protected"],
                    "{query:?}"
                );
            }
        }
    }
}

#[test]
fn restoration_preserves_original_whitespace_case_collisions_and_literal_replacements() {
    let oracle = original();
    for row in oracle["restoration"].as_array().unwrap() {
        let QueryExpansionPlan::Translate(query) =
            plan_query(row["query"].as_str().unwrap()).unwrap()
        else {
            panic!("expected translated fixture: {}", row["id"]);
        };
        let result = query.restore(row["decoded"].as_str().unwrap());
        if let Some(expected) = row["output"].as_str() {
            assert_eq!(result.unwrap(), expected, "{}", row["id"]);
        } else {
            assert!(result.is_err(), "{}", row["id"]);
        }
    }
}

#[test]
fn query_plans_are_independent_and_restoration_is_sequential_without_trimming_output() {
    let QueryExpansionPlan::Translate(first) = plan_query("¿ `ZXQ1QXZ` y foo_bar").unwrap() else {
        panic!()
    };
    let QueryExpansionPlan::Translate(other) = plan_query("¿ `other.value`").unwrap() else {
        panic!()
    };
    assert_eq!(other.restore("ZXQ0QXZ").unwrap(), "`other.value`");
    assert_eq!(first.restore(" ZXQ0QXZ  ").unwrap(), " `foo_bar`  ");
    assert_eq!(first.restore("\u{200b}").unwrap(), "\u{200b}");
    assert!(
        first
            .restore("\u{1c}\u{1d}\u{1e}\u{1f}\u{85}\u{a0}")
            .is_err()
    );
    assert!(first.restore("").is_err());
}

#[test]
fn long_failed_identifier_matches_preserve_original_text_without_panicking() {
    // The original Python matcher finds no identifier in these histories.
    // A trailing word character disallows ending before the accented letter.
    for count in [5_000, 20_000] {
        let query = format!("¿ {}é", "_".repeat(count));
        let QueryExpansionPlan::Translate(plan) = plan_query(&query).unwrap() else {
            panic!("question must select translation");
        };
        assert_eq!(plan.text(), query);
        assert!(plan.protected_values().is_empty());
    }
    for (query, expected) in [
        ("¿ a$_$", Vec::<String>::new()),
        ("¿ __", vec![]),
        ("¿ a__", vec!["a__".into()]),
        ("¿ __a_١", vec!["__a_١".into()]),
    ] {
        let QueryExpansionPlan::Translate(plan) = plan_query(query).unwrap() else {
            panic!("question must select translation");
        };
        assert_eq!(plan.protected_values(), expected);
    }
}
