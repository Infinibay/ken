#!/bin/sh
set -eu
system="$1"
ws="$2"
wrapped="$3"
"$wrapped" cargo test --locked --offline -p ken-core -- --list > "$ws/review-list-$system.log" 2>&1
"$wrapped" cargo test --locked --offline -p ken-core > "$ws/review-core-$system.log" 2>&1
"$wrapped" cargo clippy --locked --offline -p ken-core --all-targets -- -D warnings > "$ws/review-clippy-$system.log" 2>&1
"$wrapped" cargo build --locked --offline --release -p ken-core --example source_probe > "$ws/review-build-$system.log" 2>&1
"$wrapped" cargo fmt --all -- --check > "$ws/review-fmt-$system.log" 2>&1
"$wrapped" .venv/bin/python -m pytest -o addopts= tests/rust_migration/test_source_reference.py tests/rust_migration/test_source_validate.py tests/rust_migration/test_source_evidence.py --junitxml="$ws/review-python-$system.xml" > "$ws/review-python-$system.log" 2>&1
