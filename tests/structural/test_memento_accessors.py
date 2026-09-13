"""Round-trip snapshot state through constructors/getters and nominal contracts."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']


def source(language, *, contract=False, mutation='none'):
    init = ['self.saved=state']
    getter = ['return self.saved']
    save = ['result=Snapshot(self.state)', 'return result']
    restore = ['self.state=s.get()']
    if mutation == 'wrong-field': restore = ['self.other=s.get()']
    if mutation == 'wrong-getter': getter = ['return self.other']
    if mutation == 'constant-getter': getter = ['return 0']
    if mutation == 'getter-overwrite': getter = ['self.saved=0', 'return self.saved']
    if mutation == 'getter-local-overwrite': getter = ['result=self.saved', 'result=0', 'return result']
    if mutation == 'constructor-overwrite': init += ['self.saved=0']
    if mutation == 'constructor-rebind': init = ['state=0', 'self.saved=state']
    if mutation == 'restore-overwrite': restore += ['self.state=0']
    if mutation == 'restore-rebind': restore = ['s=Snapshot(0)', *restore]
    if mutation == 'abandoned-snapshot': save = ['unused=Snapshot(self.state)', 'result=Snapshot(0)', 'return result']
    if mutation == 'no-transfer': init = ['self.saved=0']
    if mutation == 'no-use': restore = ['s.get()', 'self.state=0']
    if mutation == 'receiver-escape': init += ['helper(self)']
    if language == 'python':
        def body(statements): return '\n'.join('  '+s for s in statements)+'\n'
        base = 'class Contract:\n def get(self): pass\n' if contract else ''
        text = base + 'class Snapshot' + ('(Contract)' if contract else '') + ':\n'
        text += ' def __init__(self,state):\n'+body(init)+' def get(self):\n'+body(getter)
        text += 'class Originator:\n def __init__(self): self.state=0\n def save(self):\n'+body(save)
        text += ' def restore(self,s:'+('Contract' if contract else 'Snapshot')+'):\n'+body(restore)
    else:
        typed = language in {'java', 'csharp'}
        def body(statements):
            converted = []
            for s in statements:
                s=s.replace('self', 'this').replace('Snapshot(', 'new Snapshot(')
                if s.startswith(('result=', 'unused=')):
                    local_type = 'Snapshot' if 'new Snapshot' in s else 'int'
                    if s == 'result=0' and 'result=self.saved' in statements:
                        converted.append(s); continue
                    s = (local_type+' ' if typed else 'let ') + s
                converted.append(s)
            return ';'.join(converted)+';'
        if typed:
            base = 'interface Contract{int get();}' if contract else ''
            extends = (' implements Contract' if language=='java' else ':Contract') if contract else ''
            text=base+'class Snapshot'+extends+'{int saved;int other;public Snapshot(int state){'+body(init)+'}public int get(){'+body(getter)+'}}'
            text+='class Originator{int state;int other;public Snapshot save(){'+body(save)+'}public void restore('+('Contract' if contract else 'Snapshot')+' s){'+body(restore)+'}}'
        else:
            base = 'interface Contract{get():number;}' if contract and language=='typescript' else ''
            extends = ' implements Contract' if contract and language=='typescript' else ''
            text=base+'class Snapshot'+extends+'{saved=0;other=0;constructor(state){'+body(init)+'}get(){'+body(getter)+'}}'
            annotation = ':'+('Contract' if contract else 'Snapshot') if language=='typescript' else ''
            text+='class Originator{state=0;other=0;save(){'+body(save)+'}restore(s'+annotation+'){'+body(restore)+'}}'
            if language=='javascript':
                text += 'let origin=new Originator(); origin.restore(new Snapshot(10));'
    if mutation == 'rename':
        for old,new in [('Snapshot','Envelope'),('Originator','Editor'),('Contract','Readable'),('saved','payload'),('state','content'),('get','read'),('save','remember'),('restore','recover')]:
            text=text.replace(old,new)
    return text


def run(language, **kwargs):
    graph=link_project([lower_source(source(language,**kwargs),language,'memento')])
    assert not graph.diagnostics
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('memento#accessor-snapshot',registry)],registry=registry)
    assert result['complete']
    return graph,result['matches']


@pytest.mark.parametrize('language,contract',[(language,contract) for language in LANGUAGES
                                           for contract in [False,True] if language!='javascript' or not contract])
@pytest.mark.parametrize('mutation',['none','rename','wrong-field','wrong-getter','constant-getter','getter-overwrite',
    'getter-local-overwrite','constructor-overwrite','constructor-rebind','restore-overwrite','restore-rebind',
    'abandoned-snapshot','no-transfer','no-use','receiver-escape'])
def test_accessor_state_round_trip(language,contract,mutation):
    _,matches=run(language,contract=contract,mutation=mutation)
    assert bool(matches)==(mutation in {'none','rename'})


def test_typescript_exported_interface_resolves_between_files():
    text=source('typescript',contract=True)
    boundary=text.index('class Originator')
    snapshot=text[:boundary].replace('interface Contract','export interface Contract').replace('class Snapshot','export class Snapshot')
    editor='import {Snapshot,Contract} from "./snapshot";'+text[boundary:]
    graph=link_project([lower_source(snapshot,'typescript','snapshot.ts'),lower_source(editor,'typescript','editor.ts')])
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('memento',registry)],registry=registry)
    assert result['complete'] and len(result['matches'])==1


def test_untyped_restore_needs_observed_snapshot_input():
    text=source('javascript').replace('origin.restore(new Snapshot(10));','')
    graph=link_project([lower_source(text,'javascript','no-caller')])
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('memento#accessor-snapshot',registry)],registry=registry)
    assert result['complete'] and not result['matches']


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('matching',[False,True])
def test_constructor_argument_position_must_reach_the_getter_field(language,matching):
    text=source(language)
    if language=='python':
        text=text.replace('__init__(self,state)', '__init__(self,other,state)' if matching else '__init__(self,state,other)')
    elif language in {'javascript','typescript'}:
        text=text.replace('constructor(state)', 'constructor(other,state)' if matching else 'constructor(state,other)')
    else:
        text=text.replace('Snapshot(int state)', 'Snapshot(int other,int state)' if matching else 'Snapshot(int state,int other)')
    if not matching:
        text=text.replace('saved=state','saved=other')
    for receiver in ['self','this']:
        text=text.replace('Snapshot('+receiver+'.state)', 'Snapshot(0,'+receiver+'.state)' if matching else 'Snapshot('+receiver+'.state,0)')
    text=text.replace('Snapshot(10)', 'Snapshot(0,10)' if matching else 'Snapshot(10,0)')
    graph=link_project([lower_source(text,language,'position')])
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('memento#accessor-snapshot',registry)],registry=registry)
    assert result['complete'] and bool(result['matches'])==matching


@pytest.mark.parametrize('extra',['alias=self\n  helper(alias)','helper([self])','helper({"value":self})',
                                  'self.saved=0','self.saved+=1'])
def test_python_constructor_alias_and_container_escape(extra):
    text=source('python').replace('self.saved=state', 'self.saved=state\n  '+extra)
    graph=link_project([lower_source(text,'python','escape')])
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('memento#accessor-snapshot',registry)],registry=registry)
    assert result['complete'] and not result['matches']
