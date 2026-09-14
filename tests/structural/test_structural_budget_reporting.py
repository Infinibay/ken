"""A rule that exhausted its budget must not look like a rule that found nothing.

Measured on a real 684-file Python package: with the fixture-sized defaults, 12 of
the 23 GoF roots exhausted ``max_states`` and reported zero matches. The result
already carried ``complete: false`` and the reason, but only inside the per-rule
``outcomes``, so a caller reading ``findings`` saw an empty list. ``incomplete``
names those rules at the top level, and the CLI also warns on stderr.
"""
import argparse
import json

import pytest

from ken.structural.catalog import detect_patterns
from ken.structural.cli import add_parser, dispatch
from ken.structural.frontend import lower_source
from ken.structural.model import FactIndex
from ken.structural.query import QueryBudget
from ken.structural.semantic import link_project

SOURCE = 'class Factory:\n    def make(self):\n        return Product()\n\n\nclass Product:\n    pass\n'


def graph():
    return link_project([lower_source(SOURCE, 'python', 'factory.py')])


def test_a_starved_rule_is_named_with_its_reason():
    result = detect_patterns(FactIndex(graph()), ['factory-method'],
                             QueryBudget(max_states=1, max_rows=1))
    assert result['complete'] is False
    assert list(result['incomplete']) == ['factory-method']
    assert 'budget:max_states' in result['incomplete']['factory-method']


def test_a_rule_with_room_is_not_reported_incomplete():
    result = detect_patterns(FactIndex(graph()), ['factory-method'],
                             QueryBudget(max_states=200_000, max_rows=200_000))
    assert result['complete'] is True
    assert result['incomplete'] == {}


def test_the_default_budget_is_no_ceiling_at_all():
    """A default budget must not truncate: no limit is the absence of a limit.

    Modelling "unlimited" as a large integer would still truncate the first query
    that outgrew it and report it as a partial search, which is the failure mode
    the ceilings were meant to prevent.
    """
    budget = QueryBudget()
    assert (budget.max_rows, budget.max_states, budget.max_matches, budget.timeout_ms) == (None,) * 4
    # A rule with more candidate rows and states than any fixture-sized ceiling
    # still completes, and the CLI lets the caller impose a ceiling instead.
    index = FactIndex(graph())
    result = detect_patterns(index, ['factory-method'])
    assert result['complete'] is True
    assert result['incomplete'] == {}


@pytest.mark.parametrize('field', ['max_rows', 'max_states', 'max_matches', 'timeout_ms'])
def test_a_zero_or_negative_ceiling_is_rejected_not_read_as_unlimited(field):
    with pytest.raises(ValueError, match=field):
        QueryBudget(**{field: 0})
    with pytest.raises(ValueError, match=field):
        QueryBudget(**{field: -1})


def test_the_cli_defaults_to_no_ceiling(tmp_path, capsys):
    (tmp_path / 'factory.py').write_text(SOURCE, encoding='utf-8')
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='cmd')
    add_parser(commands)
    args = parser.parse_args(['structural', 'patterns', '--path', str(tmp_path), '--cache-mb', '0'])
    assert (args.limit, args.timeout_ms, args.max_states, args.max_rows) == (None,) * 4
    assert dispatch(args) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)['complete'] is True
    assert captured.err == ''


def test_the_cli_exposes_the_budgets_and_warns_on_stderr(tmp_path, capsys):
    (tmp_path / 'factory.py').write_text(SOURCE, encoding='utf-8')
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='cmd')
    add_parser(commands)
    args = parser.parse_args(['structural', 'patterns', '--path', str(tmp_path), '--cache-mb', '0',
                              '--pattern', 'factory-method', '--max-states', '1', '--max-rows', '1'])
    assert dispatch(args) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload['incomplete'] == {'factory-method': ['budget:max_states']}
    assert 'incomplete' in captured.err and 'factory-method' in captured.err
