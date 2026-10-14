# Semble over the frozen 400 public development cases

Frozen before scoring. Same 400 query bytes, roots/commits and original v2
references. No alternative proposals are applied. The private reserve is unused.
The producer receives only id, repository id/commit, root and query, and uses the
unmodified pinned Semble 0.6.2/default Potion artifact. Native alpha/rerank/ignore
policies remain at their defaults; top_k=10 and max_snippet_lines=40.

The external adapter does not search for an answer or improve a snippet. It
keeps native result order, takes only the actual native visible prefix (at most
40 lines), checks it against source, and restores only first-line indentation.
A partial final source statement is omitted; its unseen suffix is never added.
Source hashes are checked against the canonical source index. Inclusive visible
ranges are derived from actual complete lines, not Semble's full chunk end.

Canonical ownership uses the same source-only passage ownership map used in the
matched Ken control. Exactly one owner must contain all substantive displayed
lines in its own regions. Blank separator lines carry no ownership vote. A
cross-owner/ambiguous fragment gets entity=null, never the gold owner. No query,
gold entity, purpose or language participates in this resolution. Generic
fragment references still use their original path+ALL-anchor rule.

The normalized response observes the same 12000 canonical JSON character/10
result/40 visible line budgets. Trimming starts at the last result and preserves
native order and owner identity. Errors, missing responses, invalid source and
abstentions count as misses under the existing strict scorer.

Report strict top1, identity top1, EN/ES/implementation and all 16 repositories.
Also report file top1 and visible ALL-anchor top1 ignoring canonical ownership
as diagnostics, so ambiguous external owner metadata is visible rather than
hidden. Those diagnostics never replace the approved strict metric.

Save native and full raw chunks, normalized responses, producer/model/runtime/
source/scorer/adapter hashes and all 400 planned ids. Timing may coexist with
other CPU index jobs and is not a final performance certificate.
