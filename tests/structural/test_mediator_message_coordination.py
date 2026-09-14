"""Mediator ``message-coordination``: a tag selects which colleague the centre calls.

The variant is a published rule, so the tests go through the registry name
``mediator#message-coordination`` rather than a private copy of the query.

The shape is the one the design table draws as "coordinación por tag":

```
colleague.notify(tag)  ->  coordinator.coordinate(self, tag)
coordinator.coordinate(origin, tag):
    if tag == N: first.apply(tag) else: second.apply(tag)
```

Nothing here requires the colleagues to hold a *typed* reference to the centre:
what ties the two sides together is the callee name at the notification site
compared with the dispatching method's name -- the same idiom
``composite#recursive-nominal`` already uses -- plus ``PASSES_SELF_TO`` proving the
colleagues hand themselves over. That is why the variant works for JavaScript,
where the injected coordinator has no recorded type at all.

The evidence for one unit:

* ``PASSES_SELF_TO`` from two methods of **two different types**, each of which
  calls a method whose name is the dispatching method's name;
* the dispatching method ``CONDITIONAL_DELEGATION`` to **two different fields of
  the centre**, each selected call carrying an argument loaded from the *same*
  parameter (the tag).

Not proven, and stated in ``query_claim``: that the two branches are the ``then``
and ``else`` of one test, that the tag values actually differ, that the targets are
distinct objects at runtime, or that the notification ever returns.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'mediator#message-coordination'
ROOT = 'mediator'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
NAMES = {'a': 'ColleagueA', 'b': 'ColleagueB', 'centre': 'Coordinator',
         'notify': 'notify', 'apply': 'apply', 'coordinate': 'coordinate',
         'tag': 'tag', 'origin': 'origin', 'first': 'first', 'second': 'second'}
RENAMED = {'a': 'Sender', 'b': 'Receiver', 'centre': 'Hub',
           'notify': 'announce', 'apply': 'handle', 'coordinate': 'route',
           'tag': 'kind', 'origin': 'who', 'first': 'left', 'second': 'right'}
NEGATIVES = ['no-branch', 'same-target', 'no-tag-argument', 'no-self', 'one-colleague']


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'message-coordination')


def _arms(language, mode, n):
    """The centre's dispatch body: two field calls, conditionally, with the tag."""
    apply_name = _exported(n['apply']) if language == 'go' else n['apply']
    target = n['first'] if mode == 'same-target' else None
    first = target or n['first']
    second = target or n['second']
    argument = '0' if mode == 'no-tag-argument' else n['tag']
    call = {'cpp': 'this->{t}->{apply}({a});'}.get(language, 'this.{t}.{apply}({a});')
    if language == 'go':
        call = 'c.{t}.{apply}({a})'
    elif language == 'rust':
        call = 'self.{t}.{apply}({a});'
    elif language in {'python', 'java', 'csharp'}:
        call = 'self.{t}.{apply}({a})' + (';' if language != 'python' else '')
    one = call.format(t=first, apply=apply_name, a=argument)
    two = call.format(t=second, apply=apply_name, a=argument)
    if mode == 'no-branch':
        return f'        {one}\n        {two}'
    condition = {'python': 'if {tag} == 1:', 'go': 'if {tag} == 1 {{',
                 'rust': 'if {tag} == 1 {{'}.get(language, 'if ({tag} === 1) {')
    if language == 'python':
        return f'        {condition.format(tag=n["tag"])}\n            {one}\n        else:\n            {two}'
    if language == 'go':
        return (f'        if {n["tag"]} == 1 {{\n            {one}\n'
                f'        }} else {{\n            {two}\n        }}')
    if language == 'rust':
        return (f'        if {n["tag"]} == 1 {{\n            {one}\n'
                f'        }} else {{\n            {two}\n        }}')
    if language in {'javascript', 'typescript'}:
        return f'    if ({n["tag"]} === 1) {{ {one} }} else {{ {two} }}'
    if language == 'java':
        return f'        if ({n["tag"]} == 1) {{ {one} }} else {{ {two} }}'
    if language == 'csharp':
        return f'        if ({n["tag"]} == 1) {{ {one} }} else {{ {two} }}'
    if language == 'cpp':
        return f'        if ({n["tag"]} == 1) {{ {one} }} else {{ {two} }}'
    raise AssertionError(language)


