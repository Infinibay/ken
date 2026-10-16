# Optional project guidance and English code queries

Interactive `ken install` offers to append a compact managed section to
AGENTS.md, default yes. --agents-md/--no-agents-md are explicit script choices.
Noninteractive and quiet defaults do not prompt or write instructions; an
explicit yes works without stdin. --no-wire skips instructions. Existing user
content, CRLF prefixes, unowned blocks, symlinks and local edits are preserved.
Ownership hashes live separately in .ken/instructions.json; uninstall removes
only unchanged owned sections. Claude integration adds a managed @AGENTS.md
import without replacing CLAUDE.md. The canonical recommended text also appears
in README. No existing project instructions were automatically replaced.

English natural-language code-search guidance is exposed in ken_find,ken_who
and ken_rank descriptions, plus all eight bundled skills. Paths, identifiers,
quoted source, literal search, regex and KQL stay unchanged; the assistant
responds in the user's language. Exact memory keys are preserved and memory
queries may use the saved finding's language. This guides callers; the engine
does not silently translate literal input or change stored session context.

Validation:15011tests passed,10existing xfails; mypy361sourcefiles clean.
23focused installer tests pass. New file-system tests use real temporary files,
terminal input boundaries and public CLI installation/uninstallation. A real
explicit install twice preserves identical AGENTS.md bytes; CLI help shows both
flags. A fresh MCP stdio tools/list exposes the English descriptions and compact
default schema. This does not restart the already connected older MCP process.
These checks establish interface/content delivery, not measured agent adherence.

The first full suite failed because the existing fake_install test double did
not accept the approved new optional argument. Its original flag assertions
are retained and expanded to all three instruction choices; the complete final
suite was then rerun successfully. Both logs remain. The initial tools-list
probe used the SDK's unaliased dictionary keys and stopped during a schema
assertion; the final probe uses public JSON field aliases. Product behavior
was unchanged by that probe repair. No failed run is counted as a pass.

The five V214engine files are byte-identical to8ce6b00c. MCP server ASTs are
identical after stripping docstrings, so tool description changes do not alter
ranking, schemas or response logic. V214quality remains its separate, closed
actual MCP evidence. No new400accuracy or latency claim is made from prose edits.
English development goal is110/120 and108/120top1,118/119Recall10, reserveCLOSED.

manifest.json authenticates compressed payloads and their original logical
paths with SHA256 and byte counts. Full logs, failed probes, final tools-list,
real installed instructions and test/type receipts are retained. No release.
