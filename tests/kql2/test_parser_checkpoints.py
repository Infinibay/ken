"""Lookahead rollback must retain token identity and UTF-8 source locations."""

from ken.kql2.syntax import parse
from ken.kql2.syntax.parser import Parser


def test_checkpoint_restores_lookahead_and_last_span():
    parser = Parser('"é🙂" call $f {}')
    parser.take()
    last = parser.last
    checkpoint = parser.mark()
    token = parser.take()
    parser.take()
    parser.reset(checkpoint)
    assert parser.last == last
    assert parser.take() is token
    assert parser.role() == "f"


def test_unicode_rollback_across_properties_call_and_assignment():
    source = """language "kql/2"; module test;
    pattern P(out Callable $f) {
      callable $f { name: "é🙂"; body {
        call $f { argument $x at 0; };
        $x = 1;
      } }
    }"""
    tree = parse(source)
    body = tree.declarations[0].clauses[0].blocks[0][1]
    call, assignment = body.blocks[0]
    raw = source.encode()
    assert (
        raw[call.span.start : call.span.end].decode()
        == "call $f { argument $x at 0; };"
    )
    assert raw[assignment.span.start : assignment.span.end].decode() == "$x = 1;"
