from dataclasses import FrozenInstanceError
from pathlib import Path
import re

import pytest

from ken.kql2 import ParseError, parse
from ken.kql2.syntax import Expr, SourceExpr

HEADER = 'language "kql/2"; module tests.syntax; '


def pattern(body):
    return parse(HEADER + 'pattern Test(out Callable $f) {' + body + '}')


def query(body):
    return parse(HEADER + 'query test {' + body + '}')


@pytest.mark.parametrize('body', [
    'class $c { field $f { type: map<string,list<integer>>; } }',
    'class $c { field $f { type: function<(integer,string)->boolean>; } }',
    'class $c { fields exact { field $f {} } method $m { parameters exact { param $x {} receiver $r {} } } }',
    'either { var $v { type: string; } } or { var $v { type_status: unknown; } }',
    'not exists { callable $c {} } optional { callable $e {} }',
    'body { var $x {} adjacent; $x = 1; }',
    'body adjacent { let $x = $a + $b * 2; return $x; }',
    'body { let $x = call $f { argument $v at 0; argument $w at name("key") as $a; }; return $x; }',
    'body { call $f { argument_pack $p { kind: variadic; } argument $x at any; } as $c; }',
    'body { let $v = $x++; $items[$i].value += $v; }',
    'body { if ($x > 1) { return $x; } else if ($x == 1) { throw $x; } else { return; } }',
    'body { while ($x < 10) { $x += 1; continue; break; } }',
    'body { for $x in $items { yield $x; } yield from $items; await $t; }',
    'body { for { init { let $x = 0; } condition $x < 10; step { $x += 1; } body { continue; } } }',
    'body { try { call $f {}; } catch $e when ($e == $x) { throw $e; } else { return; } finally { return; } }',
    'body { try {} finally {} }',
    'body { gap until next { paths: all; forbid writes($x); preserve value($x); } return $x; }',
    'restriction between $a.after_normal and $b.before { forbid calls($f); }',
    'body { fragment $logic { call $f {}; } } exposes $logic;',
    'body { iterate $items as $item into $output as $iteration { forms: [map,filter]; body { yield $item; } } }',
    'body { spawn $f as $t; join $t; acquire $l; release $l; send $v to $channel; receive $channel as $r; }',
    'body { let $x = new $type($arg); let $y = $x << 2; let $z = $y >> 1; }',
    'syntax { statement $s { native_kind: "if_statement"; } }',
])
def test_syntax_families(body):
    assert pattern(body).declarations[0].clauses


def test_documented_complete_programs():
    count = 0
    for path in Path('docs/design/kql2').glob('*.md'):
        for block in re.findall(r'```kql2\n(.*?)```', path.read_text(), re.S):
            stripped = block.lstrip()
            if stripped.startswith("language "):
                parse(block, str(path))
                count += 1
            elif re.match(r"(?:pattern|predicate|signature|model|enum|query)\s", stripped):
                parse(HEADER + block, str(path))
                count += 1
    assert count >= 6


def test_models_predicates_and_recursion_syntax():
    program = parse(HEADER + '''
      enum State { fresh, used, closed }
      signature Flow { predicate step(Value $a, Value $b); }
      model User implements Flow { predicate step(Value $a, Value $b) { edge($a, $b) } }
      predicate Reach(Value $a, Value $b) { edge($a,$b) or exists(Value $m | edge($a,$m) and Reach($m,$b)) }
      pattern Walk<M: Flow>(in Value $a, out Value $b) { where M.step($a,$b); }
      query reach { from Value $a; use Walk<User>(a: $a,b: $b); select $a,$b; }
    ''')
    assert len(program.declarations) == 6


def test_query_precedence_and_aggregate():
    tree = query('from Callable $f; bind $n = count(Callable $c | calls($f,$c) | $c); where $n + 2 * 3 >= 8 and $n != 0; select $n; order by $n desc; limit 10;')
    expr = tree.declarations[0].clauses[2].expressions[0]
    assert expr.value == 'and'
    assert expr.args[0].args[0].value == '+'
    assert expr.args[0].args[0].args[1].value == '*'


def test_source_and_query_expression_types_are_separate():
    tree = pattern('bind $n = 2; body { let $x = -$y ** 2; }')
    bind, body = tree.declarations[0].clauses
    assert isinstance(bind.expressions[0], Expr)
    expr = body.blocks[0][0].expressions[0]
    assert isinstance(expr, SourceExpr)
    assert expr.kind == 'unary'
    assert expr.args[0].value == '**'


