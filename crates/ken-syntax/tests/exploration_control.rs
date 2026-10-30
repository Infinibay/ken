//! A single large raw parse must cooperate, not just poll before and after it.
use ken_syntax::{GrammarCatalog, Language, ParseError};
use std::path::PathBuf;
#[test]
fn raw_syntax_parse_polls_control_during_one_large_admitted_unit() {
    let catalog = GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap();
    let source = "if condition:\n    value = target(argument)\n".repeat(30000);
    let mut checkpoints = 0;
    let result =
        catalog.syntax_checked(Language::Python, source.as_bytes(), "large.py", &mut || {
            checkpoints += 1;
            if checkpoints >= 3 {
                Err(ParseError::Parse {
                    language: "python".into(),
                    reason: "controlled cancellation".into(),
                })
            } else {
                Ok(())
            }
        });
    assert!(
        matches!(result,Err(ParseError::Parse{reason,..}) if reason=="controlled cancellation")
    );
    assert!(checkpoints >= 3);
    assert!(
        catalog
            .syntax(Language::Python, b"if x: pass\n", "small.py")
            .is_ok()
    );
}
