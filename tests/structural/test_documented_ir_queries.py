"""The operational IR guide's KenQL examples run against actual lowered source."""
import re
from pathlib import Path
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import SavedRule, builtin_rules, execute_rules


DOC = Path(__file__).resolve().parents[2] / 'docs/structural-ir.md'
QUERIES = re.findall(r'```kenql\n(.*?)\n```', DOC.read_text(), re.S)


@pytest.mark.parametrize('query', QUERIES)
def test_ir_guide_example(query):
    source='def scan(values: dict[str, list[int]], items):\n for item in list(items):\n  if item <= 10:\n   continue\n  item.next()\n return items\n'
    source += 'def endpoint(context):\n request=context.request\n return request.route.key\n'
    source += 'class Record:\n payload: int\n def copy(self):\n  result=Record()\n  result.payload=self.payload\n  return result\n'
    source += 'class FactoryClient:\n def __init__(self,create): self.create=create\n def build(self): return self.create()\n'
    source += 'class Snapshot:\n def __init__(self, value):\n  self.value=value\nSnapshot(1)\n'
    source += 'class Batch:\n def __init__(self): self.tasks=[]\n def add(self,task): self.tasks.append(task)\n def run(self):\n  for item in self.tasks: item.perform()\n  self.tasks=[]\n'
    source += 'class Product:\n def __init__(self): self.value=0\nclass Builder:\n def __init__(self): self.product=Product()\n def configure(self,value): self.product.value=value\n def finish(self): return self.product\n'
    source += 'class SnapshotBuilder:\n def configure(self,value): self.state=value\n def finish(self): return Snapshot(self.state)\n'
    source += 'class Memo: pass\nclass CacheProvider:\n def __init__(self): self.cache=Memo()\n def read(self,source,key):\n  if self.cache.contains(key): return self.cache.get(key)\n  value=source.load(key)\n  self.cache.set(key,value)\n  return value\n'
    source += 'def get_cached(cache,repository,key):\n value=cache.get(key)\n if value is None:\n  value=repository.load(key)\n  cache.set(key,value)\n return value\n'
    source += 'class Driver:\n def run(self): pass\nclass FirstDriver(Driver):\n def run(self): return 1\nclass SecondDriver(Driver):\n def run(self): return 2\nclass View:\n def render(self): pass\nclass PeerView(View):\n pass\nclass RefinedView(View):\n def __init__(self,driver:Driver): self.driver=driver\n def render(self): return self.driver.run()\n'
    rust="#[derive(Clone)] struct Product<'a>{value:&'a str} fn copy<'a>(value:Product<'a>){value.clone();}"
    rust+=' fn invoke_callback(callback:fn(i32)->i32,value:i32)->i32{(callback)(value)}'
    cpp='class NativeBackend{};class NativeHolder{const NativeBackend *backend;public:NativeHolder(const NativeBackend*input):backend(input){}};class NativeContract{public:virtual void execute(int)=0;};class NativeImpl:public NativeContract{public:void execute(int){}};'
    java='class SharedRegistry{private SharedRegistry(){}static final SharedRegistry current=new SharedRegistry();static SharedRegistry acquire(){return current;}}class RegistryClient{SharedRegistry run(){return SharedRegistry.acquire();}}'
    java+='class LazyDefaults{static LazyDefaults current;int count;static LazyDefaults get(){if(current==null){current=new LazyDefaults();}return current;}}'
    source+='class LazyRegistry:\n value=None\n @classmethod\n def acquire(cls):\n  if not (cls.value is not None):\n   cls.value=LazyRegistry()\n  return cls.value\n'
    source+='def mixify(base):\n class Enhanced(base):\n  def extra(self): return 1\n return Enhanced\nmixify(Driver)\n'
    ts='class Component{}const Local=class Hidden extends Component{render(){return 1;}};const asserted=Local as unknown;'
    graph=link_project([lower_source(source,'python','documented.py'),lower_source(rust,'rust','documented.rs'),lower_source(cpp,'cpp','documented.cpp'),lower_source(java,'java','documented.java'),lower_source(ts,'typescript','documented.ts')])
    result=execute_rules(graph,[SavedRule('documented',query)],registry=builtin_rules())
    assert result['complete'] and result['matches'], result


def test_operational_examples_remain_present():
    assert len(QUERIES)>=6
