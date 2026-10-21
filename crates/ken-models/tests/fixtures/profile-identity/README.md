# Original profile identity fixtures

Each JSON was produced by tools/rust_migration/integration_reference.py, loading src/ken/retrieval/profile.py from the frozen reference-final-t9 tree. The original source SHA and capture-tool SHA are recorded in each file. The original was unchanged before/after each capture.

macos.json and linux.json observe the actual current test environments, including literal unavailable package values; macos-torch.json and macos-mlx.json observe the separately pinned neural oracle environments. They intentionally differ. These declare compatible hash inputs, not installed native runtime libraries or inference accreditation. Model revisions in these identity-only cases are explicit synthetic40/64hex values; no weights are requested or loaded. Actual registered asset selection belongs to the factory gate.

Every file includes6 encoder configurations,10 profiles,6 rejected encoders,14 rejected nested profiles, and an explicit representation2 upgrade. Profiles include absent optional keys, separate source views, Unicode including an astral character, and ordered package lists. Captured digests and sorted Python JSON are literal expected values; Rust does not recompute the expected side of the comparison.
