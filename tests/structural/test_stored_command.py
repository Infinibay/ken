"""Stored actions carry captured bindings and are invoked through the same field."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules

SOURCES = {
 'python': 'class Task:\n def configure(self, data):\n  def action():\n   work(data)\n  self.action = action\n def run(self):\n  self.action()\n',
 'javascript': 'class Task { configure(data){ this.action = () => work(data); } run(){ this.action(); } }',
 'typescript': 'class Task { action: () => void; configure(data: string){ this.action = () => work(data); } run(){ this.action(); } }',
 'csharp': 'class Task { Action action; void Configure(string data){ this.action = () => Work(data); } void Run(){ this.action(); } }',
 'go': 'package p; type Task struct{ action func() }; func New(data string)*Task { return &Task{action: func(){ work(data) }} }; func(t *Task) Run(){t.action()}',
}

def matches(source, language):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('command#stored-closure', registry)], registry=registry)
    assert result['complete']
    return result['matches']

@pytest.mark.parametrize('language', SOURCES)
def test_stored_command(language):
    assert matches(SOURCES[language], language)
    assert matches(SOURCES[language].replace('Task', 'Deferred').replace('data', 'payload'), language)

@pytest.mark.parametrize('language', SOURCES)
def test_without_capture_is_not_bound_action(language):
    assert not matches(SOURCES[language].replace('work(data)', 'work()').replace('Work(data)', 'Work()'), language)

@pytest.mark.parametrize('language', SOURCES)
def test_other_field_is_not_stored_action(language):
    assert not matches(SOURCES[language].replace('self.action()', 'self.other()').replace('this.action()', 'this.other()').replace('t.action()', 't.other()'), language)

@pytest.mark.parametrize('language', ['go', 'javascript', 'typescript'])
def test_capture_without_action_call(language):
    assert not matches(SOURCES[language].replace('work(data)', '_ = data' if language == 'go' else 'data'), language)

def test_go_map_key_is_not_struct_field():
    source = 'package p; type Task struct{ action func() }; func New(data string){ action:="key"; x:=map[string]func(){action:func(){work(data)}}; _=x }; func(t *Task) Run(){t.action()}'
    assert not matches(source, 'go')


@pytest.mark.parametrize('path,package,expected', [('p/task.go', 'p', True), ('other/task.go', 'p', False), ('p/task.go', 'q', False)])
def test_go_cross_file_initializer_respects_package(path, package, expected):
    sources = [(path, f'package {package}; type Task struct{{ action func() }}; func(t *Task) Run(){{t.action()}}'),
               ('p/make.go', 'package p; func New(data string)*Task { return &Task{action:func(){work(data)}} }')]
    graph = link_project([lower_source(s, 'go', p) for p,s in sources])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('command#stored-closure', registry)], registry=registry)
    assert bool(result['matches']) is expected


def test_go_duplicate_type_does_not_guess_initializer_target():
    sources = [('a.go', 'package p; type Task struct{ action func() }; func(t *Task) Run(){t.action()}'),
               ('b.go', 'package p; type Task struct{ other int }'),
               ('make.go', 'package p; func New(data string)*Task{return &Task{action:func(){work(data)}}}')]
    graph = link_project([lower_source(s, 'go', p) for p,s in sources])
    assert not any(f.relation == 'INITIALIZES_FIELD' for f in graph.facts)


def test_go_package_reference_is_not_captured_local_data():
    source = 'package p; import "fmt"; type Task struct{ action func() }; func New()*Task { fmt.Println("before"); return &Task{action:func(){fmt.Println("later")}} }; func(t *Task) Run(){t.action()}'
    assert not matches(source, 'go')
