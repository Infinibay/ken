"""Executable-shaped, named fixtures for every GoF signature.

Names are deliberately unrelated to the pattern names; the second test matrix
alpha-renames them again. These are source inputs, never executed by Ken.
"""
PYTHON = {
"abstract-factory": '''
class Base:
    def a(self): pass
    def b(self): pass
class One: pass
class Two: pass
class Subject(Base):
    def a(self): return One()
    def b(self): return Two()
''',
"builder": '''
class Subject:
    def a(self, x):
        self.x = x
        return self
    def b(self, y):
        self.y = y
        return self
''',
"factory-method": '''
class Base:
    def make(self): pass
class Product: pass
class Subject(Base):
    def make(self): return Product()
''',
"prototype": '''
class Subject:
    def __init__(self, state): self.state = state
    def copy(self): return Subject(self.state)
''',
"singleton": '''
class Subject:
    value = None
    @classmethod
    def get(cls):
        if cls.value is None:
            cls.value = Subject()
        return cls.value
''',
"adapter": '''
class Contract:
    def request(self): pass
class Legacy:
    def run(self): pass
class Subject(Contract):
    def __init__(self, service: Legacy): self.service = service
    def request(self): return self.service.run()
''',
"bridge": '''
class Driver:
    def run(self): pass
class Fast(Driver): pass
class Slow(Driver): pass
class Base:
    def __init__(self, driver: Driver): self.driver = driver
    def run(self): return self.driver.run()
class Subject(Base): pass
''',
"composite": '''
class Component:
    def run(self): pass
class Subject(Component):
    def __init__(self): self.children: list[Component] = []
    def run(self):
        for child in self.children:
            child.run()
''',
"decorator": '''
class Contract:
    def run(self): pass
class Subject(Contract):
    def __init__(self, inner: Contract): self.inner = inner
    def run(self):
        print("before")
        return self.inner.run()
''',
"facade": '''
class One:
    def run(self): pass
class Two:
    def run(self): pass
class Subject:
    def __init__(self, one: One, two: Two):
        self.one = one
        self.two = two
    def run(self):
        self.one.run()
        self.two.run()
''',
"flyweight": '''
class Product:
    def __init__(self, key): self.key = key
class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        if key not in self.pool:
            self.pool[key] = Product(key)
        return self.pool[key]
''',
"proxy": '''
class Contract:
    def run(self): pass
class Subject(Contract):
    def __init__(self, inner: Contract): self.inner = inner
    def run(self, allowed):
        if allowed: return self.inner.run()
''',
"chain-of-responsibility": '''
class Handler:
    def run(self): pass
class Subject(Handler):
    def __init__(self, following: Handler): self.following = following
    def run(self, request):
        if request: return self.following.run()
''',
"command": '''
class Receiver:
    def act(self): pass
class Subject:
    def __init__(self, receiver: Receiver): self.receiver = receiver
    def execute(self): self.receiver.act()
''',
"interpreter": '''
class Expression:
    def evaluate(self, context): pass
class Subject(Expression):
    def __init__(self, child: Expression): self.child = child
    def evaluate(self, context): return self.child.evaluate(context)
''',
"iterator": '''
class Subject:
    def __iter__(self): return self
    def __next__(self):
        self.index = self.index + 1
        return self.index
''',
"mediator": '''
class One:
    def act(self): pass
    def changed(self, hub: Hub): hub.coordinate()
class Two:
    def act(self): pass
    def changed(self, hub: Hub): hub.coordinate()
class Hub:
    def __init__(self, one: One, two: Two):
        self.one = one
        self.two = two
    def coordinate(self):
        self.one.act()
        self.two.act()
''',
"memento": '''
class Snapshot:
    def __init__(self, state): self.state = state
class Subject:
    def __init__(self, state): self.state = state
    def save(self): return Snapshot(self.state)
    def restore(self, snapshot: Snapshot): self.state = snapshot.state
''',
"observer": '''
class Subject:
    def __init__(self): self.listeners = []
    def subscribe(self, listener): self.listeners.append(listener)
    def notify(self):
        for listener in self.listeners:
            listener.update()
''',
"state": '''
class Contract:
    def run(self): pass
class Concrete(Contract):
    def run(self): pass
class Subject:
    def __init__(self, state: Contract): self.state: Contract = state
    def run(self): self.state.run()
    def change(self): self.state = Concrete()
''',
"strategy": '''
class Contract:
    def run(self): pass
class First(Contract):
    def run(self): pass
class Second(Contract):
    def run(self): pass
class Subject:
    def __init__(self, strategy: Contract): self.strategy = strategy
    def run(self): return self.strategy.run()
''',
"template-method": '''
class Base:
    def run(self):
        self.step()
    def step(self): pass
class Subject(Base):
    def step(self): print("step")
''',
"visitor": '''
class Subject:
    def accept(self, visitor: Visitor): visitor.visit(self)
class Visitor:
    def visit(self, element: Subject): print(element)
''',
}

# Real syntax from seven additional frontends. All retain parameter/argument,
# storage and call relationships; no cross-language textual substitution in IR.
MULTILINGUAL = {
"javascript": (".js", '''
class Product {}
class Base { make() {} }
class Subject extends Base {
  constructor(value) { super(); this.value = value; }
  make() { return new Product(); }
  a(x) { this.x = x; return this; }
  b(y) { this.y = y; return this; }
  *items() { yield this.x; yield* [this.y]; }
}
export { Subject };
'''),
"typescript": (".ts", '''
class Product {}
class Base { make(): Product { return new Product(); } }
class Subject extends Base {
  x: number = 0; y: number = 0;
  value: string;
  constructor(value: string) { super(); this.value = value; }
  make(): Product { return new Product(); }
  a(x: number): Subject { this.x = x; return this; }
  b(y: number): Subject { this.y = y; return this; }
  *items() { yield this.x; yield* [this.y]; }
}
export { Subject };
'''),
"java": (".java", '''
class Product {}
class Base { Product make() { return new Product(); } }
class Subject extends Base {
  int x; int y;
  Product make() { return new Product(); }
  Subject a(int value) { this.x = value; return this; }
  Subject b(int value) { this.y = value; return this; }
}
'''),
"csharp": (".cs", '''
class Product {}
class Base { public virtual Product Make() { return new Product(); } }
class Subject : Base {
  int x; int y;
  public override Product Make() { return new Product(); }
  public Subject A(int value) { this.x = value; return this; }
  public Subject B(int value) { this.y = value; return this; }
}
'''),
"cpp": (".cpp", '''
class Product {};
class Base { public: virtual Product* make() { return new Product(); } };
class Subject : public Base {
  int x; int y;
  Product* make() { return new Product(); }
  Subject* a(int value) { this->x = value; return this; }
  Subject* b(int value) { this->y = value; return this; }
};
'''),
"go": (".go", '''
package sample
type Subject struct { x int; y int }
func (s *Subject) A(value int) *Subject { s.x = value; return s }
func (s *Subject) B(value int) *Subject { s.y = value; return s }
func launch() { go work() }
func work() {}
'''),
"rust": (".rs", '''
struct Subject { x: i32, y: i32 }
impl Subject {
 fn a(&mut self, value: i32) -> &mut Self { self.x = value; self }
 fn b(&mut self, value: i32) -> &mut Self { self.y = value; self }
}
'''),
}

PYTHON = {name: "from __future__ import annotations\n" + source for name, source in PYTHON.items()}
