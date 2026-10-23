These are byte-for-byte copies of the original registered Ken forests from
src/ken/retrieval/data/. They retain the repository MIT license. No model was
retrained or selected during migration. original-registry.json preserves the
original development provenance; those historical metrics are not a new native
quality measurement.

manifest.json pins compressed bytes, decoded bytes, canonical model identity,
feature count and tree count. ProductionRankModels checks this compiled registry
before opening either model lazily, then verifies each artifact before use.
The native model is the fixed mean of 16 forests (2560 trees, 251 features);
the piece model is the fixed mean of eight forests (1280 trees, 262 features).
The latter's caller and feature projection remain part of M4c2.
