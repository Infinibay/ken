"""The user's documented source-language example must execute as a saved query."""
from pathlib import Path
import re

import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget


def run(source, language, query):
    graph = link_project([lower_source(source,language,'worker.'+language)])
    assert not graph.diagnostics
    return Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(query))


QUERY = re.search(r'```kql2\n(.*?)\n```', (Path(__file__).parents[2] / 'docs/design/kql2/examples.md').read_text(), re.S)[1]
SOURCES = {
 'java': 'class Job {} class Worker { public String name; public int age; private Job job; public Worker() {} public void work(int task) {} }',
 'csharp': 'class Job {} class Worker { public string name; public int age; private Job job; public Worker() {} public void work(int task) {} }',
}


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['positive', 'wrong_type', 'wrong_visibility', 'wrong_job', 'wrong_method'])
def test_documented_worker_query(language, mutation):
 source=SOURCES[language]
 if mutation=='wrong_type': source=source.replace('int age','double age')
 if mutation=='wrong_visibility': source=source.replace('public int age','private int age')
 if mutation=='wrong_job': source=source.replace('private Job job','private Worker job')
 if mutation=='wrong_method': source=source.replace('void work','void idle')
 result=run(source, language, QUERY)
 assert result['complete'],result
 assert bool(result['matches']) is (mutation=='positive'), result


@pytest.mark.parametrize('annotation,matcher,expected', [
 ('int','integer',True), ('str','string',True), ('float','floating',True),
 ('bool','boolean',True), ('list[int]','list<integer>',True),
 ('dict[str, int]','map<string,integer>',True),
 ('list[str]','list<integer>',False), ('float','integer',False),
 ('Any','any',True), ('int','any',False),
])
def test_saved_source_type_descriptors(annotation, matcher, expected):
 query='''language "kql/2"; module types;
 pattern detect(out Callable $f) { callable $f { param $p { type: '''+matcher+'''; } } }
 query results { use detect(f: $f); select $f; }'''
 result=run('from typing import Any\ndef work(value: '+annotation+'):\n pass\n','python',query)
 assert bool(result['matches']) is expected,result


def test_missing_annotation_does_not_mean_source_type_any():
 query='''language "kql/2"; module types;
 pattern detect(out Callable $f) { callable $f { param $p { type: any; } } }
 query results { use detect(f: $f); select $f; }'''
 result=run('def work(value):\n pass\n','python',query)
 assert not result['matches'] and result['unknown'],result


@pytest.mark.parametrize('name,expected', [('a',True),('b',True),('c',False)])
def test_positional_acceptance_respects_python_parameter_modes(name, expected):
 query='''language "kql/2"; module params;
 pattern detect(out Callable $f) { callable $f { param $p { name: "'''+name+'''"; accepts_position: true; } } }
 query results { use detect(f: $f); select $f; }'''
 result=run('def work(a, /, b, *, c):\n pass\n','python',query)
 assert bool(result['matches']) is expected,result


def test_documented_worker_query_public_search_and_disk_reuse(tmp_path):
 from ken.kql2.service import search
 (tmp_path/'Worker.java').write_text(SOURCES['java'])
 first=search(tmp_path,QUERY,cache_mb=10)
 second=search(tmp_path,QUERY,cache_mb=10)
 assert first['rows'] and second['rows']==first['rows']
