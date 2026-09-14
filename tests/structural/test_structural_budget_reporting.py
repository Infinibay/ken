"""A rule that exhausted its budget must not look like a rule that found nothing.

Measured on a real 684-file Python package: with the fixture-sized defaults, 12 of
the 23 GoF roots exhausted ``max_states`` and reported zero matches. The result
already carried ``complete: false`` and the reason, but only inside the per-rule
``outcomes``, so a caller reading ``findings`` saw an empty list. ``incomplete``
names those rules at the top level, and the CLI also warns on stderr.
"""
import argparse
import json

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
