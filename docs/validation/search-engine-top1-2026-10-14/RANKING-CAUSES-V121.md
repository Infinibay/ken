# Ranking findings and current acceptance priority — 2026-10-15

The user explicitly clarified that the primary target is >=90% correct requested
piece at top1, whether or not the returned excerpt is sufficient to independently
verify the behavior. Joint visible-evidence sufficiency remains a separate metric
and must not be used to describe identity84% as51%. This updates the active target;
historical sealed protocols/results remain unchanged. Recall10>=95%, CPU viability
and modest RAM still apply. Current native identity168/200; twelve net additional
correct first pieces are needed for180/200. Private acceptance remains unopened.

## Confirmed observations

All32 native failures are decided by numeric model scores, not exact bypasses or
ties. Correct piece ranks:2(18cases),3(4),4(4),5(1),6(1),7(1),18(1),21(1),73(1).
All200 acceptable pieces are in the complete candidate pool. Files account for13
of32 failures (file37/50, class44/50, module44/50, symbol43/50 correct first).

Class/module/file ordering inherits the position of its highest-ranked projected
owner. For vp-cs-005, CodeGen.try promotes classCodeGen above classTry. A promising
method can therefore select the wrong containing class; the class is not directly
scored as a whole requested piece. This mechanism is confirmed, while the benefit
of a replacement aggregation/ranker still needs an all-case test.

The251feature trace shows query_kind_class==0 in all200 queries, including every
one of the50 class requests. The feature derives from interpret(request).kind,
whose concrete kind is currently attached to a recognized named declaration.
The benchmark caller passes target='symbol' for both class and symbol requests;
class projection happens afterward. Thus descriptive class intent is absent from
that explicit feature. Setting this old feature to1 without examining its training
contract is not a validated fix; represent requested piece kind deliberately.

Observed role confusions include a typing test vs the module defining the API,
the consumer MethodOrderingVisitor vs the requested MethodOrderer interface,
a JSON data schema vs the validator implementation, and unquote vs the byte decoder
unquote_to_bytes. Existing role/kind/similarity signals are insufficient for these
decisions. Missing relation/contract discrimination is a hypothesis supported by
the selected/correct pairs, not yet an isolated causal improvement experiment.

## Single-feature diagnostic counterfactual

Following superpowers:systematic-debugging, test one hypothesis before a fix:
the reciprocal initial rank may override more useful implementation evidence.
The policy was fixed before replay: in every query, set ONLY rrf_rank to the
within-query median of its actual candidate values. Preserve all other250features,
models, candidate identities, exact priority, ties and piece projection. All200
orders closed before fixed, already exposed development reference scoring.

Native168/200=84% -> counterfactual157/200=78.5%;4gains/15losses. Recall10
197/200 ->196/200. Gains:vp-mf-047,vp-cs-037,vp-cs-045,vp-cs-065. Eight-repository
cluster identity difference interval[-.107759266,-.009478673]. Therefore this
particular neutralization harms overall ranking even though it fixes some errors.
It is not a production change, a retrained ablation or causal feature importance;
correlated retrieval priors still exist. No model/default/weight was changed.

Artifacts:output/analysis/rrf-rank-counterfactual-v121/{registration.json,
predictions.jsonl,summary.json,graded.json}. Registration SHA256:
0be9773a980e57319fb9b19ae35277eca4b44ab8e469f632d0ff66338fbd2d92.
Producer is the clean frozen v120 core, receipt
7e470b3803391476d62691ca522ae73d6f3fd950d6d82b5bfd2d6b925c4b8657.

Next ranking hypotheses should address requested piece kind and owner-to-piece
aggregation, then distinguish definition/usage/data roles and the specific behavior
conditions. Test one change at a time over all200 and retain only net improvements
with preserved Recall10; these observations do not prove90% on private acceptance.
