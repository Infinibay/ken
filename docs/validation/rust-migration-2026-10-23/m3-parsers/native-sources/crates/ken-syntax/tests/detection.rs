//! The exact extension table and syntax evidence for ambiguous C-family headers.
use ken_syntax::{GrammarCatalog, Language, ParserRegistry};
use std::path::{Path, PathBuf};

fn parsers() -> ParserRegistry {
    let manifest = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    ParserRegistry::new(GrammarCatalog::prepared(&manifest).unwrap())
}
#[test]
fn all_original_extensions_and_unknown_names_are_preserved() {
    let parsers = parsers();
    let mut count = 0;
    for (language, extensions) in [
        (Language::C, vec!["c", "h"]),
        (
            Language::Cpp,
            vec!["cpp", "cc", "cxx", "hpp", "hh", "hxx", "ipp"],
        ),
        (Language::CSharp, vec!["cs", "csx"]),
        (Language::Css, vec!["css"]),
        (Language::Html, vec!["html", "htm", "vue", "svelte"]),
        (Language::Python, vec!["py", "pyi"]),
        (Language::Rust, vec!["rs"]),
        (Language::Ruby, vec!["rb", "rake", "gemspec"]),
        (Language::JavaScript, vec!["js", "jsx", "mjs", "cjs"]),
        (Language::TypeScript, vec!["ts", "tsx"]),
        (Language::Go, vec!["go"]),
        (Language::Java, vec!["java"]),
        (Language::Kotlin, vec!["kt", "kts"]),
        (Language::Dart, vec!["dart"]),
        (Language::Php, vec!["php", "phtml"]),
        (Language::Sql, vec!["sql"]),
        (Language::GraphQL, vec!["graphql", "gql"]),
        (Language::Bash, vec!["sh", "bash", "ksh"]),
        (Language::PowerShell, vec!["ps1", "psm1", "psd1"]),
    ] {
        for extension in extensions {
            assert_eq!(
                parsers
                    .detect(Path::new(&format!("file.{extension}")), None)
                    .unwrap(),
                Some(language)
            );
            assert_eq!(
                parsers
                    .detect(
                        Path::new(&format!("file.{}", extension.to_uppercase())),
                        None
                    )
                    .unwrap(),
                Some(language)
            );
            count += 1;
        }
    }
    assert_eq!(count, 44);
    for path in ["Rakefile", ".py", "file.unknown", "file", "file."] {
        assert_eq!(parsers.detect(Path::new(path), None).unwrap(), None);
    }
}
#[test]
fn header_detection_uses_structural_evidence_and_ignores_literal_words() {
    let parsers = parsers();
    for source in [
        "namespace sample { int read() { return 1; } }",
        "class Reader { public: int read() { return 1; } };",
        "template<class T> T read(T value) { return value; }",
        "using Value = unsigned long;",
        "int& read();",
    ] {
        assert_eq!(
            parsers
                .detect(Path::new("api.h"), Some(source.as_bytes()))
                .unwrap(),
            Some(Language::Cpp)
        );
    }
    for source in [
        "#ifndef HEADER\n#define HEADER\nstruct Reader { int size; };\nint read(void);\n#endif\n",
        "/* namespace sample { class Reader {}; } */\nconst char *label = \"template<class T>\";\nint read(void);",
        "int class = 0; int namespace = 1; int template = 2;",
    ] {
        assert_eq!(
            parsers
                .detect(Path::new("api.h"), Some(source.as_bytes()))
                .unwrap(),
            Some(Language::C)
        );
    }
    assert_eq!(
        parsers
            .detect(Path::new("api.c"), Some(b"namespace fake {}"))
            .unwrap(),
        Some(Language::C)
    );
    assert_eq!(
        parsers
            .detect(Path::new("api.hpp"), Some(b"int read(void);"))
            .unwrap(),
        Some(Language::Cpp)
    );
}

#[test]
fn missing_optional_cpp_grammar_keeps_header_fallback_and_direct_errors() {
    let original = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let temp = tempfile::tempdir().unwrap();
    let manifest = temp.path().join("manifest.json");
    std::fs::copy(original, &manifest).unwrap();
    let parsers = ParserRegistry::new(GrammarCatalog::prepared(&manifest).unwrap());
    assert_eq!(
        parsers
            .detect(Path::new("api.h"), Some(b"class Reader {};"))
            .unwrap(),
        Some(Language::C)
    );
    assert!(
        parsers
            .parse(Language::Cpp, b"class Reader {};", "api.cpp")
            .unwrap_err()
            .to_string()
            .contains("cpp")
    );
    assert!(
        parsers
            .parse(Language::Python, b"def read(): pass", "api.py")
            .is_ok()
    );
}