def test_utf8_spans_and_immutable_tree():
    source = HEADER + 'query q { class $x { name: "aé🙂"; } select $x; }'
    tree = parse(source, 'unicode.kql')
    selector = tree.declarations[0].clauses[0]
    assert source.encode()[selector.span.start:selector.span.end].decode() == 'class $x { name: "aé🙂"; }'
    assert tree.span.end == len(source.encode())
    with pytest.raises(FrozenInstanceError):
        tree.module = 'changed'


@pytest.mark.parametrize('regex', ['/foo/i', r'/a\/b/', '/[/]/', '/(?:a|b)+/ims', '/a{2,5}/'])
def test_regex(regex):
    assert pattern(f'class $x {{ name: {regex}; }}')


@pytest.mark.parametrize('regex', [r'/(a)\1/', '/(?=a)/', '/(?P<n>a)/', '/a/ii', '/a/g', '/[a/', '/'+'a'*4097+'/'])
def test_invalid_regex(regex):
    with pytest.raises(ParseError):
        pattern(f'class $x {{ name: {regex}; }}')


def test_division_and_comments():
    tree = query('/* c */ bind $x = 8 / 2; // line\n select $x;')
    assert tree.declarations[0].clauses[0].expressions[0].value == '/'


@pytest.mark.parametrize('source', [
    'query q { select 1; }',
    'language "kenql/1"; module test;',
    HEADER + 'query q { from Callable $x; }',
    HEADER + 'query q { select 1; where true; }',
    HEADER + 'query q { select 1; select 2; }',
    HEADER + 'query q { body {} select 1; }',
    HEADER + 'query q { use X($x); select 1; }',
    HEADER + 'query q { where 1 < 2 < 3; select 1; }',
    HEADER + 'query q { bind $x = "\\q"; select 1; }',
    HEADER + 'query q { bind $x = "\\ud800"; select 1; }',
    HEADER + 'pattern P() { body { try {} } }',
    HEADER + 'pattern P() { body { try {} else {} finally {} } }',
    HEADER + 'pattern P() { body { nonsense; } }',
    HEADER + 'pattern P() { body { var $x {} NOOP $x = 1; } }',
    HEADER + 'query class { select 1; }',
    HEADER + '/* unterminated',
])
def test_reject_invalid_syntax(source):
    with pytest.raises(ParseError):
        parse(source)


def test_resource_limits_are_diagnostics():
    with pytest.raises(ParseError, match='limit'):
        parse(HEADER, max_bytes=4)
    with pytest.raises(ParseError, match='limit'):
        query('select ' + '(' * 200 + '1' + ')' * 200 + ';')


def test_all_input_consumed():
    with pytest.raises(ParseError):
        parse(HEADER + 'query q { select 1; } trailing')


def test_mutated_inputs_have_bounded_diagnostics():
    import random
    rng=random.Random(7042)
    source=HEADER + 'query q { class $c { name: /Worker/i; } when $c.language in ["python"] { callable $m {} } else { callable $m {} } select $c,$m; }'
    for _ in range(300):
        start=rng.randrange(len(source))
        end=rng.randrange(start,len(source)+1)
        mutated=source[:start] + rng.choice(['', '$', '}', '/*', '"', '🙂']) + source[end:]
        try:
            parse(mutated,max_depth=32)
        except ParseError:
            pass


def test_overflowing_regex_is_a_parse_diagnostic():
    with pytest.raises(ParseError):
        pattern('class $c { name: /a{9999999999999999999999999999}/; }')


def test_bare_and_scoped_break_preserve_distinct_syntax():
    tree = parse('''language "kql/2"; module exits;
    query q { callable $f { body {
      while (true) { continue; break; }
      iterate $items as $item as $loop { body { break $loop as $exit; } }
    } } select $f; }''')
    body = tree.declarations[0].clauses[0].blocks[0][0]
    bare = body.blocks[0][0].blocks[0][1]
    scoped = body.blocks[0][1].blocks[0][0].blocks[0][0]
    assert bare.kind == scoped.kind == 'break'
    assert bare.role == bare.alias == ''
    assert scoped.role == 'loop'
    assert scoped.alias == 'exit'
