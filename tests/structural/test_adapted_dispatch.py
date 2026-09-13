"""Inherited web-style registries, input access paths and callable adaptation."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript']


def source(language):
    if language == 'python':
        return '''class Storage:
 def __init__(self): self.handlers={}
class Registrar(Storage):
 def add(self, key, handler): self.handlers[key]=handler
class Router(Registrar):
 def normalize(self, handler):
  if needs_adapter(handler): return wrap(handler)
  return handler
 def dispatch(self, context, data):
  request=context.request
  route=request.route
  return self.normalize(self.handlers[route.key])(data)
'''
    return '''class Storage { constructor(){this.handlers={};} }
class Registrar extends Storage { add(key, handler){this.handlers[key]=handler;} }
class Router extends Registrar {
 normalize(handler){if(needs_adapter(handler)){return wrap(handler);}return handler;}
 dispatch(context,data){let request=context.request;let route=request.route;
 return this.normalize(this.handlers[route.key])(data);}
}'''


def run(text, language):
    graph = link_project([lower_source(text, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.dispatch-table#adapted', registry)], registry=registry)
    assert result['complete']
    return graph, result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_inherited_adapted_dispatch(language):
    graph, matches = run(source(language), language)
    assert len(matches) == 1
    roles = {k: graph.entities[v].name for k, v in matches[0]['bindings'].items()}
    assert roles == {'$unit': 'Router', '$register': 'add', '$dispatch': 'dispatch', '$table': 'handlers'}
    paths = [f.attrs['members'] for f in graph.facts if f.relation == 'ACCESS_INPUT']
    assert ['request', 'route', 'key'] in paths


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-table', 'no-register', 'unused-adapter', 'discard-input',
                                    'other-input', 'other-context', 'overwrite-alias', 'late-alias',
                                    'conditional-alias', 'override-register', 'unknown-base', 'private-field'])
def test_adapted_dispatch_near_misses(language, mutation):
    text = source(language)
    py = language == 'python'
    if mutation == 'other-table':
        text = text.replace('handlers[route.key]', 'others[route.key]')
    elif mutation == 'no-register':
        text = text.replace('handlers[key]=handler', 'handlers[key]=key')
    elif mutation == 'unused-adapter':
        text = text.replace('handlers[route.key])(data)', 'handlers[route.key])')
    elif mutation == 'discard-input':
        text = text.replace('wrap(handler)', 'wrap(other)').replace('return handler', 'return other')
    elif mutation == 'other-input':
        text = text.replace('normalize(self.handlers[route.key])', 'normalize(other)').replace('normalize(this.handlers[route.key])', 'normalize(other)')
    elif mutation == 'other-context':
        text = text.replace('request=context.request', 'request=other.request')
    elif mutation == 'overwrite-alias':
        text = text.replace('  route=request.route', '  request=other\n  route=request.route') if py else text.replace('let route=', 'request=other;let route=')
    elif mutation == 'late-alias':
        text = text.replace('  route=request.route\n', '') + '  route=request.route\n' if py else text.replace('let route=request.route;', '').replace('(data);}', '(data);let route=request.route;}')
    elif mutation == 'conditional-alias':
        text = text.replace('  request=context.request', '  if data:\n   request=context.request') if py else text.replace('let request=context.request;', 'if(data){var request=context.request;}')
    elif mutation == 'override-register':
        text = text.replace('class Router(Registrar):', 'class Router(Registrar):\n def add(self,key,handler): pass') if py else text.replace('class Router extends Registrar {', 'class Router extends Registrar { add(key,handler){}')
    elif mutation == 'unknown-base':
        text = text.replace('Registrar(Storage)', 'Registrar(Unknown)').replace('Registrar extends Storage', 'Registrar extends Unknown')
    else:
        # Python mangling and JS lexical private slots are not common public slots.
        text = text.replace('handlers', '__handlers' if py else '#handlers')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_overwritten_adapter_parameter_is_not_original_handler(language):
    text = source(language)
    text = text.replace('  if needs_adapter', '  handler=other\n  if needs_adapter') if language == 'python' else text.replace('normalize(handler){', 'normalize(handler){handler=other;')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_registry_does_not_depend_on_framework_symbols(language):
    text = source(language)
    for a, b in [('Router','Application'),('normalize','adapt'),('handlers','actions'),('context','event')]:
        text = text.replace(a,b)
    assert run(text, language)[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_adapter_returning_only_a_wrapper(language):
    text = source(language).replace('  return handler', '  return wrap(handler)').replace('}return handler;', '}return wrap(handler);')
    assert run(text, language)[1]


def test_multiple_inheritance_does_not_guess_mro():
    text = source('python').replace('class Router(Registrar):', 'class Other: pass\nclass Router(Registrar, Other):')
    assert run(text, 'python')[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_direct_parameter_key_is_also_supported(language):
    text = source(language).replace('handlers[route.key]', 'handlers[context]')
    assert run(text, language)[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_field_replacing_inherited_method_is_not_effective_registration(language):
    text = source(language)
    if language == 'python':
        text = text.replace('class Router(Registrar):', 'class Router(Registrar):\n add=other')
    else:
        text = text.replace('class Router extends Registrar {', 'class Router extends Registrar { add=other;')
    assert run(text, language)[1] == []


def test_property_replacing_inherited_method_is_not_registration():
    text = source('python').replace('class Router(Registrar):', 'class Router(Registrar):\n @property\n def add(self): return other')
    assert run(text, 'python')[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_unrelated_receiver_table_is_not_self_table(language):
    text = source(language).replace('self.handlers[route.key]', 'other.handlers[route.key]').replace('this.handlers[route.key]', 'other.handlers[route.key]')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_inheritance_is_resolved_across_explicit_imports(language):
    text = source(language)
    marker = 'class Router'
    base, router = text.split(marker, 1)
    if language == 'python':
        paths = ['pkg/base.py', 'pkg/router.py']
        router = 'from .base import Registrar\n' + marker + router
    else:
        extension = '.ts' if language == 'typescript' else '.js'
        paths = ['base'+extension, 'router'+extension]
        base = base.replace('class Registrar', 'export class Registrar')
        router = 'import {Registrar} from "./base";\n' + marker + router
    graph = link_project([lower_source(base, language, paths[0]), lower_source(router, language, paths[1])])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.dispatch-table#adapted', registry)], registry=registry)
    assert result['complete'] and len(result['matches']) == 1