def _exported(name):
    """Go spells an exported method with an upper-case first letter."""
    return name[:1].upper() + name[1:]


def _notification(language, mode, n):
    """The colleague's self-announcement, and whether the second one exists."""
    argument = '0' if mode == 'no-self' else None
    if language == 'python':
        return (f'self.{n["centre"].lower()}.{n["coordinate"]}('
                f'{"0" if argument else "self"}, {n["tag"]})')
    if language == 'go':
        return (f'col.{n["centre"].lower()}.{_exported(n["coordinate"])}('
                f'{"0" if argument else "col"}, {n["tag"]})')
    if language == 'rust':
        return (f'self.{n["centre"].lower()}.{n["coordinate"]}('
                f'{"0" if argument else "self"}, {n["tag"]});')
    return (f'this.{n["centre"].lower()}.{n["coordinate"]}('
            f'{"0" if argument else "this"}, {n["tag"]})' + (';' if language != 'typescript' else ';'))


def source(language, mode, names=None):
    n = names or NAMES
    field = n['centre'].lower()
    arms = _arms(language, mode, n)
    notice = _notification(language, mode, n)
    second_declares_notify = mode != 'one-colleague'
    if language == 'python':
        def colleague(name, with_notify):
            notify = (f'\n    def {n["notify"]}(self, {n["tag"]}):\n        {notice}\n'
                      if with_notify else '')
            return (f'class {name}:\n'
                    f'    def __init__(self, {field}):\n        self.{field} = {field}\n'
                    f'{notify}\n'
                    f'    def {n["apply"]}(self, {n["tag"]}):\n        pass\n\n\n')
        return (colleague(n['a'], True) + colleague(n['b'], second_declares_notify)
                + f'class {n["centre"]}:\n'
                  f'    def __init__(self, {n["first"]}, {n["second"]}):\n'
                  f'        self.{n["first"]} = {n["first"]}\n'
                  f'        self.{n["second"]} = {n["second"]}\n\n'
                  f'    def {n["coordinate"]}(self, {n["origin"]}, {n["tag"]}):\n'
                  f'{arms}\n')
    if language in {'javascript', 'typescript'}:
        typed = language == 'typescript'
        def colleague(name, with_notify):
            notify = (f'  {n["notify"]}({n["tag"]}{": number" if typed else ""}) '
                      f'{{ {notice} }}\n' if with_notify else '')
            return (f'class {name} {{\n'
                    f'  {field}{": " + n["centre"] if typed else ""};\n'
                    f'  constructor({field}{": " + n["centre"] if typed else ""}) '
                    f'{{ this.{field} = {field}; }}\n'
                    f'{notify}'
                    f'  {n["apply"]}({n["tag"]}{": number" if typed else ""}) {{ }}\n'
                    f'}}\n\n')
        return (colleague(n['a'], True) + colleague(n['b'], second_declares_notify)
                + f'class {n["centre"]} {{\n'
                  f'  {n["first"]}{": " + n["a"] if typed else ""};\n'
                  f'  {n["second"]}{": " + n["b"] if typed else ""};\n'
                  f'  constructor({n["first"]}{": " + n["a"] if typed else ""}, '
                  f'{n["second"]}{": " + n["b"] if typed else ""}) '
                  f'{{ this.{n["first"]} = {n["first"]}; this.{n["second"]} = {n["second"]}; }}\n'
                  f'  {n["coordinate"]}({n["origin"]}{": " + n["a"] if typed else ""}, '
                  f'{n["tag"]}{": number" if typed else ""})'
                  f'{": void" if typed else ""} {{\n{arms}\n  }}\n}}\n')
    if language == 'java':
        def colleague(name, with_notify):
            notify = (f'  void {n["notify"]}(int {n["tag"]}) {{ {notice} }}\n'
                      if with_notify else '')
            return (f'class {name} {{\n'
                    f'  {n["centre"]} {field};\n'
                    f'  {name}({n["centre"]} {field}) {{ this.{field} = {field}; }}\n'
                    f'{notify}  void {n["apply"]}(int {n["tag"]}) {{ }}\n'
                    f'}}\n\n')
        return (colleague(n['a'], True) + colleague(n['b'], second_declares_notify)
                + f'class {n["centre"]} {{\n'
                  f'  {n["a"]} {n["first"]};\n  {n["b"]} {n["second"]};\n'
                  f'  {n["centre"]}({n["a"]} {n["first"]}, {n["b"]} {n["second"]}) '
                  f'{{ this.{n["first"]} = {n["first"]}; this.{n["second"]} = {n["second"]}; }}\n'
                  f'  void {n["coordinate"]}({n["a"]} {n["origin"]}, int {n["tag"]}) {{\n'
                  f'{arms}\n  }}\n}}\n')
    if language == 'csharp':
        def colleague(name, with_notify):
            notify = (f'  public void {n["notify"]}(int {n["tag"]}) {{ {notice} }}\n'
                      if with_notify else '')
            return (f'class {name} {{\n'
                    f'  {n["centre"]} {field};\n'
                    f'  public {name}({n["centre"]} {field}) {{ this.{field} = {field}; }}\n'
                    f'{notify}  public void {n["apply"]}(int {n["tag"]}) {{ }}\n'
                    f'}}\n\n')
        return (colleague(n['a'], True) + colleague(n['b'], second_declares_notify)
                + f'class {n["centre"]} {{\n'
                  f'  {n["a"]} {n["first"]};\n  {n["b"]} {n["second"]};\n'
                  f'  public {n["centre"]}({n["a"]} {n["first"]}, {n["b"]} {n["second"]}) '
                  f'{{ this.{n["first"]} = {n["first"]}; this.{n["second"]} = {n["second"]}; }}\n'
                  f'  public void {n["coordinate"]}({n["a"]} {n["origin"]}, int {n["tag"]}) {{\n'
                  f'{arms}\n  }}\n}}\n')
    if language == 'cpp':
        def colleague(name, with_notify):
            notify = (f'  void {n["notify"]}(int {n["tag"]}) {{ {notice} }}\n'
                      if with_notify else '')
            return (f'class {name};\n')
        # C++ needs the centre declared first so the injected pointer has a type.
        forward = f'class {n["centre"]};\nclass {n["a"]};\nclass {n["b"]};\n\n'
        def colleague_body(name, with_notify):
            notify = (f'  void {n["notify"]}(int {n["tag"]}) {{ {notice} }}\n'
                      if with_notify else '')
            return (f'class {name} {{\npublic:\n'
                    f'  {n["centre"]}* {field};\n'
                    f'  {name}({n["centre"]}* {field}) : {field}({field}) {{}}\n'
                    f'{notify}  void {n["apply"]}(int {n["tag"]}) {{ }}\n'
                    f'}};\n\n')
        return (forward
                + colleague_body(n['a'], True) + colleague_body(n['b'], second_declares_notify)
                + f'class {n["centre"]} {{\npublic:\n'
                  f'  {n["a"]}* {n["first"]};\n  {n["b"]}* {n["second"]};\n'
                  f'  {n["centre"]}({n["a"]}* {n["first"]}, {n["b"]}* {n["second"]}) '
                  f': {n["first"]}({n["first"]}), {n["second"]}({n["second"]}) {{}}\n'
                  f'  void {n["coordinate"]}({n["a"]}* {n["origin"]}, int {n["tag"]}) {{\n'
                  f'{arms}\n  }}\n}};\n')
    if language == 'go':
        def colleague(name, with_notify):
            notify = (f'func (col {name}) {_exported(n["notify"])}'
                      f'({n["tag"]} int) {{ {notice} }}\n' if with_notify else '')
            return (f'type {name} struct{{ {field} *{n["centre"]} }}\n\n'
                    f'{notify}'
                    f'func (col {name}) {_exported(n["apply"])}({n["tag"]} int) {{}}\n\n')
        return ('package mediator\n\n'
                f'type {n["first"]}Applier interface{{ {_exported(n["apply"])}(int) }}\n'
                f'type {n["second"]}Applier interface{{ {_exported(n["apply"])}(int) }}\n\n'
                f'type {n["centre"]} struct {{\n'
                f'\t{n["first"]}  {n["first"]}Applier\n'
                f'\t{n["second"]} {n["second"]}Applier\n'
                f'}}\n\n'
                f'func (c *{n["centre"]}) {_exported(n["coordinate"])}'
                f'({n["origin"]} any, {n["tag"]} int) {{\n{arms}\n}}\n\n'
                + colleague(n['a'], True) + colleague(n['b'], second_declares_notify))
    if language == 'rust':
        def colleague(name, with_notify):
            notify = (f'    fn {n["notify"]}(&self, {n["tag"]}: i32) {{ {notice} }}\n'
                      if with_notify else '')
            return (f'struct {name} {{ {field}: {n["centre"]} }}\n\n'
                    f'impl {name} {{\n{notify}'
                    f'    fn {n["apply"]}(&self, {n["tag"]}: i32) {{}}\n}}\n\n')
        return ('trait ApplierA { fn apply(&self, tag: i32); }\n'
                'trait ApplierB { fn apply(&self, tag: i32); }\n\n'
                f'struct {n["centre"]} {{ {n["first"]}: Box<dyn ApplierA>, '
                f'{n["second"]}: Box<dyn ApplierB> }}\n\n'
                f'impl {n["centre"]} {{\n'
                f'    fn {n["coordinate"]}(&self, {n["origin"]}: &{n["a"]}, '
                f'{n["tag"]}: i32) {{\n{arms}\n    }}\n}}\n\n'
                + colleague(n['a'], True) + colleague(n['b'], second_declares_notify))
    raise AssertionError(language)


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'mediator.{EXTENSIONS[language]}')])
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
def test_tag_selected_coordination_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    # The centre is the only reported unit. The two targets and the two
    # colleagues are symmetric, so the evidence comes back in every permutation.
    assert {m['bindings']['$unit'] for m in matches} == {
        f'mediator.{EXTENSIONS[language]}::module/CLASS:{NAMES["centre"]}'}
    bindings = matches[0]['bindings']
    for role in ('$operation', '$first_target', '$second_target', '$tag',
                 '$colleague_a', '$colleague_b'):
        assert role in bindings, (language, role)
    assert bindings['$first_target'] != bindings['$second_target']
    assert bindings['$colleague_a'] != bindings['$colleague_b']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'positive', names=RENAMED)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'mediator.{EXTENSIONS[language]}::module/CLASS:{RENAMED["centre"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_centre(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'mediator.{EXTENSIONS[language]}::module/CLASS:{NAMES["centre"]}'}


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    for relation in ['PASSES_SELF_TO', 'CONDITIONAL_DELEGATION', 'HAS_FIELD', 'LOADED_FROM']:
        assert relation in row['query'], relation


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_self_handover_is_what_admits_the_centre(language):
    """``PASSES_SELF_TO`` is the colleague half: it is absent when a plain value is
    handed over, and the notification call's callee name is what ties the two
    sides together without a typed reference to the centre."""
    def count(graph):
        return len([f for f in graph.facts if f.relation == 'PASSES_SELF_TO'])
    assert count(build(language, 'positive')) == 2, language
    assert count(build(language, 'no-self')) == 0, language
