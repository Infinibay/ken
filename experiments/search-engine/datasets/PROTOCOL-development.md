# Development corpus provenance

This corpus is development data and has been exposed to the retrieval implementer. It must not be described as independent acceptance evidence. Its 400 positives come from 16 pinned public repositories, separate from the sealed reserve. Each repository contributes 25 cases: 20 implementation, three identity, and two tests; 15 English and 10 Spanish.

A curator separate from the engine implementer wrote behavioral questions after reading source bodies and tests. No engine runs, rankings, candidate pools, or engine outputs were used to choose or adjust judgments. Exact-name requests belong to the identity stratum. The source parsers alone supplied canonical identities and definition ordinals. When a parser does not expose an applicable JavaScript or TypeScript declaration, identity is null and source anchors determine correctness.

Source anchors are one-based and inclusive. Every anchor of one alternative is required. All positive alternatives have at most 33 anchor lines, within the agreed 40-line result budget. Commits, source byte hashes, line bounds, schema, unique IDs and query strings, repository counts, language counts, and purpose counts were validated before the final receipt. The files named by freeze-development.json retain the snapshot hashes for reproducibility.

review-development.jsonl records the per-case source review and anchor-content digest. manifest-development.json records pinned commits and source sizes. source-snapshots-development.jsonl records hashes of tracked repository files. These are provenance records, not a claim that project test suites were executed or that a second human independently audited every label.

Behavioral duplicates and translations were kept within their repository and split. Development may support error analysis and engine changes. The separate sealed reserve must remain hidden and untouched until a frozen engine, scorer, profile, and model receipt is supplied for the gate. No acceptance result has been produced by this curation work.
