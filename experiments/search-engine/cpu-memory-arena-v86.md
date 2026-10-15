# CPU allocator control86: preserve all encoder values

Research only; no weight/graph/tokenization/normalization/source/query/ranking
change. Keep the exact frozen85b CodeRank42 int8 graph, CPU provider, two intra
and one inter thread, batch1 and prefix512 without padding. Compare the default
CPU memory arena with enable_cpu_mem_arena=False in four fresh sequential
processes, order default/off/off/default. All other SessionOptions stay equal.
Official API documents this option and its default:
https://onnxruntime.ai/docs/api/python/api_summary.html#onnxruntime.SessionOptions.enable_cpu_mem_arena

Before inference register every input hash and deterministic sample identities.
Recode ALL545 unique original/expanded query texts from the bound800 views of
400 public requests and compare normalized vectors byte for byte with31/64.
Also recode two source69 implementation texts per each of16 source repos, one
shortest and one longest by character count with vector_index tie, using exactly
the saved source text and expected source vector. This is source-only sampling;
no labels, references, eligibility, queries selecting source or private reserve.
Run the32 source probes before queries so long512 inputs precede short queries.

Require raw and normalized arrays, token IDs/masks, shapes and per-input hashes
identical across all four processes, in addition to every expected unit vector.
Any difference rejects numerical equivalence; do not transfer prior quality.
Record peak native ru_maxrss and wall time at imports/session/source/query phases,
per-input inference latency, CPU provider/runtime versions and heavy-import check.
The measured encoder working set omits retrieval/translation/presentation and
coexists with other research jobs: it is not final API memory/latency certification.
No integration/profile/default change without independently reviewed value parity
and actual ALL400 API checks of the proposed policy. Do not claim top1 improvement.
