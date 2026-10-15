# v114: cite a coherent lexical scope with explicit member attribution

Approved goal unchanged: correct requested piece plus enough visible source,
64physical lines/4excerpts/12000canonical JSON chars, Recall10≥95%, CPU/modestRAM.
Development200 is exposed; hidden v104 acceptance remains closed. No model,
ranking, references, public query/facets or pass criteria changes.

Old contract: every excerpt is exclusively owned by ONE canonical entity.
This excludes member bodies from a class quotation and nested declarations from
a function quotation even when their complete source fits. File evidence can
choose a nested test class but omit the enclosing test's actual assertions.

New optional excerpt mode: scope="lexical_container" identifies a complete
class/function extent; included_entities lists exactly its known canonical
descendants, rather than attributing those lines exclusively to the container.
Only an entirely source-covered scope that fits the SAME card limits is eligible.
Unknown nonblank ownership gaps, forged descendants, unrelated siblings and
fabricated text fail validation. Existing exclusive excerpts keep their old
contract. No new source text is hidden in metadata or exempt from the budget.
The existing supporting-method test now checks the exact canonical method in
either an exclusive excerpt or the explicit included owner list; it retains the
ownership assertion rather than requiring the old field layout. No acceptance
test, source gap guard, budget check or case is removed or weakened.

For class/symbol answers prefer a complete small scope when it actually contains
known nested owners; keep the requested unit. For file/module answers, a nested
owner may use its complete small enclosing callable as the evidence capsule,
keeping the same physical/importable unit. If it cannot be proved/fit, retain
the current owner selection. Large-scope/complementary selection is future work.

SourceCatalog owns canonical extents/lexical containment and coverage, with
instance-local caches. Quotation/validation own the new discriminated mode.
LocalCallEvidence must recognize validated included caller owners when checking
visible calls, while its conservative call-resolution contract stays unchanged.
No caller-specific rules, test labels, path whitelist or expected facets.

Consumers: verifiable_cpu_run constructs cards; verifiable_blind_inputs validates
them; card_text renders the literal source; LocalCallEvidence composes support.
Generic canonical hashes, identity/strict graders and source inventories retain
their schemas. Historical frozen producers/reports/shadow inputs remain untouched.
Ken cannot index these ignored experiments; direct consumer inspection identified
these boundaries. No applicable pre-existing KQL contract certifies this format.

Tests first: complete short class including its third method; nested-class file
evidence including constructor plus enclosing assertions; complete outer symbol
with explicit nested attribution; forged/omitted member attribution rejected;
existing unknown-owner gaps and64-line limits retained. Then freeze and rerun
all200, authenticate source/budgets and preserve candidate identity/order. New
visible cards require independent review; no joint percentage until full closure.
