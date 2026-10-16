# Named source locators: preserve identity before semantic ranking

Problem: native identifier parsing permits dots but rejects `::` and slashes.
Queries such as `Locate the definition of pkg.module::Reader.read_value` lose
their exact identity and run full semantic ranking. Nine of40 exposed qualified
lookups in new symbol200 return another related owner, despite the correct one
being in the ten. This is input/identity loss, not a learned-score defect.

Representative public use:

    search_best(conn, root, SearchRequest(
        'Locate the definition of `store.config::Reader.read_value`.',
        piece_kind='symbol'))

It should return src/store/config.py::Reader.read_value without loading models,
even when other files or sibling classes contain a read_value method. Requests
about callers or behavior merely mentioning that locator retain semantic search.

Responsibility: SourceLocator represents one explicit namespace/path plus exact
qualified symbol. It owns conservative parsing and identity matching. Existing
exact_candidates owns retrieving matching source owners in the pinned generation;
existing best-search unique-exact shortcut owns model-free response construction.
No scoring rule, learned parameter, kind inference or semantic evidence changes.

Only bare/backticked locators or anchored full EN/ES definition/declaration
requests ending immediately after one locator gain authority. Reject multiple
targets, trailing behavior clauses, malformed/traversal namespaces, nonidentifiers.
Match full symbol case-sensitively, and module/path together. Reuse module_name
for Python/JS/TS; literal indexed paths also work. Java namespace convention is
physical package directory plus Class.member; this is a path locator, not proof
that source package declarations match directories. Ambiguous overloads retain
multiple exact candidates; do not invent an ordinal.

Tests first cover parser positives/negatives, exact namespace plus complete member,
Python packages, TS paths, Java directory namespace, cross-module rejection, and
public best-search with models forbidden. Initial19tests:18fail/1pass (existing
cross-module false positive absent). Keep separate from static-cache candidate:
finish its full-suite/original200 closure before changing any production source.

Then run dedicated tests, integration suite/mypy, model-free exact replay of all
400 exposed queries, and complete200original plus200new actual public MCP before
making new quality claims. Report every candidate/order/recall change separately.
No private balanced reserve access, no release, no hardcoded query IDs or names.
This correction alone does not promise90%; prospective fresh acceptance gate stays
original>=180/197 and new-development>=180, then independent>=180/197.
