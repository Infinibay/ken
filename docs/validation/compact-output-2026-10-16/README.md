# Compact public presentation

The user requested compact text by default for all CLI commands and MCP tools,
plus examples of each output. This slice changes presentation; the subsequent
best-default search integration has its own design and validation.

- MCP tools publish output_format="compact" (default) or "json". Registered
  transport functions render text, while internal Python functions keep native
  data. This avoids breaking tools that call other tools internally.
- `ken tools read ...` prints the same compact text as MCP. `ken tools --json
  read ...` or `ken tools read ... --output-format json` returns native JSON.
  The older global `--compact` retains its single-line JSON meaning for scripts.
- `ken search-files` and `ken search-symbols` show locations/names plus up to8
  current source lines, labeled live previews. Search order is unchanged in this
  slice. Indexed locations are not claimed to be hash-verified symbol evidence.
- `ken_read` preserves its selected source budget and numbers returned lines.
  Disjoint excerpts remain separate. FTS text without real source coordinates
  stays unnumbered. Partial/stale/errors, source scopes and unknown coverage stay
  visible. No global clip that could delete a negation or a warning is added.
- `ken structural ... --json`, `ken kql2 ... --json` and `python -m ken.kql2
  ... --json` preserve previous structured data. KQL2 compact rows retain column
  bindings and row boundaries. `--full`, `full=True` or `explain=True` retains
  diagnostic detail in the chosen presentation.
- `ken_who` omits the expandable responsibility graph while keeping candidate
  evidence, counterevidence, assumptions and any incomplete verification.
  `ken_reason` keeps bindings, premise sources, semantic caveats and search
  completeness while omitting its recursive proof trace. JSON retains it all.
- Commands already returning concise text (status, install, models, index
  preparation, bench summaries, etc.) keep that text. Hook and JSON-RPC protocol
  envelopes retain their required machine framing; compact text is tool content,
  not a replacement for the transport protocol.

[EXAMPLES.md](EXAMPLES.md) contains exact captured output from all12 MCP tools in
one persistent session and7 CLI invocations on a disposable three-file project.
[captures.json](captures.json) stores the full capture and exit codes; the
[capture script](capture_examples.py) creates the fixture and replays those calls.
These samples show presentation, not retrieval quality. The embedding/profile
used by this presentation-only snapshot is the preexisting static-Qwen default;
regenerate after the separately authorized best-profile integration.

Real SDK stdio tests explicitly provide absolute PYTHONPATH. The client SDK does
not inherit PYTHONPATH by default; omitting it can accidentally test an older
installed package while in-process tests use the changed source.

Verification closed with14843 tests passed and10 preexisting expected failures
in528.51s. Final source-line fidelity refinements subsequently passed160 focused
tests in9.69s. Mypy found no issues in342sourcefiles. The exact commands and
logs were preserved locally in /private/tmp/ken-compact-full3.log,
/private/tmp/ken-compact-final-focused.log and
/private/tmp/ken-compact-mypy-final2.log. The full compatibility run preceded the
final presentation-only refinements; the focused follow-up exercises those.
Mutation disabling the output-format guard was caught by its contract test,
and the original source bytes were restored before verification.
