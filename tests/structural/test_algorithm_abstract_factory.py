"""Abstract Factory: categories, selected family and creation-flow obligations.

Only source parsing is exercised. The current rule recognizes factory shape;
the explicitly marked refinement needs family metadata, not class-name guesses.
"""
import re

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


SOURCES = {
    'python': '''class Button: pass
class Panel: pass
class OceanButton(Button): pass
class OceanPanel(Panel): pass
class LandButton(Button): pass
class LandPanel(Panel): pass
class Provider:
 def button(self) -> Button: pass
 def panel(self) -> Panel: pass
class Ocean(Provider):
 def button(self) -> Button:
  return OceanButton()
 def panel(self) -> Panel:
  return OceanPanel()
class Land(Provider):
 def button(self) -> Button:
  return LandButton()
 def panel(self) -> Panel:
  return LandPanel()
def configure(provider: Provider):
 button = provider.button()
 panel = provider.panel()
 return (button, panel)
''',
    'java': '''class Button {} class Panel {}
class OceanButton extends Button {} class OceanPanel extends Panel {}
class LandButton extends Button {} class LandPanel extends Panel {}
abstract class Provider { abstract Button button(); abstract Panel panel(); }
class Ocean extends Provider {
 Button button(){ return new OceanButton(); }
 Panel panel(){ return new OceanPanel(); }
}
class Land extends Provider {
 Button button(){ return new LandButton(); }
 Panel panel(){ return new LandPanel(); }
}
class Client { Object[] configure(Provider provider){
 Button button = provider.button(); Panel panel = provider.panel();
 return new Object[]{button, panel};
} }
''',
    'typescript': '''class Button {} class Panel {}
class OceanButton extends Button {} class OceanPanel extends Panel {}
class LandButton extends Button {} class LandPanel extends Panel {}
interface Provider { button(): Button; panel(): Panel; }
class Ocean implements Provider {
 button(): Button { return new OceanButton(); }
 panel(): Panel { return new OceanPanel(); }
}
class Land implements Provider {
 button(): Button { return new LandButton(); }
 panel(): Panel { return new LandPanel(); }
}
function configure(provider: Provider): [Button, Panel] {
 const button = provider.button(); const panel = provider.panel();
 return [button, panel];
}
''',
}


def instrument(source, language):
    if language == 'python':
        return source.replace('  return ', '  metric = 1 + 2\n  print(metric)\n  return ').replace(' panel = provider.panel()', ' print(123)\n panel = provider.panel()')
    marker = 'int metric = 1 + 2; System.out.println(metric);' if language == 'java' else 'const metric = 1 + 2; console.log(metric);'
    source = source.replace('return new Ocean', marker + ' return new Ocean').replace('return new Land', marker + ' return new Land')
    if language == 'java':
        return source.replace('Panel panel = provider.panel()', 'System.out.println(123); Panel panel = provider.panel()')
    return source.replace('const panel = provider.panel()', 'console.log(123); const panel = provider.panel()')


def detect(source, language):
    graph = link_project([lower_source(source, language, 'family.' + {'python': 'py', 'java': 'java', 'typescript': 'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('abstract-factory', registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return {graph.entities[m['bindings']['$unit']].name for m in result['matches']}


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mode', ['baseline', 'noise', 'renamed'])
def test_two_categories_and_two_family_providers_survive_noise(language, mode):
    source = SOURCES[language]
    if mode != 'baseline':
        source = instrument(source, language)
    if mode == 'renamed':
        for old, new in [('Ocean', 'First'), ('Land', 'Second'), ('Button', 'PartA'), ('Panel', 'PartB')]:
            source = re.sub(r'\b' + old + r'\b', new, source)
    assert detect(source, language) == ({'First', 'Second'} if mode == 'renamed' else {'Ocean', 'Land'})


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['no-second-product', 'same-category', 'no-contract'])
def test_missing_factory_obligation_rejects_only_affected_provider(language, mutation):
    source = instrument(SOURCES[language], language)
    if mutation == 'no-second-product':
        source = source.replace('return OceanPanel()', 'return None').replace('return new OceanPanel()', 'return null')
    elif mutation == 'same-category':
        if language == 'python':
            source = source.replace('class OceanPanel(Panel)', 'class OceanPanel(Button)')
        else:
            source = source.replace('class OceanPanel extends Panel', 'class OceanPanel extends Button')
        # The fixtures are parsed, not type-checked: this intentionally breaks
        # the declared category contract, preserving the surrounding syntax.
    else:
        source = source.replace('class Ocean(Provider)', 'class Ocean').replace('class Ocean extends Provider', 'class Ocean').replace('class Ocean implements Provider', 'class Ocean')
    assert detect(source, language) == {'Land'}


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.xfail(strict=True, reason='Uniform-family refinement needs explicit product-family compatibility evidence')
def test_requested_uniform_family_refinement_rejects_mixed_provider(language):
    # Fixture family membership is intentional external ground truth. The base
    # Abstract Factory rule does not implement this stronger selectable contract.
    source = instrument(SOURCES[language], language).replace('return OceanPanel()', 'return LandPanel()').replace('return new OceanPanel()', 'return new LandPanel()')
    assert detect(source, language) == {'Land'}
