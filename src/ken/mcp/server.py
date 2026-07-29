"""stdio MCP server — entrypoint for ``ken mcp``.

Built on the official ``mcp`` Python SDK v2. The old ``FastMCP`` class
was renamed to ``MCPServer``; the decorator API (``@mcp.tool()``) is the
same shape it always was, so every tool below is a plain function with
type annotations and a docstring — same surface ken has exposed since
0.x. The CLI passthrough (``ken tools ...``) reads from a parallel
registry populated alongside the SDK registration, so it does not need
to spin up the stdio server to list tools.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import sys
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mcp.server import MCPServer

from ken import _paths
from ken.clones import clones
from ken.cochange import cochange
from ken.codeflow import callgraph, type_hierarchy, wiring
from ken.db import connect
from ken.graphtools import architecture, blast_radius
from ken.grep import grep
from ken.intent import intent_history
from ken.memory import forget, list_findings, recall, remember
from ken.profile import profile
from ken.search import (
    changed_context,
    file_neighbors,
    file_outline,
    file_snippets,
    file_symbols,
    find_tests,
    module_graph,
    project_overview,
    search_files,
    search_symbols,
    symbol_detail,
)

logger = logging.getLogger("ken.mcp")

# Each `ken mcp` is a *single project* server — coding agents launch
# one instance per workspace. The project root is resolved once at
# startup; if it's not a ken project we fail fast so the user sees
# a clear error in their MCP logs.
_PROJECT_ROOT: Path | None = None

mcp = MCPServer("ken")


def run(start: Path) -> int:
    """Resolve the project root, then hand control to the MCP stdio loop."""
    global _PROJECT_ROOT
    root = _paths.find_project_root(start.resolve()) or start.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"ken mcp: no .ken project at {root}", file=sys.stderr)
        return 1
    _PROJECT_ROOT = root
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("ken mcp ready project_root=%s", root)
    mcp.run(transport="stdio")
    return 0


# ---- CLI tool registry --------------------------------------------------
#
# ``ken tools ...`` (the shell-side passthrough) reads tool names,
# descriptions, and parameter schemas from this registry so it does not
# need to spin up the MCP stdio loop just to print ``--help`` text. We
# mirror each ``@mcp.tool()`` registration into ``_REGISTRY`` via the
# ``_register`` helper below.


@dataclass
class ToolDef:
    """Lightweight record of a registered MCP tool.

    Mirrors the public surface of the old ``fastmcp.Tool`` object that
    ``ken tools ...`` was reading via ``mcp._tool_manager.list_tools()``:
    ``name``, ``description``, ``parameters`` (JSON schema), ``fn``, and
    ``is_async``.
    """

    name: str
    description: str
    fn: Callable[..., Any]
    is_async: bool
    parameters: dict[str, Any]
    input_schema: dict[str, Any]


_REGISTRY: dict[str, ToolDef] = {}


def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Build a ``ToolDef`` from a function and stash it in ``_REGISTRY``.

    The function name becomes the tool name (callers use the
    ``ken_foo`` convention themselves). The JSON schema is derived from
    the function's signature — annotations become ``properties``,
    parameters with defaults become optional, the rest required. This is
    the same shape the SDK derives internally, so any agent that reads
    those schemas sees the same surface either way.
    """
    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        prop, has_default = _annotation_to_schema(param)
        if prop is None:
            continue
        if not has_default:
            required.append(name)
        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    _REGISTRY[fn.__name__] = ToolDef(
        name=fn.__name__,
        description=(fn.__doc__ or "").strip(),
        fn=fn,
        is_async=inspect.iscoroutinefunction(fn),
        parameters=schema,
        input_schema=schema,
    )
    return fn


