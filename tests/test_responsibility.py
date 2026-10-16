"""Who owns this operation? Test the public contract against changing code."""

from hashlib import blake2b
import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from ken.cli import main
from ken.db import connect, init_schema
from ken.indexer import index_files
from ken.mcp import server
from ken.responsibility.model import Evidence
from ken.responsibility.reasoners import confidence, terms
from ken.responsibility.service import who


class LexicalEmbedder:
    """Deterministic vectors; ranking-quality experiments use the real model."""

    dim = 256

    def embed_query(self, text):
        vector = np.zeros(self.dim, dtype=np.float32)
        for word in terms(text):
            slot = (
                int.from_bytes(blake2b(word.encode(), digest_size=2).digest(), "big")
                % self.dim
            )
            vector[slot] += 1
        return vector / (np.linalg.norm(vector) + 1e-12)

    def embed_passages(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_queries(self, texts):
        return self.embed_passages(texts)


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / ".ken").mkdir()
    (tmp_path / ".ken/meta.json").write_text("{}")
    conn = connect(tmp_path / ".ken/ken.db")
    init_schema(conn)
    embedder = LexicalEmbedder()
    monkeypatch.setattr("ken.responsibility.service.get_embedder", lambda: embedder)
    monkeypatch.setattr(
        "ken.responsibility.service.configure_for_project", lambda conn: None
    )
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)

    def add(path, text):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        index_files(conn, tmp_path, [Path(path)], embedder=embedder)

    yield tmp_path, conn, add
    conn.close()


