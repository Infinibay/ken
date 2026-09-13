"""An invoker and no-argument delegation alone also describe getters and copies."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCES={
 'python':'''class Receiver:
 def act(self):
  self.state=1
  return self.state
class Action:
 def __init__(self, receiver:Receiver): self.receiver=receiver
 def execute(self): return self.receiver.act()
class Invoker:
 def invoke(self, command:Action): return command.execute()
''',
 'java':'''class Receiver{int state;int act(){this.state=1;return this.state;}}
class Action{Receiver receiver;Action(Receiver receiver){this.receiver=receiver;}int execute(){return this.receiver.act();}}
class Invoker{int invoke(Action command){return command.execute();}}''',
 'typescript':'''class Receiver{state:number;act():number{this.state=1;return this.state;}}
class Action{receiver:Receiver;constructor(receiver:Receiver){this.receiver=receiver;}execute():number{return this.receiver.act();}}
class Invoker{invoke(command:Action):number{return command.execute();}}''',
 'csharp':'''class Receiver{int state;int act(){this.state=1;return this.state;}}
class Action{Receiver receiver;Action(Receiver receiver){this.receiver=receiver;}int execute(){return this.receiver.act();}}
class Invoker{int invoke(Action command){return command.execute();}}''',
}


def run(source,language):
    graph=link_project([lower_source(source,language,'sample')])
    assert not graph.diagnostics
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('command#command-object',registry)],registry=registry)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_returning_state_changing_action(language):
    assert run(SOURCES[language],language)


@pytest.mark.parametrize('language',SOURCES)
def test_returning_a_pure_getter_is_not_this_command_variant(language):
    text=SOURCES[language].replace('  self.state=1\n','').replace('this.state=1;','')
    assert run(text,language)==[]


@pytest.mark.parametrize('language',SOURCES)
def test_action_names_do_not_select_commands(language):
    text=SOURCES[language].replace('Action','Message').replace('execute','copy').replace('act','read')
    assert run(text,language)


@pytest.mark.parametrize('language',SOURCES)
def test_local_assignment_in_getter_is_not_receiver_state(language):
    text=SOURCES[language].replace('self.state=1','local=1').replace('this.state=1;', 'int local=1;' if language in {'java','csharp'} else 'let local=1;')
    assert run(text,language)==[]


def test_python_copying_receiver_value_into_new_object_is_not_command():
    text=SOURCES['python'].replace(' def execute(self): return self.receiver.act()',
        ' def execute(self):\n  result=Action(self.receiver)\n  result.saved=self.receiver.act()\n  return result')
    assert run(text,'python')==[]


def test_clone_method_does_not_hide_actual_action():
    text=SOURCES['python'].replace('class Invoker:',
        ' def copy(self):\n  result=Action(self.receiver)\n  result.saved=self.receiver.act()\n  return result\nclass Invoker:')
    assert run(text,'python')


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['none','other-slot','not-retained','immediate'])
def test_retained_object_can_encapsulate_pure_calculation(language,mutation):
    text=SOURCES[language].replace('  self.state=1\n','').replace('this.state=1;','')
    if language=='python':
        text=text[:text.index('class Invoker:')]+'''class Invoker:
 def set(self, command:Action): self.saved=command
 def invoke(self): return self.saved.execute()
'''
    elif language=='typescript':
        text=text[:text.index('class Invoker')]+'''class Invoker{saved:Action;
 set(command:Action):void{this.saved=command;}
 invoke():number{return this.saved.execute();}}'''
    else:
        text=text[:text.index('class Invoker')]+'''class Invoker{Action saved;
 void set(Action command){this.saved=command;}
 int invoke(){return this.saved.execute();}}'''
    if mutation=='other-slot':
        text=text.replace('saved.execute()', 'other.execute()')
    elif mutation=='not-retained':
        text=text.replace('self.saved=command','pass').replace('this.saved=command;','')
    elif mutation=='immediate':
        text=text.replace('self.saved=command','command.execute()').replace('this.saved=command;','command.execute();')
    graph=link_project([lower_source(text,language,'sample')])
    assert not graph.diagnostics
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule('command',registry)],registry=registry)
    assert result['complete']
    assert bool(result['matches'])==(mutation=='none')
