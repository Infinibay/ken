#[path = "support/responsibility_profile.rs"]
mod profiles;
#[path = "support/navigation.rs"]
#[allow(dead_code)]
mod support;
use ken_core::tool_output::render;
use ken_search::navigation::IndexNavigation;
use rusqlite::Connection;
use serde_json::Value;

#[test]
fn original_file_directory_and_public_profiles_match_without_writes_or_models() {
    let fixture = profiles::fixture();
    let hash = fixture.database_hash();
    let reference = profiles::reference();
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    for row in reference["rows"].as_array().unwrap() {
        let args = &row["args"];
        let profile = nav
            .profile(
                args["path"].as_str().unwrap(),
                args["granularity"].as_str().unwrap(),
                args["top_terms"].as_i64().unwrap(),
            )
            .unwrap();
        let mut expected = row["result"].clone();
        if args["granularity"] == "dir" && args["path"] == "src" {
            // Python observed explanation/client in hash-set order. Each has
            // target19/rest0: EXACT scores tie, not merely their rounded values.
            // Only this proven pair may change order; keep the fixture intact.
            for term in ["client", "explanation"] {
                let mut selected = 0;
                let mut rest = 0;
                for file in reference["input"]["files"].as_array().unwrap() {
                    let count = [
                        file["text"].as_str().unwrap(),
                        file["intent"].as_str().unwrap_or(""),
                    ]
                    .into_iter()
                    .flat_map(str::split_whitespace)
                    .filter(|word| *word == term)
                    .count();
                    if file["path"].as_str().unwrap().starts_with("src/") {
                        selected += count;
                    } else {
                        rest += count;
                    }
                }
                assert_eq!((selected, rest), (19, 0));
            }
            let terms = expected["distinguishing_terms"].as_array_mut().unwrap();
            assert_eq!(terms[2]["term"], "explanation");
            assert_eq!(terms[3]["term"], "client");
            assert_eq!(terms[2]["z"], terms[3]["z"]);
            terms.swap(2, 3);
        }
        assert_eq!(serde_json::to_value(profile).unwrap(), expected, "{args}");
    }
    for row in reference["public"].as_array().unwrap() {
        let profile = nav
            .read(&serde_json::from_value(row["args"].clone()).unwrap())
            .unwrap();
        assert_eq!(
            serde_json::to_value(&profile).unwrap(),
            row["result"],
            "{}",
            row["args"]
        );
        assert_eq!(
            render(&profile, "ken_read", false),
            row["compact"].as_str().unwrap()
        );
    }
    assert_eq!(fixture.database_hash(), hash);
    assert_eq!(
        nav.profile("lib/unicode.py", "file", 99)
            .unwrap()
            .get("term_count")
            .integer(),
        Some(82)
    );
    drop(nav);
    // An exact z tie has deterministic lexical order. Tokenization leaves an
    // acronym intact, splits after digits/lowercase, and drops ASCII stop words.
    let conn = Connection::open(fixture.paths.db()).unwrap();
    conn.execute(
        "UPDATE ci_symbols SET docstring='zebra apple' WHERE file_id=1",
        [],
    )
    .unwrap();
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    let profile: Value =
        serde_json::to_value(nav.profile("src/alpha.py", "file", 12).unwrap()).unwrap();
    let terms = profile["distinguishing_terms"].as_array().unwrap();
    assert_eq!(terms.len(), 2);
    assert_eq!(terms[0]["term"], "apple");
    assert_eq!(terms[1]["term"], "zebra");
    assert_eq!(terms[0]["z"], terms[1]["z"]);
}
