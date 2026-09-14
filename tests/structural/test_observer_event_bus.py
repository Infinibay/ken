"""Observer ``event-bus``: a topic-keyed registry, registered and published on.

The variant is a published rule, so the tests go through the registry name
``observer#event-bus`` rather than a private copy of the query.

The contract is the one the design asks for: the topic of the registration and the
topic of the publication are **the same slot**, not merely two strings -- the
identity join is the field entity both sides reach through their registry access:

```
subscribe(handler): <registry under topic> <- handler      (insert)
publish(payload):   for handler in <registry under topic>: handler(payload)
```

The registry is reached two different ways and the query accepts both, because the
languages split on it:

* **index syntax** -- `handlers[topic]` in Go, JS/TS, C#, C++, Rust: the access
  value carries `CONTAINER`/`INDEX` and is also what `INSERTS_INTO` points at.
* **method syntax** -- Python `dict.setdefault`/`get` and Java
  `Map.computeIfAbsent`/`get`: the access is a *call* whose receiver is the
  registry and whose argument 0 is the topic. Java has no `operator[]` on `Map`,
  so without this form the variant could not include it. Java also binds the
  looked-up bucket to a local before iterating, which is a third alternative on
  the publication side (`ASSIGNED_FROM`).

All eight languages use one query and no engine change.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'observer#event-bus'
ROOT = 'observer'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
NAMES = {'unit': 'EventBus', 'registry': 'handlers', 'other': 'spare', 'topic': 'topic',
         'topic_out': 'topicOut', 'subscribe': 'subscribe', 'publish': 'publish',
         'subscriber': 'handler', 'payload': 'payload'}
RENAMED = {'unit': 'Channel', 'registry': 'routes', 'other': 'backup', 'topic': 'subject',
           'topic_out': 'subjectOut', 'subscribe': 'attach', 'publish': 'broadcast',
           'subscriber': 'receiver', 'payload': 'message'}
# Each negative breaks one link of the contract: the two sides stop sharing the
# topic, the registered value is not the subscriber, the publication iterates a
# different registry, the invocation does not receive the payload, or nothing is
# registered at all.
NEGATIVES = ['different-topic', 'other-value', 'other-registry', 'no-payload', 'no-register']
SPARE = {'python': 'None', 'javascript': 'null', 'typescript': 'null', 'java': 'null',
         'csharp': 'null', 'cpp': 'nullptr', 'go': 'nil', 'rust': 'None'}
CONSTANT = {'python': '"constant"', 'javascript': '"constant"', 'typescript': '"constant"',
            'java': '"constant"', 'csharp': '"constant"', 'cpp': '"constant"',
            'go': '"constant"', 'rust': '"constant"'}


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'event-bus')


def _plan(language, mode, n):
    """The names each side uses, and what flows through the two calls."""
    registry_in, registry_out = n['registry'], n['registry']
    topic_in, topic_out = n['topic'], n['topic']
    inserted = n['subscriber']
    argument = n['payload']
    register = True
    if mode == 'different-topic':
        topic_out = n['topic_out']
    elif mode == 'other-value':
        inserted = SPARE[language]
    elif mode == 'other-registry':
        registry_out = n['other']
    elif mode == 'no-payload':
        argument = CONSTANT[language]
    elif mode == 'no-register':
        register = False
    elif mode != 'positive':
        raise AssertionError(mode)
    return registry_in, registry_out, topic_in, topic_out, inserted, argument, register


def source(language, mode, names=None):
    n = names or NAMES
    reg_in, reg_out, topic_in, topic_out, inserted, argument, register = _plan(language, mode, n)
    if language == 'python':
        subscribe = (f'self.{reg_in}.setdefault(self.{topic_in}, []).append({inserted})'
                     if register else f'self.{reg_in}.setdefault(self.{topic_in}, [])')
        return (f'class {n["unit"]}:\n'
                f'    def __init__(self):\n'
                f'        self.{reg_in} = {{}}\n'
                f'        self.{n["other"]} = []\n'
                f'        self.{topic_in} = "click"\n'
                f'        self.{n["topic_out"]} = "click"\n\n'
                f'    def {n["subscribe"]}(self, {n["subscriber"]}):\n'
                f'        {subscribe}\n\n'
                f'    def {n["publish"]}(self, {n["payload"]}):\n'
                f'        for handler in self.{reg_out}.get(self.{topic_out}, []):\n'
                f'            handler({argument})\n')
    if language in {'javascript', 'typescript'}:
        typed = language == 'typescript'
        handler_type = ': (payload: string) => void' if typed else ''
        bucket_type = ': ((payload: string) => void)[]' if typed else ''
        dict_type = ': Record<string, ((payload: string) => void)[]>' if typed else ''
        signature = f'{n["subscriber"]}{handler_type}' if typed else n['subscriber']
        payload_signature = f'{n["payload"]}: string' if typed else n['payload']
        returns = ': void' if typed else ''
        string_type = ': string' if typed else ''
        subscribe = (f'this.{reg_in}[this.{topic_in}].push({inserted});' if register
                     else f'this.{reg_in}[this.{topic_in}] = this.{reg_in}[this.{topic_in}];')
        return (f'class {n["unit"]} {{\n'
                f'  {n["registry"]}{dict_type};\n'
                f'  {n["other"]}{bucket_type};\n'
                f'  {n["topic"]}{string_type};\n'
                f'  {n["topic_out"]}{string_type};\n'
                f'  constructor() {{\n'
                f'    this.{n["registry"]} = {{}};\n'
                f'    this.{n["other"]} = [];\n'
                f'    this.{n["topic"]} = "click";\n'
                f'    this.{n["topic_out"]} = "click";\n'
                f'    this.{n["registry"]}[this.{n["topic"]}] = [];\n'
                f'  }}\n'
                f'  {n["subscribe"]}({signature}){returns} {{ {subscribe} }}\n'
                f'  {n["publish"]}({payload_signature}){returns} {{\n'
                f'    for (const handler of this.{reg_out}[this.{topic_out}]) {{\n'
                f'      handler({argument});\n'
                f'    }}\n'
                f'  }}\n'
                f'}}\n')
    if language == 'java':
        registry = n['registry'] if reg_in == n['registry'] else n['other']
        subscribe = (f'{registry}.computeIfAbsent({topic_in}, key -> new ArrayList<>())'
                     f'.add({inserted});' if register else f'{registry}.get({topic_in});')
        source_registry = n['registry'] if reg_out == n['registry'] else n['other']
        lookup = f'{source_registry}.get({topic_out})'
        return (f'import java.util.HashMap;\nimport java.util.Map;\nimport java.util.List;\n'
                f'import java.util.ArrayList;\nimport java.util.function.Consumer;\n\n'
                f'class {n["unit"]} {{\n'
                f'    private final Map<String, List<Consumer<String>>> {n["registry"]} = new HashMap<>();\n'
                f'    private final Map<String, List<Consumer<String>>> {n["other"]} = new HashMap<>();\n'
                f'    private final String {n["topic"]} = "click";\n'
                f'    private final String {n["topic_out"]} = "click";\n\n'
                f'    void {n["subscribe"]}(Consumer<String> {n["subscriber"]}) {{\n'
                f'        {subscribe}\n'
                f'    }}\n\n'
                f'    void {n["publish"]}(String {n["payload"]}) {{\n'
                f'        List<Consumer<String>> bucket = {lookup};\n'
                f'        if (bucket != null) {{\n'
                f'            for (Consumer<String> handler : bucket) {{\n'
                f'                handler.accept({argument});\n'
                f'            }}\n'
                f'        }}\n'
                f'    }}\n'
                f'}}\n')
    if language == 'csharp':
        registry = n['registry'] if reg_in == n['registry'] else n['other']
        subscribe = (f'{registry}[{topic_in}].Add({inserted});' if register
                     else f'{registry}[{topic_in}].Count();')
        return (f'using System;\nusing System.Collections.Generic;\n\n'
                f'class {n["unit"]} {{\n'
                f'    private readonly Dictionary<string, List<Action<string>>> {n["registry"]} = '
                f'new Dictionary<string, List<Action<string>>>();\n'
                f'    private readonly Dictionary<string, List<Action<string>>> {n["other"]} = '
                f'new Dictionary<string, List<Action<string>>>();\n'
                f'    private readonly string {n["topic"]} = "click";\n'
                f'    private readonly string {n["topic_out"]} = "click";\n\n'
                f'    public void {n["subscribe"]}(Action<string> {n["subscriber"]}) {{\n'
                f'        {subscribe}\n'
                f'    }}\n\n'
                f'    public void {n["publish"]}(string {n["payload"]}) {{\n'
                f'        foreach (Action<string> handler in {reg_out}[{topic_out}]) {{\n'
                f'            handler({argument});\n'
                f'        }}\n'
                f'    }}\n'
                f'}}\n')
    if language == 'cpp':
        registry = n['registry'] if reg_in == n['registry'] else n['other']
        subscribe = (f'{registry}[{topic_in}].push_back({inserted});' if register
                     else f'{registry}[{topic_in}].size();')
        return (f'#include <string>\n#include <vector>\n#include <functional>\n#include <map>\n\n'
                f'class {n["unit"]} {{\n'
                f'    std::map<std::string, std::vector<std::function<void(std::string)>>> {n["registry"]};\n'
                f'    std::map<std::string, std::vector<std::function<void(std::string)>>> {n["other"]};\n'
                f'    std::string {n["topic"]} = "click";\n'
                f'    std::string {n["topic_out"]} = "click";\n'
                f'public:\n'
                f'    void {n["subscribe"]}(std::function<void(std::string)> {n["subscriber"]}) {{\n'
                f'        {subscribe}\n'
                f'    }}\n'
                f'    void {n["publish"]}(std::string {n["payload"]}) {{\n'
                f'        for (auto const& handler : {reg_out}[{topic_out}]) {{\n'
                f'            handler({argument});\n'
                f'        }}\n'
                f'    }}\n'
                f'}};\n')
    if language == 'go':
        registry = n['registry'] if reg_in == n['registry'] else n['other']
        subscribe = (f'\tb.{registry}[b.{topic_in}] = append(b.{registry}[b.{topic_in}], {inserted})'
                     if register else f'\t_ = b.{registry}[b.{topic_in}]')
        source_registry = n['registry'] if reg_out == n['registry'] else n['other']
        lookup = f'b.{source_registry}[b.{topic_out}]'
        export = lambda name: name[:1].upper() + name[1:]
        return (f'package bus\n\n'
                f'type {n["unit"]} struct {{\n'
                f'\t{n["registry"]} map[string][]func(string)\n'
                f'\t{n["other"]} map[string][]func(string)\n'
                f'\t{n["topic"]}    string\n'
                f'\t{n["topic_out"]} string\n'
                f'}}\n\n'
                f'func (b *{n["unit"]}) {export(n["subscribe"])}({n["subscriber"]} func(string)) {{\n'
                f'{subscribe}\n'
                f'}}\n\n'
                f'func (b *{n["unit"]}) {export(n["publish"])}({n["payload"]} string) {{\n'
                f'\tfor _, handler := range {lookup} {{\n'
                f'\t\thandler({argument})\n'
                f'\t}}\n'
                f'}}\n')
    if language == 'rust':
        registry = n['registry'] if reg_in == n['registry'] else n['other']
        subscribe = (f'self.{registry}[&self.{topic_in}].push({inserted});' if register
                     else f'let _ = &self.{registry}[&self.{topic_in}];')
        source_registry = n['registry'] if reg_out == n['registry'] else n['other']
        lookup = f'&self.{source_registry}[&self.{topic_out}]'
        return (f'use std::collections::HashMap;\n\n'
                f'struct {n["unit"]} {{\n'
                f'    {n["registry"]}: HashMap<String, Vec<Box<dyn Fn(&str)>>>,\n'
                f'    {n["other"]}: HashMap<String, Vec<Box<dyn Fn(&str)>>>,\n'
                f'    {n["topic"]}: String,\n'
                f'    {n["topic_out"]}: String,\n'
                f'}}\n\n'
                f'impl {n["unit"]} {{\n'
                f'    fn {n["subscribe"]}(&mut self, {n["subscriber"]}: Box<dyn Fn(&str)>) {{\n'
                f'        {subscribe}\n'
                f'    }}\n\n'
                f'    fn {n["publish"]}(&self, {n["payload"]}: &str) {{\n'
                f'        for handler in {lookup} {{\n'
                f'            handler({argument});\n'
                f'        }}\n'
                f'    }}\n'
                f'}}\n')
    raise AssertionError(language)


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'bus.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, (language, mode, graph.diagnostics)
    return graph


def detect(language, mode, names=None, rule=RULE):
    graph = build(language, mode, names)
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_topic_keyed_registration_and_publication_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    assert {m['bindings']['$unit'] for m in matches} == {
        f'bus.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}
    bindings = matches[0]['bindings']
    for role in ('$subscription', '$publication', '$registry', '$topic',
                 '$subscriber', '$payload', '$invocation'):
        assert role in bindings, (language, role)
    assert bindings['$subscription'] != bindings['$publication']
    assert bindings['$subscriber'] != bindings['$payload']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'positive', names=RENAMED)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'bus.{EXTENSIONS[language]}::module/CLASS:{RENAMED["unit"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_bus(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'bus.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    for relation in ['INSERTED_VALUE', 'INSERTS_INTO', 'ITERATES_CALLS',
                     'ITERATION_INVOKES_VALUE', 'HAS_FIELD']:
        assert relation in row['query'], relation


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_topic_slot_is_the_one_both_sides_use(language):
    """The same field entity is the topic of both sides, so the two spellings are
    joined by identity -- not by comparing names. The fixture also declares a
    second topic field, and the match must bind neither it nor the spare
    registry."""
    bindings = detect(language, 'positive')[0]['bindings']
    graph = build(language, 'positive')
    assert graph.entities[bindings['$topic']].name == NAMES['topic']
    assert graph.entities[bindings['$registry']].name == NAMES['registry']
    assert not detect(language, 'different-topic')
