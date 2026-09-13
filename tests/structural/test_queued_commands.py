"""Own source fixtures for queued command use and public batch-drain queries."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules, SavedRule

LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']


def source(language, mutation='positive', async_=False, property=False):
    if language == 'python':
        text = '''class Action:
 def perform(self): pass
class Sink:
 def write(self, value): pass
class Job(Action):
 sink: Sink
 def __init__(self, sink: Sink, value: int):
  self.sink = sink
  self.value = value
 def perform(self):
  self.sink.write(self.value)
class Queue:
 tasks: list[Action]
 other: list[Action]
 def __init__(self):
  self.tasks = []
  self.other = []
 def register(self, task: Action):
  self.tasks.append(task)
 def consume(self):
  for item in self.tasks:
   item.perform()
  self.tasks = []
def client(sink: Sink):
 queue = Queue()
 queue.register(Job(sink, 1))
'''
        if async_:
            text = text.replace('def perform', 'async def perform').replace('def consume', 'async def consume').replace('def write', 'async def write').replace('   item.perform()', '   await item.perform()').replace('  self.sink.write', '  await self.sink.write')
        changes = {
            'renamed': None,
            'no-registration': ('self.tasks.append(task)', 'pass'),
            'other-registration': ('self.tasks.append(task)', 'self.other.append(task)'),
            'other-iteration': ('for item in self.tasks:', 'for item in self.other:'),
            'other-item': ('item.perform()', 'other.perform()'),
            'with-argument': ('item.perform()', 'item.perform(1)'),
            'no-reset': ('  self.tasks = []\ndef client', '  pass\ndef client'),
            'other-reset': ('  self.tasks = []\ndef client', '  self.other = []\ndef client'),
            'reset-before': ('  for item in self.tasks:\n   item.perform()\n  self.tasks = []', '  self.tasks = []\n  for item in self.tasks:\n   item.perform()'),
            'reset-in-branch': ('  self.tasks = []\ndef client', '  if flag:\n   self.tasks = []\ndef client'),
            'return-before-reset': ('  self.tasks = []\ndef client', '  return\n  self.tasks = []\ndef client'),
            'rebound-input': ('  self.tasks.append(task)', '  task = None\n  self.tasks.append(task)'),
            'rebound-item': ('   item.perform()', '   item = None\n   item.perform()'),
            'wrong-action': ('item.perform()', 'item.inspect()'),
            'receiver-overwritten': ('  self.sink = sink', '  self.sink = sink\n  self.sink = None'),
            'without-receiver': ('  self.sink.write(self.value)', '  pass'),
        }
    else:
        js = language == 'javascript'; ts = language == 'typescript'; java = language == 'java'
        if js or ts:
            contract = 'class Action { perform() {} }' if js else 'interface Action { perform(): void; }'
            heritage = 'extends' if js else 'implements'
            fields = '' if js else 'sink: Sink; value: number;'
            constructor = 'constructor(sink, value)' if js else 'constructor(sink: Sink, value: number)'
            setup = ('super(); ' if js else '') + 'this.sink = sink; this.value = value;'
            if property:
                fields = ''; constructor = 'constructor(private sink: Sink, private value: number)'; setup = ''
            write = 'write(value)' if js else 'write(value: number)'
            perform = 'perform()'; consume = 'consume()'
            queue_fields = '' if js else 'tasks: Action[]; other: Action[];'
            queue_ctor = 'constructor() {this.tasks=[]; this.other=[];}'
            register = 'register(task)' if js else 'register(task: Action)'
            insert = 'this.tasks.push(task);'
            loop = 'for (const item of this.tasks)'
            clear = 'this.tasks = [];'
            client = 'function client(sink) { const queue = new Queue(); queue.register(new Job(sink, 1)); }'
        else:
            contract = 'interface Action { void perform(); }'
            heritage = 'implements' if java else ':'
            fields = 'Sink sink; int value;'
            constructor = 'public Job(Sink sink, int value)'; setup = 'this.sink = sink; this.value = value;'
            write = 'public void write(int value)'; perform = 'public void perform()'; consume = 'public void consume()'
            queue_fields = 'List<Action> tasks; List<Action> other;'
            queue_ctor = 'public Queue() {this.tasks=new List<Action>(); this.other=new List<Action>();}'
            if java: queue_ctor=queue_ctor.replace('new List<Action>()', 'new ArrayList<Action>()')
            register = 'public void register(Action task)'
            insert = 'this.tasks.add(task);' if java else 'this.tasks.Add(task);'
            loop = 'for (Action item : this.tasks)' if java else 'foreach (Action item in this.tasks)'
            clear = 'this.tasks.clear();' if java else 'this.tasks.Clear();'
            client = 'class Client { void start(Sink sink) { Queue queue = new Queue(); queue.register(new Job(sink, 1)); } }'
        if async_:
            assert not java
            if js or ts:
                perform = 'async '+perform; consume = 'async '+consume; write = 'async '+write
                if ts: contract = contract.replace('void;', 'Promise<void>;')
            else:
                perform=perform.replace('void','async Task');consume=consume.replace('void','async Task');write=write.replace('void','async Task');contract=contract.replace('void','Task')
        await_ = 'await ' if async_ else ''
        text = f'''{contract}
class Sink {{ {write} {{ }} }}
class Job {heritage} Action {{ {fields}
 {constructor} {{ {setup} }}
 {perform} {{ {await_}this.sink.write(this.value); }}
}}
class Queue {{ {queue_fields}
 {queue_ctor}
 {register} {{ {insert} }}
 {consume} {{ {loop} {{ {await_}item.perform(); }} {clear} }}
}}
{client}
'''
        changes = {
            'no-registration': (insert, ''),
            'other-registration': (insert, insert.replace('this.tasks', 'this.other')),
            'other-iteration': (loop, loop.replace('this.tasks', 'this.other')),
            'other-item': ('item.perform()', 'other.perform()'),
            'with-argument': ('item.perform()', 'item.perform(1)'),
            'no-reset': (f'{clear} }}\n}}', '}\n}'),
            'other-reset': (f'{clear} }}\n}}', clear.replace('this.tasks','this.other')+' }\n}'),
            'reset-before': (f'{loop} {{ item.perform(); }} {clear}', f'{clear} {loop} {{ item.perform(); }}'),
            'reset-in-branch': (f'{clear} }}\n}}', f'if (flag) {{ {clear} }} }}\n}}'),
            'return-before-reset': (f'{clear} }}\n}}', f'return; {clear} }}\n}}'),
            'rebound-input': (insert, 'task = null; '+insert),
            'rebound-item': ('item.perform();', 'item = null; item.perform();'),
            'wrong-action': ('item.perform()', 'item.inspect()'),
            'receiver-overwritten': (f'{constructor} {{ {setup} }}', f'{constructor} {{ {setup} this.sink = null; }}'),
            'without-receiver': (f'{await_}this.sink.write(this.value);', ''),
        }
    if mutation not in {'positive','renamed'}:
        old,new=changes[mutation];assert old in text,(mutation,language);text=text.replace(old,new)
    if mutation == 'renamed':
        for old,new in [('Job','Envelope'),('Action','Work'),('Queue','Batch'),('perform','invoke'),('tasks','pending'),('register','addWork'),('consume','flush')]:
            text=re.sub(r'\b'+old+r'\b',new,text)
    return text


def detect(text,language):
    graph=link_project([lower_source(text,language,'queue-example')]);assert not graph.diagnostics
    rules=builtin_rules();out=execute_rules(graph,[named_rule('command#queued-object',rules),named_rule('architecture.batch-work-queue',rules)],registry=rules)
    assert out['complete'],out
    return graph,{m['id'] for m in out['matches']}


MUTATIONS=['positive','renamed','no-registration','other-registration','other-iteration','other-item',
           'with-argument','no-reset','other-reset','reset-before','reset-in-branch','return-before-reset',
           'rebound-input','rebound-item','wrong-action','receiver-overwritten','without-receiver']


@pytest.mark.parametrize('language,property',[(lang,False) for lang in LANGUAGES]+[('typescript',True)])
@pytest.mark.parametrize('mutation',MUTATIONS)
def test_queued_command_and_batch_work_correlations(language,property,mutation):
    _,ids=detect(source(language,mutation,property=property),language)
    assert ('command#queued-object' in ids)==(mutation in {'positive','renamed'}),ids
    assert ('architecture.batch-work-queue' in ids)==(mutation in {'positive','renamed','wrong-action','receiver-overwritten','without-receiver'}),ids


@pytest.mark.parametrize('language',['python','javascript','typescript','csharp'])
def test_awaited_commands_preserve_discarded_activation(language):
    _,ids=detect(source(language,async_=True),language)
    assert ids=={'command#queued-object','architecture.batch-work-queue'}


def test_untyped_registration_requires_observed_caller_and_exposes_public_drain():
    text=source('javascript');text=text[:text.index('function client')]
    graph,ids=detect(text,'javascript')
    assert ids=={'architecture.batch-work-queue'}
    query='''query usage {
      match "architecture.batch-work-queue.drain"(queue:$queue,item:$item,dispatch:$dispatch,reset:$reset);
      emit $queue,$item,$dispatch,$reset;
    }'''
    out=execute_rules(graph,[SavedRule('usage',query)],registry=builtin_rules())
    assert out['complete'] and len(out['matches'])==1
