# x86 numerical execution diagnosis

Continue the authorized x86-only migration by resolving the numerical evidence
blocking CST acceptance. Do not attribute the EPYC9V45 failure to hardware merely
because the successful runs used3975WX/7763. The current measurable failures are
context boundary511 (-.015078825876116753 vs .15921735763549805) and alignment
product-float32-float32-float64-4-128-3/weighted
(2.1855457487859224 vs2.1855458146647404).

First establish the contract on one actual machine: independent original Python
adapter/library execution, native public callers, frozen data and accepted
baseline. Diagnostic observations are not replacement oracles and never rewrite
fixtures/tolerances/models. Source identity and raw command exits must accompany
all conclusions. A diagnostic workflow succeeding means recording completed;
it does not turn failing model gates into success.

Responsibilities: diagnostic inputs select existing bounded counterexamples and
strip answers; Python context/alignment observers call existing original APIs;
recorded commands preserve stdin/stdout/stderr/exit/digests; comparison reports
separate native-vs-Python parity, frozen-vs-current differences and intervention
results. Main model gates retain their strict failure propagation.

Use the existing input-only context_probe/numeric_owner_probe. Observe context
empty-query/boundary511/boundary512 with the actual Python adapter, then native and
Python raw ORT file/memory sessions with1/2threads. Observe exact alignment inputs
and intermediate similarities/maxima/coverage under native OpenBLAS selection and
an explicit Haswell intervention in fresh processes; record get_corename. No
AVX512 kernel is forced on an AVX2-only machine. Compare full8root and filtered
registered context tests plus alignment target for candidate and accepted49bf
baseline on the SAME runner, with authenticated identical model/math sources.
Keep failure exits as data, not successful software verdicts. Run two bounded x86
replicas to sample the shared runner pool, never retry until green. If neither
exposes the differing execution regime, record that limitation explicitly.

Keep the existing isolated migration branch and prior raw/workspaces unchanged.
Implement inline with TDD; no implementation agents. One fresh final read-only
review for this NEW diagnostic plan, at most one Important repair pass, no
re-review. Preserve all data locally and push to the authorized branch. A runtime
or oracle policy change needs a demonstrated cause; this plan initially delivers
complete diagnosis tooling and observations, then records the smallest justified
correction if the evidence supports one. Unsupported claims remain pending.
