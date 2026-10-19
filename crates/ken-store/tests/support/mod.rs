use serde_json::Value;
use std::{
    io::{BufRead, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

pub fn original_python(script: &str, root: &Path) -> std::process::Child {
    let reference =
        PathBuf::from(std::env::var_os("KEN_RUST_REFERENCE").expect("prepared frozen reference"));
    let manifest: Value =
        serde_json::from_slice(&std::fs::read(reference.join("reference-manifest.json")).unwrap())
            .unwrap();
    let mut command = Command::new(manifest["python"].as_str().unwrap());
    command
        .args(["-u", "-c", script])
        .arg(root)
        .arg(&reference)
        .env(
            "PYTHONPATH",
            std::env::join_paths([reference.join("src"), reference.clone()]).unwrap(),
        )
        .env("PYTHONNOUSERSITE", "1")
        .current_dir(root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    command.spawn().unwrap()
}

pub fn event(reader: &mut impl BufRead) -> Value {
    loop {
        let mut line = String::new();
        assert!(
            reader.read_line(&mut line).unwrap() > 0,
            "child ended before event"
        );
        if let Some((_, payload)) = line.split_once("vector-event:") {
            return serde_json::from_str(payload.trim()).unwrap();
        }
    }
}

pub fn signal(writer: &mut impl Write, value: &str) {
    writeln!(writer, "{value}").unwrap();
    writer.flush().unwrap();
}

pub const ORIGINAL_IMPORTS: &str = r#"
import json, sys
from pathlib import Path
import numpy as np
import ken.vectors as vectors
root, reference = map(Path, sys.argv[1:])
assert Path(vectors.__file__).resolve() == (reference / 'src/ken/vectors.py').resolve()
def event(value):
    print('vector-event:' + json.dumps(value), flush=True)
"#;
