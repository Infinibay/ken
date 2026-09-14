"""Proxy ``remote-subject``: a local class that serializes a call to a client.

The variant is a published rule, so the tests go through the registry name
``proxy#remote-subject`` rather than a private copy of the query.

The contract has no API name table -- it is the second alternative the ficha allows,
"a visible local implementation that serializes the call and returns its response":

    String call(String payload) {
        String response = client.post("/api", codec.encode(payload));
        return codec.decode(response);
    }

Four pieces: the class **is** the local representation of the contract (``SUBTYPE_OF``,
or ``IMPLEMENTS`` in Go, which satisfies an interface by method set); it holds a client
whose type is **not** that contract; the transport call's argument is the result of an
**encoder** fed by the method's own parameter; and the method returns the result of a
**decoder**. ``different $transport $decoder`` keeps the decoder line itself from
qualifying as the transport (Java returned a second, spurious match without it).

The client's type comes from a declaration (python's annotation, java/csharp/cpp/go/rust
fields, typescript's field) or from the **construction** the field is initialized with,
which is what JavaScript has instead of a declaration: measured, ``this.client = new
HttpClient()`` yields ``TYPE client -> HttpClient`` while ``this.client = client`` does
not.

The negatives are derived from the positive by explicit per-language edits, and every
derived source is parsed in ``build()``, so an invalid edit fails instead of being
analysed as something else.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'proxy#remote-subject'
ROOT = 'proxy'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
NAMES = {'unit': 'RemoteService', 'contract': 'Service', 'client': 'HttpClient',
         'codec': 'JsonCodec', 'method': 'call', 'field': 'client', 'wire': 'codec'}
RENAMED = {'unit': 'WireService', 'contract': 'Api', 'client': 'Transport',
           'codec': 'Wire', 'method': 'invoke', 'field': 'transport', 'wire': 'wire'}
NEGATIVES = ['no-codec', 'same-contract-client', 'no-decode', 'other-payload']


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'remote-subject')


def _exported(name):
    return name[:1].upper() + name[1:]


def positive(language, n):
    """The canonical proxy: implement the contract, serialize, decode the reply."""
    unit, contract, client = n['unit'], n['contract'], n['client']
    codec, method, field, wire = n['codec'], n['method'], n['field'], n['wire']
    encode = _exported('encode') if language in {'go', 'csharp'} else 'encode'
    decode = _exported('decode') if language in {'go', 'csharp'} else 'decode'
    transport = _exported('post') if language in {'go', 'csharp'} else 'post'
    if language == 'python':
        return (f'class {contract}:\n    def {method}(self, payload):\n        pass\n\n\n'
                f'class {codec}:\n    def {encode}(self, value):\n        return "{{}}"\n\n'
                f'    def {decode}(self, text):\n        return None\n\n\n'
                f'class {client}:\n    def {transport}(self, url, body):\n        return ""\n\n\n'
                f'class {unit}({contract}):\n'
                f'    def __init__(self, {field}: {client}, {wire}: {codec}):\n'
                f'        self.{field} = {field}\n        self.{wire} = {wire}\n\n'
                f'    def {method}(self, payload):\n'
                f'        response = self.{field}.{transport}("/api", self.{wire}.{encode}(payload))\n'
                f'        return self.{wire}.{decode}(response)\n')
    if language in {'javascript', 'typescript'}:
        typed = language == 'typescript'
        declared = f'  {field}: {client};\n  {wire}: {codec};\n' if typed else ''
        parameters = (f'{field}: {client}, {wire}: {codec}' if typed else f'{field}, {wire}')
        assignment = (f'this.{field} = {field}; this.{wire} = {wire};' if typed
                      else f'this.{field} = new {client}(); this.{wire} = new {codec}();')
        return (f'class {contract} {{ {method}(payload) {{ }} }}\n\n'
                f'class {codec} {{\n  {encode}(value) {{ return "{{}}"; }}\n'
                f'  {decode}(text) {{ return null; }}\n}}\n\n'
                f'class {client} {{ {transport}(url, body) {{ return ""; }} }}\n\n'
                f'class {unit} extends {contract} {{\n{declared}'
                f'  constructor({parameters}) {{ super(); {assignment} }}\n'
                f'  {method}(payload) {{\n'
                f'    const response = this.{field}.{transport}("/api", this.{wire}.{encode}(payload));\n'
                f'    return this.{wire}.{decode}(response);\n  }}\n}}\n')
    if language == 'java':
        return (f'class {contract} {{ String {method}(String payload) {{ return null; }} }}\n\n'
                f'class {codec} {{\n  String {encode}(String value) {{ return "{{}}"; }}\n'
                f'  String {decode}(String text) {{ return null; }}\n}}\n\n'
                f'class {client} {{ String {transport}(String url, String body) {{ return ""; }} }}\n\n'
                f'class {unit} extends {contract} {{\n'
                f'    private {client} {field};\n    private {codec} {wire};\n'
                f'    {unit}({client} {field}, {codec} {wire}) '
                f'{{ this.{field} = {field}; this.{wire} = {wire}; }}\n'
                f'    String {method}(String payload) {{\n'
                f'        String response = {field}.{transport}("/api", {wire}.{encode}(payload));\n'
                f'        return {wire}.{decode}(response);\n    }}\n}}\n')
    if language == 'csharp':
        return (f'class {contract} {{ public virtual string {method}(string payload) {{ return null; }} }}\n\n'
                f'class {codec} {{\n  public string {encode}(string value) {{ return "{{}}"; }}\n'
                f'  public string {decode}(string text) {{ return null; }}\n}}\n\n'
                f'class {client} {{ public string {transport}(string url, string body) {{ return ""; }} }}\n\n'
                f'class {unit} : {contract} {{\n'
                f'    private readonly {client} {field};\n    private readonly {codec} {wire};\n'
                f'    public {unit}({client} {field}, {codec} {wire}) '
                f'{{ this.{field} = {field}; this.{wire} = {wire}; }}\n'
                f'    public override string {method}(string payload) {{\n'
                f'        string response = {field}.{transport}("/api", {wire}.{encode}(payload));\n'
                f'        return {wire}.{decode}(response);\n    }}\n}}\n')
    if language == 'cpp':
        return (f'#include <string>\n\n'
                f'class {contract} {{ public: virtual int {method}(int payload) {{ return 0; }} }};\n\n'
                f'class {codec} {{\npublic:\n'
                f'    int {encode}(int value) {{ return 0; }}\n'
                f'    int {decode}(int text) {{ return 0; }}\n}};\n\n'
                f'class {client} {{ public: int {transport}(std::string url, int body) {{ return 0; }} }};\n\n'
                f'class {unit} : public {contract} {{\n'
                f'    {client}* {field};\n    {codec}* {wire};\npublic:\n'
                f'    {unit}({client}* a, {codec}* b) : {field}(a), {wire}(b) {{}}\n'
                f'    int {method}(int payload) override {{\n'
                f'        int response = {field}->{transport}("/api", {wire}->{encode}(payload));\n'
                f'        return {wire}->{decode}(response);\n    }}\n}};\n')
    if language == 'go':
        return (f'package remote\n\n'
                f'type {contract} interface{{ {_exported(method)}(payload string) string }}\n\n'
                f'type {codec} struct{{}}\n'
                f'func ({codec}) {encode}(value string) string {{ return "{{}}" }}\n'
                f'func ({codec}) {decode}(text string) string {{ return "" }}\n\n'
                f'type {client} struct{{}}\n'
                f'func ({client}) {transport}(url string, body string) string {{ return "" }}\n\n'
                f'type {unit} struct {{\n\t{field} {client}\n\t{wire} {codec}\n}}\n\n'
                f'func (r {unit}) {_exported(method)}(payload string) string {{\n'
                f'\tresponse := r.{field}.{transport}("/api", r.{wire}.{encode}(payload))\n'
                f'\treturn r.{wire}.{decode}(response)\n}}\n')
    if language == 'rust':
        return (f'struct {codec};\n\n'
                f'impl {codec} {{\n'
                f'    fn {encode}(&self, value: &str) -> String {{ String::from("{{}}") }}\n'
                f'    fn {decode}(&self, text: &str) -> String {{ String::new() }}\n}}\n\n'
                f'struct {client};\n\n'
                f'impl {client} {{\n'
                f'    fn {transport}(&self, url: &str, body: String) -> String {{ String::new() }}\n}}\n\n'
                f'trait {contract} {{ fn {method}(&self, payload: &str) -> String; }}\n\n'
                f'struct {unit} {{ {field}: {client}, {wire}: {codec} }}\n\n'
                f'impl {contract} for {unit} {{\n'
                f'    fn {method}(&self, payload: &str) -> String {{\n'
                f'        let response = self.{field}.{transport}("/api", self.{wire}.{encode}(payload));\n'
                f'        return self.{wire}.{decode}(&response);\n    }}\n}}\n')
    raise AssertionError(language)


def _edits(language, mode, n):
    """Explicit per-language edits that break one link of the contract."""
    codec, client, contract = n['codec'], n['client'], n['contract']
    field, wire = n['field'], n['wire']
    encode = _exported('encode') if language in {'go', 'csharp'} else 'encode'
    owner = {'python': f'self.{wire}.', 'javascript': f'this.{wire}.',
             'typescript': f'this.{wire}.', 'cpp': f'{wire}->', 'go': f'r.{wire}.',
             'rust': f'self.{wire}.'}
    owner = owner.get(language, f'{wire}.')
    if mode == 'no-codec':
        return [(f'{owner}{encode}(payload)', 'payload')]
    if mode == 'same-contract-client':
        if language == 'javascript':
            return [(f'new {client}()', f'new {contract}()')]
        if language == 'typescript':
            return [(f'{field}: {client}', f'{field}: {contract}')]
        if language == 'python':
            return [(f'{field}: {client}', f'{field}: {contract}')]
        if language == 'java':
            return [(f'private {client} {field};', f'private {contract} {field};')]
        if language == 'csharp':
            return [(f'readonly {client} {field};', f'readonly {contract} {field};')]
        if language == 'cpp':
            return [(f'{client}* {field};', f'{contract}* {field};')]
        if language == 'go':
            return [(f'{field} {client}', f'{field} {contract}')]
        if language == 'rust':
            return [(f'{field}: {client},', f'{field}: Box<dyn {contract}>,')]
    if mode == 'no-decode':
        if language == 'python':
            return [(f'return self.{wire}.decode(response)', 'return "constant"')]
        if language in {'javascript', 'typescript'}:
            return [(f'return this.{wire}.decode(response);', 'return "constant";')]
        if language == 'java':
            return [(f'return {wire}.decode(response);', 'return "constant";')]
        if language == 'cpp':
            return [(f'return {wire}->decode(response);', 'return "constant";')]
        if language == 'csharp':
            return [(f'return {wire}.Decode(response);', 'return "constant";')]
        if language == 'go':
            return [(f'return r.{wire}.Decode(response)', 'return "constant"')]
        if language == 'rust':
            return [(f'return self.{wire}.decode(&response);', 'return "constant";')]
    if mode == 'other-payload':
        return [(f'{encode}(payload)', f'{encode}("constant")')]
    raise AssertionError(mode)


def source(language, mode, names=None):
    n = names or NAMES
    if mode == 'renamed':
        return positive(language, RENAMED)
    text = positive(language, n)
    if mode == 'positive':
        return text
    for old, new in _edits(language, mode, n):
        assert old in text, (language, mode, old)
        text = text.replace(old, new, 1)
    return text


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'remote.{EXTENSIONS[language]}')])
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
def test_serializing_remote_proxy_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    assert {m['bindings']['$unit'] for m in matches} == {
        f'remote.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}
    bindings = matches[0]['bindings']
    for role in ('$contract', '$client', '$method', '$transport', '$encoder',
                 '$decoder', '$request'):
        assert role in bindings, (language, role)
    assert bindings['$transport'] != bindings['$decoder']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'renamed')
    assert {m['bindings']['$unit'] for m in matches} == {
        f'remote.{EXTENSIONS[language]}::module/CLASS:{RENAMED["unit"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_remote_proxy(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'remote.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    for relation in ['SUBTYPE_OF', 'IMPLEMENTS', 'OVERRIDES', 'RESULT', 'RETURNS_CALL']:
        assert relation in row['query'], relation


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_client_type_is_what_separates_it_from_a_decorator(language):
    """The client must be typed and must not be the contract, or the shape accepts any
    wrapper that happens to serialize."""
    graph = build(language, 'positive')
    assert [f for f in graph.facts if f.relation == 'TYPE'], language
    assert not detect(language, 'same-contract-client')
