"""Name tokenisation, shared by the indexer that stores tokens and the ranker
that queries them.

This used to live inside `ranker/channels.py` and run only at query time: every
`ken rank` tokenised every file path and every symbol name in Python before
intersecting with the prompt. On a 771 563-symbol index that measured **11.3 s of
the 22.6 s** the lexical channel cost — 77% of it, against 3.3 s of actual SQL.

The work moves to index time, into `ci_name_tokens`. That is only sound because
the lexical score depends on **how many** query tokens a row matches and never on
the row's full token set — no Jaccard denominator, no length normalisation — so a
posting list reproduces the old score exactly rather than approximating it.

Living in its own module is the point: if indexing and querying could drift apart
on what a token is, the index would answer a subtly different question than the
one asked, and nothing would fail loudly. :data:`NAME_TOKEN_VERSION` is the other
half of that guarantee — bump it whenever the stopwords, the aliases or the split
regex change, and every project rebuilds instead of serving stale postings.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Bump on any change to _WORD_RE, _split_camel, _STOPWORDS or _TOKEN_ALIASES.
#: Stored per project in ``meta.name_token_version``; a mismatch makes the ranker
#: fall back to tokenising on the fly until the index is rebuilt, so a bump
#: degrades speed and never correctness.
NAME_TOKEN_VERSION = 1

#: ``ci_name_tokens.kind`` — which table ``row_id`` points into.
KIND_FILE = 0
KIND_SYMBOL = 1

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")

_STOPWORDS = frozenset(
    "the and for with from into this that what where when why how fix bug error "
    "traceback file line test tests code src function class method module "
    "este esta esto ese esa eso con para que por los las una uno momento ahora "
    "sigue seguir continua continuar continuemos seguimos path foco extra cual "
    "quien donde cuando como clase codigo código fichero archivo funcion función".split()
)

_TOKEN_ALIASES = {
    "class": {"class"},
    "code": {"code"},
    "file": {"file"},
    "scheduler": {"sched"},
    "scheduling": {"sched"},
    "parsear": {"parse", "parser", "parsers", "parsed"},
    "parsea": {"parse", "parser", "parsers", "parsed"},
    "parseo": {"parse", "parser", "parsers", "parsed"},
    "parse": {"parser", "parsers", "parsed"},
    "parser": {"parse", "parsers", "parsed"},
    "parsing": {"parse", "parser", "parsers", "parsed"},
    "archivo": {"file", "source"},
    "fichero": {"file", "source"},
    "codigo": {"code", "source"},
    "código": {"code", "source"},
    "clase": {"class"},
}


def split_camel(text: str) -> list[str]:
    return _CAMEL_RE.findall(text)


def name_tokens(text: str, *, extra_stopwords: set[str] | None = None) -> set[str]:
    """The token set of a name, path or prompt.

    Aliases expand *both* sides — a stored `scheduler` carries `sched`, so a
    prompt saying `sched` still matches it. That symmetry is why the postings
    have to be built with this exact function.
    """
    parts: set[str] = set()
    for raw in _WORD_RE.findall(text.replace("-", "_").replace(".", "_").replace("/", "_")):
        for piece in raw.split("_"):
            parts.update(split_camel(piece))
    raw_tokens = {p.lower() for p in parts if len(p) >= 3}
    stopwords = _STOPWORDS if not extra_stopwords else _STOPWORDS | extra_stopwords
    tokens = {p for p in raw_tokens if p not in stopwords}
    for token in raw_tokens:
        tokens.update(_TOKEN_ALIASES.get(token, set()))
    return tokens


def project_stopwords(project_root: Path | None) -> set[str]:
    """Tokens from the project's own name, which appear in nearly every path.

    Derived from `project_root.name` alone, so it is invariant for the life of a
    project — which is what makes it safe to bake into the stored postings rather
    than recompute per query.
    """
    if project_root is None:
        return set()
    tokens = name_tokens(project_root.name)
    return {token for token in tokens if len(token) >= 3}


def file_tokens(path: str, *, extra_stopwords: set[str] | None = None) -> set[str]:
    return name_tokens(path, extra_stopwords=extra_stopwords)


def symbol_tokens(
    kind: str, qualname: str | None, name: str, *, extra_stopwords: set[str] | None = None
) -> set[str]:
    return name_tokens(
        f"{kind} {qualname or ''} {name}", extra_stopwords=extra_stopwords
    )
