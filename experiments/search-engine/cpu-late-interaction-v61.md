# Compact contextual token interaction v61

The valid235-feature ranking compresses each source owner to one contextual
vector, then uses context-free Potion word matches for finer coverage. Test
whether contextual token matching supplies information lost by that compression.
This is a hypothesis, not a90% claim or a pretrained ColBERT implementation.

References: [ColBERT](https://arxiv.org/abs/2004.12832) defines per-query-token
maximum source similarity and an independently encoded source index;
[PLAID](https://arxiv.org/abs/2205.09707) addresses CPU serving and compression.
Their trained projections, query augmentation and published results are NOT
transferred to CodeRank's untrained token projection or to this code benchmark.

Use ALL16 complete source6 indices58 before reading public queries, every owner,
same physical source hashes and canonical ownership. The EXISTING137M int8 graph
already exposes token_embeddings and sentence_embedding. Encode the exact58
path/identity/signature/doc800/owned-body prefix512 text on CPU2threads/batch1.
Require normalized sentence output to equal the existing58 full-source vector
for EVERY text. No new/larger model, learned token weights, GPU, generated prose,
remote inference, changes to source visibility or private acceptance access.

Select non-special tokens whose original text contains a letter/digit/underscore
or code operator. Store both an all-content mask and actual owned-implementation
mask using tokenizer offsets and the verified projection prefix. Metadata remains
ranking input, never displayed implementation evidence. Preserve512 truncation;
do not claim coverage beyond what the model actually encoded.

Use a fixed Rademacher768x128 projection with seed61, L2 normalize each token,
round127 to int8. Same projection for source and query. Record matrix and helper
hashes; no fitting on queries/references. Persist source token IDs, owner/source
mapping, offsets/masks, all-source document frequencies and compact vectors on
disk. Stream or memory-map the index; bound per-owner scoring memory. Record
actual bytes and reconstruction error; quantization is approximate, not exact.

After all16 source indices complete, encode each original/expanded query ONCE,
same registered query prefix and tokenizer; remove prefix/special tokens by
offset, retaining every query content token within the actual512 prefix. Compute
per-query-token maximum cosine to each candidate's all/implementation token bag.
Six summaries: mean,min,p25,source-DF-weighted mean,fraction>=.5,fraction>=.7.
Add pool-relative mean difference-to-max and reciprocal rank per query/view:
32 extra columns,267 total, keeping58's235 values and candidates fixed.

One fixed267-column model, unchanged160tree parameters and16 whole-repo-excluded
folds. Source58 original eligible_owner labels joined only in the separate
evaluator. Native/export exact, original400 strict ALL-anchor references and
strata, original40lines/10results/12kJSON/error behavior. No gold-based window
selection or candidate filtering. Paired235 source6 baseline58, then real API,
CPU/RAM/public Semble/CLI/MCP and blind acceptance if useful; no promotion from
prepared-only improvement. Continue counting all no-positive and failed queries.
