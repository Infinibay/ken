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

**Anchor it, or it only fires if someone searches.** An anchored memory is
handed to whoever next touches the same thing — no query needed:
`ken_remember(topic, content, anchor_file="src/db/service.py")`, or
`anchor_symbol` for one function, `anchor_tool="pytest"` for a command,
`anchor_error="database is locked"` for a message (matched as a substring of
whatever the tool reports). Set as many as apply; the memory fires on any.
