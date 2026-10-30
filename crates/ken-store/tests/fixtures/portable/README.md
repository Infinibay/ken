# Portable storage test inputs

`storage-cases.json` is the exact existing32-case original input document from `docs/validation/rust-migration-2026-10-19/m2-storage/cases.json`, SHA256 `db8806ae8311641a017abf017ddd60f9f9c6fc6b6a5ce56a85084a201ca07f0b` (7475bytes).

`storage-schemas.json` contains precisely the two schema values previously consumed by database.rs: the first original oracle's `schema-fresh` and `schema-legacy` result output.schema, keyed by case ID. Every schema object/index/column/foreign key value is unchanged; unrelated histories and receipt metadata from the3.6MB archival reference are omitted. `PROVENANCE.json` pins the source and projection SHA256/size.

These are portable test/example inputs, not new acceptance evidence. No original, model or global suite was replayed; source originals remain unchanged.
