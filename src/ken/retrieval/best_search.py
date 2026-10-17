"""The shared default search path: prepare source, rank owners, rank requested pieces."""
from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

from ken.retrieval.best_resources import SearchResources, default_resources
from ken.retrieval.candidates import exact_candidates, owner_descriptions, owner_passages, retrieve_contextual
from ken.retrieval.context_preparation import prepare_context
from ken.retrieval.contextual import ContextualRetriever
from ken.retrieval.embedding_store import IndexVersionError, retrieval_snapshot
from ken.retrieval.indexing import index_project
from ken.retrieval.intent import requested_piece_kind
from ken.retrieval.model import SearchRequest, SearchResponse
from ken.retrieval.piece_cards import build_piece_cards
from ken.retrieval.piece_catalog import SourceCatalog, SYMBOL_KINDS
from ken.retrieval.piece_search import PieceSearch, present_cards
from ken.retrieval.presentation import present
from ken.retrieval.profile import active_profile, potion_profile
from ken.retrieval.ranking import rank_candidates
from ken.retrieval.storage import generation, source_extractor_current


@dataclass
class PreparedProject:
    generation: int
    context: ContextualRetriever
    pieces: PieceSearch


_projects: OrderedDict[tuple[str, str, int, str], PreparedProject] = OrderedDict()
_lock = threading.RLock()


def _projection(conn: sqlite3.Connection, root: Path, resources: SearchResources) -> None:
    profile = potion_profile()
    stored = conn.execute("SELECT value FROM meta WHERE key='retrieval_profile_fingerprint'").fetchone()
    if (stored and stored[0] == profile.fingerprint and active_profile(conn) == profile
            and source_extractor_current(conn)):
        return
    files = [Path(r[0]) for r in conn.execute('SELECT path FROM ci_files ORDER BY path')]
    index_project(conn, root, files, profile=profile,
                  encoders={'identity': resources.words, 'behavior': resources.words})


def _prepared(conn: sqlite3.Connection, root: Path, resources: SearchResources) -> PreparedProject:
    database = str(conn.execute('PRAGMA database_list').fetchone()[2])
    key = (str(root.resolve()), database, generation(conn), resources.profile.fingerprint)
    if key in _projects:
        _projects.move_to_end(key)
        return _projects[key]
    catalog = SourceCatalog(root, owner_passages(conn))
    context = prepare_context(catalog, key[2], resources.context, root/'.ken'/'search-context')
    project = PreparedProject(key[2], context, PieceSearch(catalog, resources.piece_ranker, resources.neural))
    _projects[key] = project
    while len(_projects) > 2:
        _projects.popitem(last=False)
    return project


def search_best(conn: sqlite3.Connection, root: Path, request: SearchRequest) -> SearchResponse:
    """Use the complete generic engine by default, retaining cold exact lookups.

    Model preparation happens once; project source snapshots are generation-bound.
    Serial access bounds temporary memory and shares lazy model sessions across
    MCP requests/projects. Explicit legacy search remains a separate public mode.
    """
    root = Path(root).resolve()
    with _lock:
        if not conn.execute('SELECT 1 FROM ci_passages LIMIT 1').fetchone():
            files = [Path(row[0]) for row in conn.execute('SELECT path FROM ci_files ORDER BY path')]
            if files:
                from ken.indexer import index_files
                from ken.retrieval.passages import PassagePolicy
                index_files(conn, root, files, retrieval_policy=PassagePolicy())
        with retrieval_snapshot(conn):
            owners = owner_passages(conn)
            if not owners:
                return SearchResponse(request.query, [], 'best-empty-source-v1')
            exact = exact_candidates(conn, request)
            if len(exact) == 1:
                key = exact[0].entity
                kind = requested_piece_kind(request)
                if request.piece_kind is None and request.target != 'file' and kind == 'symbol' and key.kind == 'class':
                    kind = 'class'
                    request = replace(request, piece_kind=kind)
                matches = rank_candidates(request, exact)
                # Preserve exact enum/struct/interface declarations supported by
                # older lookup; behavioral class eligibility is unchanged.
                if kind == 'symbol' and key.kind not in SYMBOL_KINDS:
                    return present(matches, root, request, profile_version='best-exact-source-v1')
                catalog = SourceCatalog(root, {k: ps for k, ps in owners.items() if k.path == key.path})
                cards = build_piece_cards(matches, kind, request.query, catalog)
                return present_cards(cards, request, catalog, profile_version='best-exact-source-v1')
        resources = default_resources()
        _projection(conn, root, resources)
        with retrieval_snapshot(conn):
            project = _prepared(conn, root, resources)
            candidates, expanded = retrieve_contextual(conn, root, request, resources.profile,
                runtime=project.context, expand_query=resources.owner_ranker.prepare_query,
                encoders={'identity': resources.words, 'behavior': resources.words})
            matches = resources.owner_ranker.rank(request, candidates, owner_descriptions(conn, candidates),
                expanded_query=expanded, evidence_version=3)
            return project.pieces.search(request, matches, expanded_query=expanded,
                profile_version=resources.profile.fingerprint,
                exact=len(candidates)==1 and bool(candidates[0].signals.get('exact')))


def prepare_best(conn: sqlite3.Connection, root: Path) -> dict[str, str | int]:
    """Explicit setup keeps model/index preparation separate from query latency."""
    with _lock:
        files = int(conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0])
        if not files:
            return {'indexed_files': 0, 'owners': 0}
        resources = default_resources()
        _projection(conn, root, resources)
        with retrieval_snapshot(conn):
            project = _prepared(conn, root, resources)
        resources.owner_ranker.prepare_query('¿Dónde convierte un valor?')
        resources.neural.score('find a stored value', ['def get(key): return data[key]']*10)
        return {'indexed_files': files, 'owners': len(project.pieces.catalog.owners),
                'profile_version': resources.profile.fingerprint}
