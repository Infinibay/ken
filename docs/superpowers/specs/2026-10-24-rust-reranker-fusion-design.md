# Native ordinal reranker fusion — bounded M4d foundation

Continue the approved Rust migration after the accepted x86grammar prerequisite.
The next PieceSearch caller needs to combine its existing candidate order with
neural ordinal evidence without changing membership. This slice ports that one
policy; source operations,symbol second views,PieceSearch,prepared pools and public
CLI/MCP remain subsequent M4d work. No complete M4d/M4/global acceptance is implied.

The executor chooses a standalone `reranker_fusion` function in ken-retrieval.
Reusing `fuse_proposals` would conflate named-channel owner aggregation with a
fixed candidate permutation; reimplementing neural inference would duplicate
accepted ken-models. A focused ordinal function is directly reusable by the
future PieceSearch coordinator and has no model/resource dependency.

Representative caller:
`let order = fused_reranker_order(&scores, 0.5, 60.0)?;`
Its indices address the original pool. Validate weight finite/in[0,1],then offset
finite/nonnegative,then every score finite,including on empty input. Preserve
Python error messages and validation precedence. Rank neural scores descending
with original index as tie breaker;combine one-based reciprocal ranks with
`(1-weight)/(offset+i+1) + weight/(offset+neural_rank)`;sort descending,then index.
Preserve IEEE operation order,negative zero,extreme finite values and stable ties.
Do not add truncation,top10 caps,normalization or candidates to this helper.

Before native implementation,capture the frozen Python function's observations
and its exact12-root original suite once. Save input/output/errors,observer,
request,stdout/stderr,JUnit,source/runtime identities locally. Commit only a
consumed regression fixture. The typed Rust API accepts f64;arbitrary Python
objects and coercion are outside its type boundary,not silently certified.
No new crate/dependency/version. Rust1.95.0,Python3.12.9/Unicode15 remain pinned.
No accepted originals,old receipts,thresholds or installed commands change.

Verification: actual public-use Rust differential tests,complete core/retrieval
suites,fmt,strict Clippy,and both native ARM integration jobs. Existing full-suite
root inventories must increase only by the actually discovered new test roots;
historical archives keep their frozen validators. Use one final fresh read-only
review and one repair pass if needed;no implementation agents or stage questions.
Preserve all generated evidence locally and push to the already authorized branch.