def test_cli_and_mcp_find_documented_responsibility_with_evidence(project, capsys):
    root, conn, add = project
    add(
        "store.py", 'def perform():\n    """Store reusable findings."""\n    return 1\n'
    )
    add("other.py", 'def paint():\n    """Render green pixels."""\n    return 2\n')
    result = server.ken_who("Who stores reusable findings?", full=True)
    first = result["candidates"][0]
    assert first["symbol"] == "perform"
    assert first["documentation"] == "Store reusable findings."
    assert first["source"]["behavior_verified"] is False
    assert first["confidence"]["probability"] is None
    assert first["assumptions"]
    assert (
        main(
            [
                "tools", "--json",
                "--path",
                str(root),
                "who",
                "Who stores reusable findings?",
                "--full",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == result


def test_proposed_translation_is_explicit_and_cli_list_reaches_tool(project, capsys):
    root, conn, add = project
    add("store.py", 'def perform():\n    """Store reusable findings."""\n    pass\n')
    assert (
        main(
            [
                "tools", "--json",
                "--path",
                str(root),
                "who",
                "¿Quién recuerda aprendizajes?",
                "--full",
                "--hypotheses",
                "Store reusable findings",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    first = result["candidates"][0]
    assert first["matched_formulation"] == "Store reusable findings"
    assert "supplied formulation" in first["assumptions"][0]


def test_equal_documentation_retains_ambiguity_even_with_limit_one(project):
    root, conn, add = project
    add("a.py", 'def first():\n    """Store findings."""\n    pass\n')
    add("b.py", 'def second():\n    """Store findings."""\n    pass\n')
    result = who(conn, root, "Store findings", limit=1)
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 1


def test_denial_is_counterevidence_not_high_confidence_support(project):
    root, conn, add = project
    add(
        "a.py",
        'def store_findings():\n    """Does not store findings. This is a compatibility stub."""\n    pass\n',
    )
    result = who(conn, root, "Who stores findings?")
    assert result["status"] == "unknown"
    assert not result["candidates"]
    assert result["counterevidence"][0]["confidence"]["score"] <= 0.2
    assert any(
        e["direction"] == "against" for e in result["counterevidence"][0]["evidence"]
    )


def test_hypothesis_cannot_bypass_denial_under_another_formulation(project):
    root, conn, add = project
    add(
        "a.py",
        'def store_findings():\n    """Does not store findings. Persist reusable memories."""\n    pass\n',
    )
    result = who(conn, root, "Store findings", hypotheses=["Persist reusable memories"])
    assert not result["candidates"]
    assert result["counterevidence"]


def test_delegation_and_calls_are_context_not_independent_votes(project):
    root, conn, add = project
    add(
        "store.py",
        'def dispatch():\n    """Delegate storage of findings to another component."""\n    return store_findings()\n',
    )
    result = who(conn, root, "storage findings", hypotheses=["store findings"])
    first = result["candidates"][0]
    assert first["confidence"]["score"] <= 0.55
    assert {e["reasoner"] for e in first["evidence"]} >= {
        "documentation",
        "calls",
        "delegation",
    }
    assert any("unresolved" in a for a in first["assumptions"])


def test_conditional_documentation_keeps_its_assumption(project):
    root, conn, add = project
    add(
        "store.py",
        'def perform():\n    """May store findings if persistence is enabled."""\n    pass\n',
    )
    first = who(conn, root, "Store findings")["candidates"][0]
    assert first["confidence"]["score"] <= 0.55
    assert any("condition" in a for a in first["assumptions"])


def test_changed_documentation_is_read_live_and_old_quote_is_never_reused(project):
    root, conn, add = project
    add("store.py", 'def perform():\n    """Store findings."""\n    pass\n')
    (root / "store.py").write_text(
        '\n\n\ndef perform():\n    """Does not store findings."""\n    pass\n'
    )
    result = who(conn, root, "Store findings")
    first = result["counterevidence"][0]
    assert first["documentation"] == "Does not store findings."
    assert first["line"] == 4
    assert first["source"]["index_changed"] is True


@pytest.mark.parametrize("change", ["removed", "syntax", "missing", "outside_symlink"])
def test_unverifiable_sources_cannot_provide_positive_evidence(
    project, tmp_path, change
):
    root, conn, add = project
    add("store.py", 'def perform():\n    """Store findings."""\n    pass\n')
    file = root / "store.py"
    if change == "removed":
        file.write_text("x = 1\n")
    elif change == "syntax":
        file.write_text("def broken(\n")
    else:
        file.unlink()
        if change == "outside_symlink":
            file.symlink_to(root.parent / "outside.py")
    result = who(conn, root, "Store findings")
    assert result["status"] == "unknown"
    assert result["coverage"]["issues"]


def test_scope_precedes_ranking_and_tests_are_opt_in(project):
    root, conn, add = project
    add("src/a.py", 'def save():\n    """Store findings."""\n    pass\n')
    add("tests/test_a.py", 'def test_save():\n    """Store findings."""\n    pass\n')
    result = who(conn, root, "Store findings", path="src")
    assert result["coverage"]["indexed_symbols"] == 1
    assert all(c["path"].startswith("src/") for c in result["candidates"])
    assert who(conn, root, "Store findings")["coverage"]["indexed_symbols"] == 1
    assert (
        who(conn, root, "Store findings", include_tests=True)["coverage"][
            "indexed_symbols"
        ]
        == 2
    )


def test_full_python_docstring_and_method_owner_are_preserved(project):
    root, conn, add = project
    add(
        "store.py",
        'class Store:\n    def perform(self):\n        """Public entry point.\n\n        Store reusable findings.\n        """\n        pass\n',
    )
    first = who(conn, root, "Store reusable findings")["candidates"][0]
    assert first["symbol"] == "Store.perform"
    assert "Store reusable findings" in first["documentation"]
    assert first["source"]["documentation_scope"] == "full"


def test_unknown_is_not_an_absence_proof(project):
    root, conn, add = project
    result = who(conn, root, "quux xyzzy")
    assert result["status"] == "unknown"
    assert result["coverage"]["exhaustive"] is False
    assert result["assessment"]["probability"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"question": ""},
        {"question": "a", "limit": 0},
        {"question": "a", "path": ".."},
        {"question": "a", "hypotheses": ["a"] * 4},
    ],
)
def test_invalid_contract_is_rejected(project, kwargs):
    root, conn, add = project
    with pytest.raises(ValueError):
        who(conn, root, **kwargs)


def test_correlated_or_repeated_evidence_does_not_multiply_confidence():
    doc = Evidence("documentation", "supports", 0.6, "a")
    name = Evidence("name", "supports", 0.5, "b")
    calls = Evidence("calls", "context", 1.0, "c")
    assert confidence((doc, name)) == confidence((doc, name, doc, name, calls))


def test_new_reasoner_can_add_counterevidence_without_changing_orchestration(project):
    root, conn, add = project
    add("store.py", 'def perform():\n    """Store findings."""\n    pass\n')
    from ken.responsibility.service import DEFAULT_REASONERS

    class Constraint:
        def assess(self, inquiry, symbol):
            return (
                Evidence(
                    "deployment_constraint",
                    "against",
                    1.0,
                    "The required backend is unavailable.",
                ),
            )

    result = who(
        conn, root, "Store findings", reasoners=(*DEFAULT_REASONERS, Constraint())
    )
    assert result["counterevidence"]
    assert result["status"] == "unknown"


def test_new_support_provider_has_conservative_weight_and_cannot_count_twice():
    support = Evidence(
        "structural_contract",
        "supports",
        0.9,
        "Candidate effect under stated assumptions.",
    )
    assert confidence((support,))["score"] == 0.45
    assert confidence((support, support)) == confidence((support,))


def test_nested_function_calls_are_not_attributed_to_outer_symbol(project):
    root, conn, add = project
    add(
        "store.py",
        'def outer():\n    """Store findings."""\n    def deferred():\n        return store_findings()\n    return deferred\n',
    )
    first = who(conn, root, "Store findings")["candidates"][0]
    assert not any(e["reasoner"] == "calls" for e in first["evidence"])


def test_sdk_and_cli_publish_the_same_who_contract():
    sdk_tools = asyncio.run(server.mcp.list_tools())
    sdk = next(t for t in sdk_tools if t.name == "ken_who")
    cli = next(t for t in server.list_tools() if t.name == "ken_who")
    assert sdk.input_schema["required"] == cli.parameters["required"] == ["question"]
    assert sdk.input_schema["properties"]["limit"]["default"] == 3
    assert cli.parameters["properties"]["hypotheses"]["items"] == {"type": "string"}
    assert sdk.input_schema["properties"]["full"]["default"] is False
    assert cli.parameters["properties"]["full"] == {"type": "boolean", "default": False}


@pytest.mark.parametrize(
    "kind,source,expected",
    [
        ("module", '"""Normalize Unicode filenames."""\nVERSION = 1\n', "component.py"),
        (
            "class",
            'class Component:\n    """Normalize Unicode filenames."""\n    pass\n',
            "Component",
        ),
        (
            "method",
            'class Component:\n    def apply(self):\n        """Normalize Unicode filenames."""\n        pass\n',
            "Component.apply",
        ),
        (
            "function",
            'def apply():\n    """Normalize Unicode filenames."""\n    pass\n',
            "apply",
        ),
    ],
)
def test_each_documentation_owner_is_found_without_using_findings(
    project, capsys, kind, source, expected
):
    root, conn, add = project
    add("component.py", source)
    # A matching saved note must not influence this code-documentation query.
    conn.execute(
        "INSERT INTO cr_findings(topic,content,created_at,updated_at) VALUES (?,?,0,0)",
        ("Normalize Unicode filenames", "ImaginaryService does this in nonexistent.py"),
    )
    result = server.ken_who("Who normalizes Unicode filenames?", full=True)
    first = result["candidates"][0]
    assert (first["kind"], first["symbol"]) == (kind, expected)
    assert first["source"]["documentation_kind"] == kind + "_docstring"
    assert result["coverage"]["findings_used"] is False
    assert (
        main(
            [
                "tools", "--json",
                "--path",
                str(root),
                "who",
                "Who normalizes Unicode filenames?",
                "--full",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == result
    inspect = dict(first["inspect"])
    assert inspect.pop("tool") == "ken_read"
    source = server.ken_read(**inspect)["source"]["snippets"][0]["code"]
    assert "Normalize Unicode filenames" in source


def test_module_and_class_documentation_are_not_attributed_to_undocumented_methods(
    project,
):
    root, conn, add = project
    add(
        "component.py",
        '"""Normalize Unicode filenames."""\nclass Component:\n    """Encrypt customer archives."""\n    def apply(self):\n        pass\n',
    )
    result = who(conn, root, "Normalize Unicode filenames")
    assert result["candidates"][0]["kind"] == "module"
    assert not any(c["symbol"] == "Component.apply" for c in result["candidates"])
    result = who(conn, root, "Encrypt customer archives")
    assert result["candidates"][0]["kind"] == "class"


@pytest.mark.parametrize(
    "new_doc", ["", '"""Does not normalize Unicode filenames."""\n']
)
def test_changed_module_docs_never_reuse_old_claims(project, new_doc):
    root, conn, add = project
    add("component.py", '"""Normalize Unicode filenames."""\nVERSION = 1\n')
    (root / "component.py").write_text(new_doc + "VERSION = 2\n")
    result = who(conn, root, "Normalize Unicode filenames")
    assert result["status"] == "unknown"
    if new_doc:
        assert result["counterevidence"][0]["source"]["index_changed"]
    else:
        assert result["coverage"]["issues"]


def test_module_path_cannot_collide_with_qualified_method_name(project):
    root, conn, add = project
    add(
        "foo.py",
        '"""Normalize Unicode filenames."""\nclass foo:\n    def py(self):\n        """Encrypt customer archives."""\n        pass\n',
    )
    result = who(conn, root, "Normalize Unicode filenames")
    assert (result["candidates"][0]["kind"], result["candidates"][0]["symbol"]) == (
        "module",
        "foo.py",
    )
    result = who(conn, root, "Encrypt customer archives")
    assert (result["candidates"][0]["kind"], result["candidates"][0]["symbol"]) == (
        "method",
        "foo.py",
    )


def test_default_is_compact_and_full_preserves_diagnostic_contract(project, capsys):
    root, conn, add = project
    add(
        "component.py",
        '"""Public API.\n\nNormalize Unicode filenames.\n"""\nVERSION = 1\n',
    )
    question = "Who normalizes Unicode filenames?"
    compact = server.ken_who(question)
    detailed = server.ken_who(question, full=True)
    assert detailed == who(conn, root, question)
    first = compact["candidates"][0]
    assert (first["kind"], first["path"], first["line"]) == (
        "module",
        "component.py",
        1,
    )
    assert first["score"] == detailed["candidates"][0]["confidence"]["score"]
    assert first["evidence"] == "Normalize Unicode filenames."
    assert compact["score_kind"] == "heuristic_not_probability"
    assert (
        not {"coverage", "assessment", "question", "counterevidence"} & compact.keys()
    )
    assert (
        not {"symbol", "source", "assumptions", "inspect", "confidence"} & first.keys()
    )
    assert len(json.dumps(compact)) < len(json.dumps(detailed)) / 2
    for flags, expected in [([], compact), (["--full"], detailed)]:
        assert main(["tools", "--json", "--path", str(root), "who", question, *flags]) == 0
        assert json.loads(capsys.readouterr().out) == expected


def test_compact_keeps_ambiguity_and_explicit_formulation_assumption(project):
    root, conn, add = project
    for path in ("a.py", "b.py"):
        add(path, 'def apply():\n    """Normalize Unicode filenames."""\n    pass\n')
    result = server.ken_who(
        "¿Quién normaliza los nombres?",
        hypotheses=["Normalize Unicode filenames"],
        limit=1,
    )
    assert result["status"] == "ambiguous"
    assert (
        result["candidates"][0]["assumed_formulation"] == "Normalize Unicode filenames"
    )


@pytest.mark.parametrize(
    "documentation,caveat",
    [
        (
            "May normalize Unicode filenames if normalization is enabled.",
            "Conditional documentation",
        ),
        (
            "Delegate normalization of Unicode filenames to another component.",
            "delegation",
        ),
        ("Does not normalize Unicode filenames.", "Possible explicit denial"),
    ],
)
def test_compact_keeps_conditions_delegation_and_counterevidence(
    project, documentation, caveat
):
    root, conn, add = project
    add("component.py", f'def apply():\n    """{documentation}"""\n    pass\n')
    result = server.ken_who("Normalize Unicode filenames")
    entries = result.get("counterevidence") or result["candidates"]
    assert any(caveat in message for message in entries[0]["caveats"])
    if "not normalize" in documentation:
        assert result["status"] == "unknown"
        assert "not proof of absence" in result["reason"]


def test_compact_reports_unavailable_source_without_dumping_diagnostics(project):
    root, conn, add = project
    add(
        "component.py",
        'def apply():\n    """Normalize Unicode filenames."""\n    pass\n',
    )
    (root / "component.py").unlink()
    result = server.ken_who("Normalize Unicode filenames")
    assert result["status"] == "unknown"
    assert result["uninspected_candidates"] == 1
    assert "coverage" not in result


def test_who_default_gives_numbered_implementation_without_another_read(project):
    root, conn, add = project
    add('reader.py', 'def read_setting(key):\n    """Read stored application settings."""\n    return values[key]\n')
    tool = next(t for t in server.list_tools() if t.name == 'ken_who')
    result = server.ken_who('Who reads stored application settings?', verify=False)
    first = result['candidates'][0]
    assert first['snippets'] == [{'start_line': 1, 'end_line': 3,
        'content': 'def read_setting(key):\n    """Read stored application settings."""\n    return values[key]'}]
    text = tool.fn('Who reads stored application settings?', verify=False)
    assert 'reader.py:1-3 :: read_setting' in text
    assert '3 |     return values[key]' in text
    assert 'score_kind' not in text and 'heuristic_not_probability' not in text


def test_who_large_class_shows_relevant_method_instead_of_only_long_docstring(project):
    root, conn, add = project
    source = ('class Reader:\n    """Read stored application settings.\n' +
              '    General public API documentation.\n' * 25 + '    """\n' +
              ''.join(f'    def unrelated_{i}(self):\n        return {i}\n' for i in range(20)) +
              '    def read_setting(self, key):\n        return settings.get_value(key)\n')
    add('reader.py', source)
    result = who(conn, root, 'Who reads stored application settings?')
    first = result['candidates'][0]
    assert first['symbol'] == 'Reader'
    snippets = first['snippets']
    shown = '\n'.join(s['content'] for s in snippets)
    assert 'class Reader:' in shown and 'return settings.get_value(key)' in shown
    assert sum(s['end_line'] - s['start_line'] + 1 for s in snippets) <= 16
    assert first['truncated'] is True
    lines = source.splitlines()
    for s in snippets:
        assert s['content'] == '\n'.join(lines[s['start_line']-1:s['end_line']])


def test_who_code_quotes_current_snapshot_even_when_index_is_stale(project):
    root, conn, add = project
    add('reader.py', 'def read_setting(key):\n    """Read stored settings."""\n    return 11\n')
    (root / 'reader.py').write_text('def read_setting(key):\n    """Read stored settings."""\n    return 99\n')
    first = who(conn, root, 'Who reads stored settings?')['candidates'][0]
    assert first['source']['index_changed'] is True
    shown = '\n'.join(s['content'] for s in first['snippets'])
    assert 'return 99' in shown and 'return 11' not in shown


def test_who_counterevidence_also_carries_code_for_independent_inspection(project):
    root, conn, add = project
    add('reader.py', 'def read_setting(key):\n    """Does not read stored settings."""\n    raise NotImplementedError(key)\n')
    tool = next(t for t in server.list_tools() if t.name == 'ken_who')
    text = tool.fn('Who reads stored settings?', verify=False)
    assert 'NotImplementedError(key)' in text and 'counterevidence' in text.lower()
    assert 'not proof of absence' in text



def test_who_preview_honors_python_source_encoding(project):
    root, conn, add = project
    source = '# coding: latin-1\ndef read_setting():\n    """Read stored settings."""\n    return "café"\n'
    add('reader.py', source)
    (root / 'reader.py').write_bytes(source.encode('latin-1'))
    first = who(conn, root, 'Who reads stored settings?')['candidates'][0]
    assert 'return "café"' in '\n'.join(s['content'] for s in first['snippets'])
    assert first['source']['index_changed'] is True


def test_who_preview_skips_oversized_lines_without_cutting_source_or_losing_return(project):
    root, conn, add = project
    source = ('def read_setting(key):\n    """Read stored settings."""\n' +
              '    values = {"data": "' + 'x' * 10000 + '"}\n    return values[key]\n')
    add('reader.py', source)
    first = who(conn, root, 'Who reads stored settings?')['candidates'][0]
    snippets = first['snippets']
    assert sum(len(s['content']) + 1 for s in snippets) <= 4000
    assert any('return values[key]' in s['content'] for s in snippets)
    assert first['truncated'] is True
    lines = source.splitlines()
    for s in snippets:
        assert s['content'] == '\n'.join(lines[s['start_line']-1:s['end_line']])



def test_source_preview_failure_never_changes_candidate_scores_or_order(project, monkeypatch):
    from ken.responsibility.source import SourceReader
    root, conn, add = project
    add('a.py', 'def read_setting():\n    """Read stored settings."""\n    return 1\n')
    add('b.py', 'def another_reader():\n    """Read stored settings."""\n    return 2\n')
    with_code = who(conn, root, 'Who reads stored settings?')
    def unavailable(self, candidate):
        raise ValueError('Preview unavailable; read this symbol directly.')
    monkeypatch.setattr(SourceReader, 'preview', unavailable)
    without_code = who(conn, root, 'Who reads stored settings?')
    identity_and_score = lambda result: [(c['path'], c['symbol'], c['confidence']) for c in result['candidates']]
    assert identity_and_score(without_code) == identity_and_score(with_code)
    assert all('Preview unavailable' in c['preview_unavailable'] for c in without_code['candidates'])