def ken_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register ``fn`` as both an MCP tool and a CLI-passthrough tool."""
    mcp.add_tool(fn)
    _register(fn)
    return fn


def list_tools() -> list[ToolDef]:
    """Snapshot of every registered tool, in insertion order."""
    return list(_REGISTRY.values())


# ── JSON-Schema derivation ─────────────────────────────────────────────
#
# Mirrors what the SDK's MCPServer does internally — narrowly, only for
# the annotation shapes ken actually uses (``str``, ``int``, ``float``,
# ``bool``, ``list[...]``, ``dict[...]``, ``X | None`` / ``Optional[X]``).

_PRIMITIVE_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _annotation_to_schema(
    param: inspect.Parameter,
) -> tuple[dict[str, Any] | None, bool]:
    """Return ``(schema_dict, has_default)`` for a single function parameter.

    ``has_default`` is True when the parameter is optional in the JSON
    schema sense — either it has a Python default or its annotation is
    ``Optional[X]`` / ``X | None``. Returns ``(None, True)`` for
    ``*args`` / ``**kwargs`` / ``self``, which are not part of the schema.
    """
    if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
        return None, True

    has_default = param.default is not inspect.Parameter.empty
    annotation = param.annotation

    core, is_optional = _unwrap_optional(annotation)
    if is_optional:
        has_default = True

    if core is inspect.Parameter.empty or core is None:
        schema: dict[str, Any] = {}
    elif core in _PRIMITIVE_JSON_TYPE:
        schema = {"type": _PRIMITIVE_JSON_TYPE[core]}
    elif origin := typing.get_origin(core):
        if origin in (list, typing.List):
            schema = {"type": "array", "items": _items_schema(typing.get_args(core))}
        elif origin in (dict, typing.Dict):
            schema = {"type": "object"}
        else:
            schema = {}
    elif isinstance(core, type):
        schema = {"type": "string"}  # named types → opaque string for the agent
    else:
        schema = {}

    if param.default is not inspect.Parameter.empty and param.default is not None:
        schema["default"] = param.default

    return schema, has_default


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(inner, is_optional)`` for ``X | None`` / ``Optional[X]`` / ``None``."""
    if annotation is None or annotation is type(None):
        return type(None), True
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(annotation)) > 1:
            return args[0], True
        return annotation, False
    return annotation, False


def _items_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    if not args:
        return {}
    inner, _ = _unwrap_optional(args[0])
    if inner in _PRIMITIVE_JSON_TYPE:
        return {"type": _PRIMITIVE_JSON_TYPE[inner]}
    return {}


def _conn() -> sqlite3.Connection:
    if _PROJECT_ROOT is None:
        raise RuntimeError("MCP server not initialised — call run() first")
    return connect(_paths.db_path(_PROJECT_ROOT))


# ---- MCP server tools ----------------------------------------------
#
# Same surface as before — same names, same docstrings, same parameter
# annotations and defaults. Only the registration mechanism changed
# (``@mcp.tool()`` now lives on ``MCPServer`` instead of ``FastMCP``);
# the bodies are byte-for-byte identical to the pre-migration server.


@ken_tool
def ken_search_files(query: str, limit: int = 8) -> list[dict]:
    """Search the project's indexed files for ones semantically relevant to *query*.

    Cosine similarity against per-file embeddings (built from each
    file's language + base name + top symbol names — same shape the
    ranker's fuzzy channel uses). Returns the top *limit* hits with
    their score and a short symbol outline.

    When *query* is a bare identifier (``cochange``, ``reembed``) the semantic
    order is fused with a literal path match, and files matching it exactly are
    listed first with ``match: "exact"``. ``score`` stays the cosine either
    way, so with a literal match present the list is not in score order.
    """
    with _conn() as conn:
        return search_files(conn, query, limit=limit, project_root=_PROJECT_ROOT)


@ken_tool
def ken_search_symbols(query: str, limit: int = 10) -> list[dict]:
    """Search the project's indexed symbols (functions, classes, methods) for
    ones semantically relevant to *query*.

    Cosine similarity against per-symbol embeddings (built from
    ``"{kind} {name} — {docstring_first_line}"``). Returns the top
    *limit* hits with their location and one-line doc.

    When *query* is a bare identifier the semantic order is fused with a
    literal name match: symbols named exactly that come first
    (``match: "exact"``), then partial matches (``"qualified"`` for a method of
    a class, ``"tokens"`` for a shared-word name) traded off against
    similarity. Without this a query like ``blast_radius`` returns
    ``test_blast_radius_reverse_reachability`` above the function itself.
    ``score`` remains the cosine, so the list is not in score order when a
    literal match is present. Prose queries are pure similarity, unchanged.
    """
    with _conn() as conn:
        return search_symbols(conn, query, limit=limit, project_root=_PROJECT_ROOT)


