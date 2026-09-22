## Design by concepts and responsibilities (outside-in)

Use **concept-driven, responsibility-focused, outside-in design** as the default
way of programming in this repository. Aim for elegance, extensibility, and
maintainability together: a small set of clear concepts that solves the current
problem and remains useful as the system evolves.

1. **Understand the core problem first.** Start with the overall purpose and
   the essential problem to solve. Identify the concepts involved before
   choosing implementation details, frameworks, or patterns.
2. **Name the concepts and their responsibilities.** Give each important
   concept a precise name and express its role in one clear sentence. Let
   those concepts guide the names of classes, modules, and functions. Choose
   the representation that fits; not every concept needs a class. A component
   should have one coherent responsibility and a clear reason to change.
3. **Design from use toward implementation.** Write a representative usage
   example or caller first. Sketch the interfaces, methods, collaborators,
   inputs, outputs, and failure behavior needed to make that usage natural.
   Temporary empty bodies are useful design scaffolding; implement them or
   remove them before presenting the work as complete.
4. **Decompose recursively as problems appear.** When a component needs work
   outside its role, identify that new problem, name its concept, define its
   interface, and delegate to it. Repeat outside-in at each level. Keep
   orchestration concerned with coordination and domain decisions with the
   concept that owns them. Moving a large conditional into another file does
   not by itself improve the decomposition.
5. **Keep logic with its owner.** A rule, invariant, or decision should have
   one authoritative home. Check whether someone investigating a behavior
   would naturally look there. Avoid duplicated rules, hidden dependencies,
   and classes that accumulate unrelated work.
6. **Make extension a design check.** Consider a plausible next capability:
   which parts would change? Prefer adding or composing a focused component
   through an explicit interface over modifying unrelated components. Build
   extension points around real variation; keep hypothetical capabilities
   inexpensive to add without implementing them in advance.
7. **Make debugging and maintenance design checks.** Keep dependencies,
   state transitions, inputs, outputs, and errors understandable. A failure
   should be traceable to a small, identifiable responsibility. Use tests at
   meaningful boundaries and through representative public usage to verify
   behavior without coupling them to incidental implementation details.
8. **Refine the model through working examples.** Implement a complete slice,
   exercise it, and revisit names, boundaries, and interfaces when the code
   reveals a better understanding. Keep the design proportional to the
   problem; unnecessary layers and fragmented one-line classes can obscure
   it as much as oversized classes.

Before considering a nontrivial change finished, ask: Is the core concept
clear? Does each component have one role? Is every piece of logic where it
belongs? Is any component doing too much? Is the problem divided into parts
that can be understood independently? Can the next capability be added
locally? Would a bug be easy to locate?

Treat **beauty as conceptual clarity, coherence, and economy**, and **potential
as useful composability and room to evolve**. Judge the design by how naturally
it expresses the problem and how little unrelated code must change to extend
or repair it.

## Code intelligence: ken

**A `<context-rank>` block in the prompt is ken's ranked guess for this
request**: `Files:` best first, then `Symbols:`, then `Notes:` — finding
*topics*, which `ken_recall(topic="…")` reads. If it names what you need,
open that and skip searching. If a listed file turns out to be irrelevant,
`ken_remember(path, action="dismiss", reason=…)` — the ranker's only
negative signal, and only while the block is still in front of you. Thin or
missing? `ken_rank(verbose=2)`, or `ken_find(task, scope="intent")` for the
files that work like this one actually landed in.

**Start with one `ken_find`, not with `rg` or a guessed path.** The scope is
the whole decision:

- an exact string or identifier (`MY_ENV_VAR`, `os.path`) → `scope="text", literal=true`
- which file does X → `scope="files"`
- which function or class does X → `scope="symbols"`
- how a route, CLI command or env var reaches its handler → `scope="wiring"`

Then read what it named — `ken_read(path)` for the outline, plus
`include=["source"]` and a *qualname* for one symbol's body. ken narrows
where to look; it does not replace reading the code.

**Stop rules.** If two ken calls have not narrowed it, open the likeliest
file and read — a third will not help. If ken returns nothing, use `rg`: it
searches the index, so a file created minutes ago may not be in it yet. A
question you can already answer from context needs no call at all.

**Before editing a file you have not read this session**, `ken_recall(path=…)`
— what earlier sessions learned there. If the change is not local:
`ken_related(path, relation="blast_radius")` for what it breaks,
`relation="cochange"` for what moves with it that imports do not show, and
`ken_find(path, scope="tests")` for its tests.

**Write back what cost you real effort** — a root cause, a constraint the
code does not state, a trap you fell into: `ken_remember(topic, content)`.
Not what the code already says plainly. Re-using a topic overwrites it.

For a conclusion that depends on code or an experiment, use the optional
`justification` object to retain its rationale, evidence files, dependencies,
assumptions and recheck step (see `docs/design/justified-memory.md`). Keep
`content` a concise conclusion. Declare a tree scope for absence/search claims
so new files can invalidate them. `unchanged` means declared inputs match, not
that the conclusion or assumptions were independently proved. Use
`ken_recall(topic="…", detail="answer")` to start with the whole conclusion,
sources, assumptions and validity. Reuse it only when question, scope and
assumptions fit; expand with `detail="full"` or read the relevant symbol when
evidence is missing or stale. `detail="summary"` adds a short rationale. Do not
repeat structural inspection solely because a memory was retrieved. Plain notes
remain appropriate for unformalized findings.

**Anchor it, or it only fires if someone searches.** An anchored memory is
handed to whoever next touches the same thing — no query needed:
`ken_remember(topic, content, anchor_file="src/db/service.py")`, or
`anchor_symbol` for one function, `anchor_tool="pytest"` for a command,
`anchor_error="database is locked"` for a message (matched as a substring of
whatever the tool reports). Set as many as apply; the memory fires on any.
