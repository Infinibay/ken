# Evidence selection within a fixed owner ranking v60

Keep the valid235-feature owner ranking38/42 fixed. Previous40 trained one
query-level list containing every owner/window; this does not isolate the
responsibility of selecting evidence inside an already chosen function.

Use the existing source-only34b naturally generated/rendered hypotheses and
40c window features/strict labels, whose full source and label fidelity were
independently audited. No new hypotheses from references, anchor centering,
criteria changes, extra encoder, external inference, GPU or private acceptance.
This is a source5 prepared paired control, not the source6 rebuild58 or an API.

Fit ONLY the43 window-specific columns235:278, discarding all owner-level
features. Each training group is (query,canonical owner), never the whole query.
Training groups without any strictly positive window contribute no ordering
information; remove only those groups from fitting, along with the original
nonrenderable window. No query/owner is removed from inference or final scoring.
Use the same fixed160-tree parameters and16 whole-repository-excluded folds;
native/export scores must match exactly. No fitting on other outer-fold scores.

At inference, choose the highest-scoring naturally renderable hypothesis for
each owner available in that pre-existing public window pool. Join by complete
canonical entity AND source hash, never by owner index across proposal pools.
Keep every owner score/order unchanged. If no proposed window exists, retain
the original retrieved evidence. Preserve deterministic exact authority.
Pass ALL scored owners through the actual presenter and original budgets.

First reconstruct the original fixed owner ranking and require277/400 strict
and290/400 identity with the unchanged scorer. Then evaluate ALL400 original
strict ALL-anchor references, every stratum and failure, including owners with
no strictly satisfactory hypothesis. Report changes in final owner identity;
although order is fixed, output pruning can still affect visible identity.

This can resolve only evidence-selection losses; it cannot establish90% or
improve the110 primary owner-ordering failures by itself. Any prepared benefit
requires an independently reviewed real source-only feature/presentation path,
actual API/CLI/MCP, CPU/RAM and untouched private acceptance before promotion.
