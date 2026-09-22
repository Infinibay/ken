from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.structural_store import Store


def test_order_and_limit_applied_after_union_with_hidden_sort_column():
    p = compile(parse('''language "kql/2"; module t;
      query q {
        { bind $name = "early"; bind $score = 1; }
        or { bind $name = "late"; bind $score = 3; }
        or { bind $name = "middle"; bind $score = 2; }
        select $name; order by $score desc; limit 2;
      }
    '''))
    with Store() as store:
        result = execute(p,store,store.publish([],expected_parent=None))
        assert result.rows == [('late',),('middle',)]
        assert result.complete and result.results_truncated


def test_union_deduplicates_before_limit():
    p = compile(parse('''language "kql/2"; module t; query q {
      { bind $x = 2; } or { bind $x = 2; } or { bind $x = 1; }
      select $x; order by $x; limit 2;
    }'''))
    with Store() as store:
        result = execute(p,store,store.publish([],expected_parent=None))
        assert result.rows == [(1,),(2,)]
        assert result.complete and not result.results_truncated