@ken_tool
def ken_file_symbols(path: str, include_docstrings: bool = True) -> dict:
    """Return the indexed symbol structure for one file.

    *path* is the project-relative file path stored in Ken's index, such
    as ``src/ken/search.py``. Returns all symbols ordered by source line
    with kind, name, qualified name, start/end lines, and optionally the
    first docstring/comment line captured by the parser.
    """
    with _conn() as conn:
        return file_symbols(
            conn,
            path,
            include_docstrings=include_docstrings,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_file_outline(
    path: str,
    include_symbols: bool = True,
    include_imports: bool = True,
    include_docstrings: bool = True,
) -> dict:
    """Return a structural outline for one indexed file.

    Includes language, symbol count, optional symbols, optional imports,
    optional reverse imports, and optional first-line docstrings.
    """
    with _conn() as conn:
        return file_outline(
            conn,
            path,
            include_symbols=include_symbols,
            include_imports=include_imports,
            include_docstrings=include_docstrings,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_file_neighbors(path: str, limit: int = 20) -> dict:
    """Return files directly related to *path*.

    Uses resolved internal imports, reverse imports, and test-file
    heuristics to suggest files worth inspecting alongside the target.
    """
    with _conn() as conn:
        return file_neighbors(conn, path, limit=limit, project_root=_PROJECT_ROOT)


@ken_tool
def ken_symbol_detail(path: str, qualname: str, include_snippet: bool = False) -> dict:
    """Return metadata for one symbol in one file, optionally with source."""
    with _conn() as conn:
        return symbol_detail(
            conn,
            path,
            qualname,
            include_snippet=include_snippet,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_module_graph(path: str, depth: int = 1, limit: int = 100) -> dict:
    """Return a bounded local import graph around one indexed file.

    ``limit`` caps *nodes*. Every returned edge has both endpoints in ``nodes``,
    so the graph is always well-formed; when the cap cut the neighbourhood
    short, a ``truncated`` block reports how many edges that dropped.
    """
    with _conn() as conn:
        return module_graph(
            conn, path, depth=depth, limit=limit, project_root=_PROJECT_ROOT
        )


@ken_tool
def ken_find_tests(path: str, limit: int = 20) -> dict:
    """Return likely test files for an indexed source file, best evidence first.

    Each candidate accumulates every channel that fired, and ``score`` ranks
    them: being named by the ecosystem's convention (``test_x``, ``x_test``,
    ``x.spec.ts``, ``XTest.java``) counts far more than merely importing the
    target — for a widely-imported module like ``db.py`` almost every test does
    that. Name matching is on whole tokens, so ``cli.py`` does not pull in
    ``test_client.py``.
    """
    with _conn() as conn:
        return find_tests(conn, path, limit=limit, project_root=_PROJECT_ROOT)


@ken_tool
def ken_changed_context() -> dict:
    """Return current git changes enriched with indexed symbols and tests."""
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return changed_context(conn, _PROJECT_ROOT)


@ken_tool
def ken_file_snippets(
    path: str,
    symbols: list[str] | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 12000,
) -> dict:
    """Return source snippets for selected symbols or a line range."""
    with _conn() as conn:
        return file_snippets(
            conn,
            path,
            symbols=symbols,
            start_line=start_line,
            end_line=end_line,
            max_chars=max_chars,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_project_overview(depth: int = 2, limit: int = 20) -> dict:
    """Return a compact structural overview of the indexed project."""
    with _conn() as conn:
        return project_overview(conn, depth=depth, limit=limit)


@ken_tool
def ken_remember(
    topic: str,
    content: str,
    tags: list[str] | None = None,
    kind: str | None = None,
) -> dict:
    """Write a finding for future sessions to recall.

    *topic* is a short lookup key (unique — re-using a topic updates
    the existing row). *content* is the body — usually a few sentences
    capturing a fact you don't want to re-derive next time. *kind* can
    explicitly classify the note as finding, persistent_rule,
    experimental_finding, or hypothesis.
    """
    with _conn() as conn:
        return remember(conn, topic, content, tags=tags, kind=kind)


@ken_tool
def ken_forget(topic: str) -> dict:
    """Delete a saved finding by exact *topic*.

    Use ``ken_findings`` or ``ken_recall`` first if you need to discover
    the exact topic. Returns ``deleted=0`` when no finding matched.
    """
    with _conn() as conn:
        return forget(conn, topic)


@ken_tool
def ken_findings(limit: int = 20, tag: str | None = None) -> list[dict]:
    """List recent saved findings, optionally filtering by exact tag."""
    with _conn() as conn:
        return list_findings(conn, limit=limit, tag=tag)


@ken_tool
def ken_recall(query: str, limit: int = 5, min_score: float = 0.25) -> list[dict]:
    """Search previously-saved findings by semantic similarity to *query*.

    Results below *min_score* are omitted. Set ``min_score=0`` to inspect
    nearest neighbors even when they are likely noise.
    """
    with _conn() as conn:
        return recall(conn, query, limit=limit, min_score=min_score)


@ken_tool
def ken_related_findings(
    topic: str,
    limit: int = 8,
    min_weight: float = 0.3,
) -> dict:
    """Saved findings related to *topic* in the findings knowledge graph.

    Links are deterministic and evidence-cited: two findings connect when they
    reference the same file/symbol (``shared_file`` / ``shared_symbol`` — exact),
    share meaningful tags (``shared_tag``), or are close in embedding space
    (``semantic`` — approximate). *topic* resolves by exact match, else the top
    ``ken_recall`` hit. Neighbors are ranked evidence-backed-first, then by
    weight; each carries its per-edge evidence. Returns empty rather than guessing.
    """
    with _conn() as conn:
        from ken.findings_graph import related_findings

        return related_findings(conn, topic, limit=limit, min_weight=min_weight)


@ken_tool
def ken_file_findings(path: str, expand: bool = False, limit: int = 15) -> dict:
    """Durable findings that reference *path* — "what do we already know here?".

    Uses the finding→code bridge: each saved finding's prose is resolved to
    indexed ``ci_files`` paths, so this surfaces accumulated knowledge about a
    file before you edit it. With ``expand=True``, also returns findings one hop
    away in the graph. Resolution is index-based, so it lags a just-deleted file
    until the next reindex.
    """
    with _conn() as conn:
        from ken.findings_graph import file_findings

        return file_findings(
            conn, path, expand=expand, limit=limit, project_root=_PROJECT_ROOT
        )


@ken_tool
def ken_cochange(
    path: str,
    min_confidence: float = 0.4,
    min_support: int = 3,
    min_llr: float = 3.841,
    limit: int = 15,
) -> dict:
    """Files historically changed together with *path* — including hidden coupling.

    Mines git commit history as market-basket transactions (support /
    confidence / lift with recency decay) and **subtracts the import graph**,
    so the headline is the logical coupling imports can't see: schema <->
    migration, code <-> config, parallel implementations. Partners with no
    import edge are flagged ``hidden_coupling`` and sorted first. Returns an
    empty list rather than guessing when evidence is below threshold.

    Statistics are computed within the target file's own repo (``scope``), so a
    workspace of sibling repos does not inflate lift. Per partner:

    * ``confidence`` — P(partner changes | target changes), recency-weighted.
    * ``confidence_low`` — Wilson 95% lower bound on that probability from the
      raw counts. Read this, not ``confidence``, when support is small.
    * ``lift`` — how many times more often than chance they co-change.
    * ``llr`` — Dunning G², a χ²(1) significance score. Pairs below *min_llr*
      (default 3.841 = p<0.05) are dropped as indistinguishable from chance,
      however high their lift. Pass ``min_llr=0`` to see them anyway.
    * ``strength`` — the ranking key: confidence discounted by evidence thinness.
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return cochange(
            conn,
            path,
            min_confidence=min_confidence,
            min_support=min_support,
            min_llr=min_llr,
            limit=limit,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_blast_radius(path: str, max_hops: int = 4) -> dict:
    """Files likely affected by editing *path*, with per-channel evidence.

    Reverse import reachability (transitive importers + hop distance) unioned
    with test heuristics and git co-change. Every impacted file lists its
    evidence ("imports(hop 2)", "test-of", "co-changed 8x") — never a fused
    black-box score. Reports unresolved-import coverage as an explicit lower
    bound, so the agent knows the result is a floor, not a ceiling.
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return blast_radius(conn, path, max_hops=max_hops, project_root=_PROJECT_ROOT)


@ken_tool
def ken_architecture(depth: int = 2, limit: int = 20) -> dict:
    """Subsystems, layers, dependency cycles, and load-bearing hubs of the project.

    Graph algorithms over the resolved import graph: Tarjan SCC (import
    cycles — exact), topological layering (approximate), label-propagation
    communities, and PageRank hubs + reverse-PageRank foundations. Every
    result carries an ``edge_coverage`` header ("resolves 140/210 imports")
    so the agent calibrates: cycles are high-trust, layers/communities degrade
    as unresolved imports rise.

    Output is bounded for large monorepos: ``limit`` caps items per list and
    files listed per item (cycles/clusters/layers report a ``size`` plus a
    capped sample), and ``depth`` is how many layers carry file samples (deeper
    layers are size-only). A ``summary`` reports the full counts. Raise either
    to see more.
    """
    with _conn() as conn:
        return architecture(conn, depth=depth, limit=limit)


@ken_tool
def ken_profile(path: str, granularity: str = "file", top_terms: int = 12) -> dict:
    """What a file/package is *for* and what distinguishes it from its siblings.

    Weighted log-odds-ratio with an informative Dirichlet prior (Monroe et
    al.) over the file's symbol names, qualnames, and docstrings — every term
    is a real, verifiable token from the index, not a generated summary. Set
    ``granularity='dir'`` to profile a whole package. Reports evidence
    strength so thin directories are flagged.
    """
    with _conn() as conn:
        return profile(conn, path, granularity=granularity, top_terms=top_terms)


@ken_tool
def ken_clones(
    path: str | None = None,
    qualname: str | None = None,
    min_similarity: float = 0.75,
    limit: int = 10,
) -> dict:
    """Find near-duplicate / copy-pasted symbols (MinHash + LSH over token shingles).

    With *path* (and optionally *qualname*), returns clones of that symbol.
    Without a path, returns the strongest duplicate pairs project-wide. Purely
    lexical set-similarity — no embeddings, no LLM. Anti-boilerplate floor
    keeps tiny identical stubs from flooding results.

    MinHash + LSH only *retrieve* candidates; the reported ``similarity`` is
    the exact Jaccard of the token-shingle sets, so it can be compared against
    *min_similarity* directly. ``containment`` is the share of the smaller
    symbol found in the larger one — near 1.0 with a lower similarity means one
    body was pasted verbatim into something bigger. Banding adapts to
    *min_similarity*, so lowering it genuinely widens the search.
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return clones(
            conn,
            path,
            qualname=qualname,
            min_similarity=min_similarity,
            limit=limit,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_intent_history(query: str, k_prompts: int = 12, limit: int = 15) -> dict:
    """Which files a request *like this one* historically ended up touching.

    Relevance-by-outcome: finds the nearest historical ``user_prompt`` turns by
    embedding cosine, then tallies the files those sessions touched (weighted by
    prompt similarity x interaction weight). Distinct from ``ken_search_files``
    (content match) — this routes by what past similar work actually did.
    Returns the matched prompts so you see *why* each file was routed.
    """
    with _conn() as conn:
        return intent_history(
            conn, query, k_prompts=k_prompts, limit=limit, project_root=_PROJECT_ROOT
        )


@ken_tool
def ken_grep(
    query: str, mode: str = "literal", language: str | None = None, limit: int = 20
) -> dict:
    """Exact-literal or BM25-ranked search over the live worktree.

    ``mode='literal'`` (default): exact substring match scanned fresh from
    disk, with line-cited snippets — never stale. ``mode='bm25'``: ranked
    relevance via an FTS5 index whose tokenizer preserves identifier
    characters (``_ . -``) so ``MY_ENV_VAR`` and ``os.path`` are findable.
    Optional ``language`` filter (e.g. "python").
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return grep(
            conn,
            query,
            mode=mode,
            language=language,
            limit=limit,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_callgraph(
    qualname: str,
    path: str | None = None,
    direction: str = "both",
    min_confidence: str = "T2",
    limit: int = 50,
) -> dict:
    """Who calls *qualname* and what it calls — precision-tiered call graph.

    Extracts real call-sites from the AST (no token scans) and resolves each
    to a symbol only in confidence tiers: **T1** = same-file or repo-unique
    name; **T2** = name resolves to a single imported file; **T3** = ambiguous,
    reported as an unresolved call-site, never argmax'd into a false edge.
    ``direction`` is callers | callees | both. Works for any tree-sitter
    language ken indexes (Python, JS/TS, Go, Rust, Java, C, Dart, …).
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return callgraph(
            conn,
            qualname,
            path=path,
            direction=direction,
            min_confidence=min_confidence,
            limit=limit,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_wiring(
    query: str | None = None, trigger_kind: str | None = None, limit: int = 50
) -> dict:
    """How features are wired up: routes / CLI / env-var triggers -> handler symbols.

    Extracts decorator/registration nodes (``@app.route``, ``@click.command``)
    and ``os.environ``/``getenv`` reads from the AST, binding each to its
    enclosing symbol by line range. Recognises Flask/NestJS/Spring-style route
    decorators and annotations across languages. Filter by ``trigger_kind``
    (route | cli | env | decorator) or a substring ``query``. Line-cited.
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return wiring(
            conn,
            query=query,
            trigger_kind=trigger_kind,
            limit=limit,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_type_hierarchy(
    qualname: str, direction: str = "sub", with_overrides: bool = True
) -> dict:
    """Subclasses / ancestors of a class, with best-effort override detection.

    Extracts ``class X(Base)`` clauses from the AST and walks the transitive
    closure: ``direction='sub'`` lists descendants, ``'super'`` lists ancestors
    (including unresolved external bases like ``BaseModel``, kept verbatim).
    With ``with_overrides``, flags subclasses that redefine a method name of the
    target class (best-effort — ignores signatures). Works across OO languages
    ken indexes (Python, JS/TS, Java, Dart).
    """
    assert _PROJECT_ROOT is not None
    with _conn() as conn:
        return type_hierarchy(
            conn,
            qualname,
            direction=direction,
            with_overrides=with_overrides,
            project_root=_PROJECT_ROOT,
        )


@ken_tool
def ken_rank(query: str = "", verbose: int = 1, max_chars: int = 0) -> dict:
    """Re-render the context-rank for the current session at a chosen verbosity.

    The default ``<context-rank>`` block injected before each user
    prompt is intentionally terse. Call this when you want more detail:

    * ``verbose=0`` — same compact list-only format as the auto-injected
      block.
    * ``verbose=1`` — top 5 files with a 3-line outline of each and a
      ranked symbols section.
    * ``verbose=2`` — top 8 files with a 12-line outline of each plus
      symbols. Largest payload.

    Set ``max_chars`` to a positive integer to cap the rendered block
    by dropping whole interior lines while preserving valid tags.

    With *query* empty (default), this re-renders the ranker's cached
    output for the most recent prompt — cheap, no recomputation. Pass
    a *query* to run the ranker against that intent without reactive
    session carry-over.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    resp = daemon_client.post(
        _PROJECT_ROOT,
        "/rank",
        {"query": query, "verbose": int(verbose), "max_chars": int(max_chars)},
    )
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp


@ken_tool
def ken_explain_rank(query: str = "") -> dict:
    """Per-channel breakdown of the ranker for a query (or the last prompt).

    Returns each channel's raw output (traceback/explicit / reactive /
    predictive / fuzzy / lexical / findings), the merged pre-boost scores, the per-boost
    score deltas (symbol-file affinity, freshness, co-occurrence, test/import
    affinity, dismissal penalty), and the final
    ordering. Use this when "why didn't file X show up?" or "where did
    that score come from?" matters more than the rendered block.

    *query* defaults to the most recent prompt in the active session.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    resp = daemon_client.post(_PROJECT_ROOT, "/explain", {"query": query})
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp


@ken_tool
def ken_dismiss(target: str, reason: str = "") -> dict:
    """Explicit "this file wasn't what I was looking for" signal.

    Records a ``dismissed`` interaction against the current active
    session — the predictive ranker will treat this target as a negative
    example for similar prompts in future sessions.
    Requires a running daemon with an active hook-backed session.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    health = daemon_client.health(_PROJECT_ROOT)
    if not health or health.get("sessions_active", 0) == 0:
        return {
            "ok": False,
            "error": (
                "no active session — open a coding agent inside the project "
                "and try again"
            ),
        }
    resp = daemon_client.post(
        _PROJECT_ROOT,
        "/interactions/dismiss",
        {"target": target, "reason": reason},
    )
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp
