//! Stress representative generated/deep source in owned subprocesses, without Python.
use ken_syntax::{
    GrammarCatalog, Language,
    structural::{lower_operations, lower_source},
};
use std::{
    path::PathBuf,
    process::{Command, Stdio},
    time::{Duration, Instant},
};
const CHILD: &str = "KEN_FULL_SOURCE_STRESS_CHILD";
fn catalog() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap()
}
fn run_child(name: &str, mode: &str) {
    let temp = tempfile::tempdir().unwrap();
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", name, "--nocapture"])
        .env(CHILD, mode)
        .current_dir(temp.path())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            let stderr = child.wait_with_output().unwrap().stderr;
            assert!(
                status.success(),
                "{mode}: {}",
                String::from_utf8_lossy(&stderr)
            );
            break;
        }
        if start.elapsed() > Duration::from_secs(10) {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("{mode}: source projection exceeded generous10s process budget");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}
#[test]
fn deep_expression_projection_uses_bounded_stack_and_keeps_operands() {
    if std::env::var_os(CHILD).is_none() {
        run_child(
            "deep_expression_projection_uses_bounded_stack_and_keeps_operands",
            "deep",
        );
        return;
    }
    let source = format!("def deep_source(x):\n return {}x\n", "x+".repeat(1500));
    let ir = lower_source(&catalog(), Language::Python, source.as_bytes(), "deep.py").unwrap();
    assert_eq!(
        ir.facts
            .iter()
            .filter(|f| f.relation == "EXPRESSION_OPERAND")
            .count(),
        3000
    );
}
#[test]
fn generated_cpp_fields_have_bounded_projection_work() {
    if std::env::var_os(CHILD).is_none() {
        run_child(
            "generated_cpp_fields_have_bounded_projection_work",
            "fields",
        );
        return;
    }
    let source = format!(
        "struct GeneratedFields{{ {} }};",
        (0..16000)
            .map(|i| format!("int field{i};"))
            .collect::<String>()
    );
    let ir = lower_operations(&catalog(), Language::Cpp, source.as_bytes(), "fields.cpp").unwrap();
    assert_eq!(
        ir.operations
            .iter()
            .filter(|o| o.native_kind == "field_declaration")
            .count(),
        16000
    );
}
#[test]
fn generated_cpp_initializer_inventory_uses_grouped_fact_indexes() {
    if std::env::var_os(CHILD).is_none() {
        run_child(
            "generated_cpp_initializer_inventory_uses_grouped_fact_indexes",
            "initializers",
        );
        return;
    }
    let source = format!(
        "struct GeneratedInitializers{{int value;{} }};",
        (0..4500)
            .map(|i| format!("GeneratedInitializers(int x{i}):value(x{i}){{}}"))
            .collect::<String>()
    );
    let ir = lower_source(
        &catalog(),
        Language::Cpp,
        source.as_bytes(),
        "initializers.cpp",
    )
    .unwrap();
    assert_eq!(
        ir.facts
            .iter()
            .filter(|f| f.relation == "CONSTRUCTOR_INITIALIZER_STATUS")
            .count(),
        4500
    );
}
