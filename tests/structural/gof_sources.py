"""Source fixtures for canonical GoF queries; parsed, never executed.

Python uses duck typing and explicit annotations; Java uses nominal contracts,
static storage, typed collections and virtual slots. Fixture names are arbitrary.
These examples demonstrate structural evidence, not fully functional libraries.
"""
from .examples import PYTHON as LEGACY_PYTHON

PYTHON = dict(LEGACY_PYTHON)
PYTHON['command'] += '\nclass Invoker:\n def run(self, command: Subject): command.execute()\n'
PYTHON['builder'] = '''
class Product:
 def __init__(self, x): self.x = x
class Subject:
 def size(self, x): self.x = x
 def finish(self): return Product(self.x)
'''
JAVA = {
'abstract-factory': '''
abstract class Base { abstract One a(); abstract Two b(); }
class One {} class Two {}
class Subject extends Base { One a(){return new One();} Two b(){return new Two();} }
''',
'builder': '''
class Product { Product(int value){} }
class Subject { int value; Subject size(int x){this.value=x;return this;} Product finish(){return new Product(this.value);} }
''',
'factory-method': '''
abstract class Base { abstract Product make(); }
class Product {}
class Subject extends Base { Product make(){return new Product();} }
''',
'prototype': '''
class Subject { int value; Subject(int x){this.value=x;} Subject duplicate(){return new Subject(this.value);} }
''',
'singleton': '''
class Subject { static Subject instance=null;
 static Subject shared(){if(Subject.instance==null){Subject.instance=new Subject();}return Subject.instance;}
}
''',
'adapter': '''
interface Contract { int request(); }
class Legacy { int perform(){return 1;} }
class Subject implements Contract { Legacy service;
 Subject(Legacy service){this.service=service;}
 public int request(){return this.service.perform();}
}
''',
'bridge': '''
interface Driver { int run(); }
class First implements Driver {public int run(){return 1;}}
class Second implements Driver {public int run(){return 2;}}
class Base {Driver driver; Base(Driver driver){this.driver=driver;} int run(){return this.driver.run();}}
class Subject extends Base {Subject(Driver driver){super(driver);}}
''',
'composite': '''
import java.util.List;
interface Component { void run(); }
class Subject implements Component { List<Component> children;
 Subject(List<Component> children){this.children=children;}
 public void run(){for(Component child:this.children){child.run();}}
}
''',
'decorator': '''
interface Contract {int run();}
class Subject implements Contract {Contract inner;
 Subject(Contract inner){this.inner=inner;}
 public int run(){System.out.println("before");return this.inner.run();}
}
''',
'facade': '''
class First {void run(){}} class Second {void run(){}}
class Subject {First one; Second two;
 Subject(First one,Second two){this.one=one;this.two=two;}
 void run(){this.one.run();this.two.run();}
}
''',
'flyweight': '''
class Product {Product(int key){}}
class Subject {Product[] pool=new Product[100];
 Product get(int key){if(this.pool[key]==null){this.pool[key]=new Product(key);}return this.pool[key];}
}
''',
'proxy': '''
interface Contract {int run(boolean allowed);}
class Subject implements Contract {Contract inner;
 Subject(Contract inner){this.inner=inner;}
 public int run(boolean allowed){if(allowed){return this.inner.run(allowed);}return 0;}
}
''',
'chain-of-responsibility': '''
interface Handler {void run(boolean request);}
class Subject implements Handler {Handler following;
 Subject(Handler following){this.following=following;}
 public void run(boolean request){if(request){this.following.run(request);}}
}
''',
'command': '''
class Receiver {void act(){}}
class Subject {Receiver receiver; Subject(Receiver receiver){this.receiver=receiver;} void execute(){this.receiver.act();}}
class Invoker {void run(Subject command){command.execute();}}
''',
'interpreter': '''
interface Expression {int evaluate(int context);}
class Subject implements Expression {Expression child;
 Subject(Expression child){this.child=child;}
 public int evaluate(int context){return this.child.evaluate(context);}
}
''',
'iterator': '''
class Subject {int index=0;
 boolean hasNext(){return this.index<10;}
 int next(){this.index=this.index+1;return this.index;}
}
''',
'mediator': '''
class First {void act(){} void changed(Hub hub){hub.coordinate();}}
class Second {void act(){} void changed(Hub hub){hub.coordinate();}}
class Hub {First one;Second two;
 Hub(First one,Second two){this.one=one;this.two=two;}
 void coordinate(){this.one.act();this.two.act();}
}
''',
'memento': '''
class Snapshot {int value;Snapshot(int value){this.value=value;}}
class Subject {int value;
 Snapshot save(){return new Snapshot(this.value);}
 void restore(Snapshot snapshot){this.value=snapshot.value;}
}
''',
'observer': '''
import java.util.List;
import java.util.ArrayList;
interface Listener {void update();}
class Subject {List<Listener> listeners=new ArrayList<>();
 void subscribe(Listener listener){this.listeners.add(listener);}
 void notifyAllListeners(){for(Listener listener:this.listeners){listener.update();}}
}
''',
'state': '''
interface Contract {void run();}
class Concrete implements Contract {public void run(){}}
class Subject {Contract state;
 Subject(Contract state){this.state=state;}
 void run(){this.state.run();}
 void change(){this.state=new Concrete();}
}
''',
'strategy': '''
interface Contract {int run();}
class First implements Contract {public int run(){return 1;}}
class Second implements Contract {public int run(){return 2;}}
class Subject {Contract strategy;
 Subject(Contract strategy){this.strategy=strategy;}
 int run(){return this.strategy.run();}
}
''',
 'template-method': '''
abstract class Base {void run(){this.step();}abstract void step();}
class Subject extends Base {void step(){System.out.println("step");}}
''',
'visitor': '''
class Subject {void accept(Visitor visitor){visitor.visit(this);}}
class Visitor {void visit(Subject element){System.out.println(element);}}
''',
}

TYPESCRIPT = {
'abstract-factory': '''
interface Base { a(): One; b(): Two; }
class One {} class Two {}
class Subject implements Base { a():One{return new One();} b():Two{return new Two();} }
''',
'builder': '''
class Product {constructor(value:number){}}
class Subject {value:number=0; size(x:number):this{this.value=x;return this;} finish():Product{return new Product(this.value);} }
''',
'factory-method': '''
interface Base {make():Product;}
class Product {}
class Subject implements Base {make():Product{return new Product();}}
''',
'prototype': '''
class Subject {value:number;constructor(x:number){this.value=x;} duplicate():Subject{return new Subject(this.value);}}
''',
'singleton': '''
class Subject {static instance:Subject|null=null;
 static shared():Subject {if(Subject.instance===null){Subject.instance=new Subject();}return Subject.instance;}
}
''',
'adapter': '''
interface Contract {request():number;}
class Legacy {perform():number{return 1;}}
class Subject implements Contract {service:Legacy;
 constructor(service:Legacy){this.service=service;}
 request():number{return this.service.perform();}
}
''',
'bridge': '''
interface Driver {run():number;}
class First implements Driver {run():number{return 1;}}
class Second implements Driver {run():number{return 2;}}
class Base {driver:Driver;constructor(driver:Driver){this.driver=driver;}run():number{return this.driver.run();}}
class Subject extends Base {}
''',
'composite': '''
interface Component {run():void;}
class Subject implements Component {children:Array<Component>=[];
 run():void{for(const child of this.children){child.run();}}
}
''',
'decorator': '''
interface Contract {run():number;}
class Subject implements Contract {inner:Contract;
 constructor(inner:Contract){this.inner=inner;}
 run():number{console.log("before");return this.inner.run();}
}
''',
'facade': '''
class First {run():void{}} class Second {run():void{}}
class Subject {one:First;two:Second;
 constructor(one:First,two:Second){this.one=one;this.two=two;}
 run():void{this.one.run();this.two.run();}
}
''',
'flyweight': '''
class Product {constructor(key:number){}}
class Subject {pool:Array<Product>=[];
 get(key:number):Product{if(!this.pool[key]){this.pool[key]=new Product(key);}return this.pool[key];}
}
''',
'proxy': '''
interface Contract {run(allowed:boolean):number;}
class Subject implements Contract {inner:Contract;
 constructor(inner:Contract){this.inner=inner;}
 run(allowed:boolean):number{if(allowed){return this.inner.run(allowed);}return 0;}
}
''',
'chain-of-responsibility': '''
interface Handler {run(request:boolean):void;}
class Subject implements Handler {following:Handler;
 constructor(following:Handler){this.following=following;}
 run(request:boolean):void{if(request){this.following.run(request);}}
}
''',
'command': '''
class Receiver {act():void{}}
class Subject {receiver:Receiver;constructor(receiver:Receiver){this.receiver=receiver;}execute():void{this.receiver.act();}}
class Invoker {run(command:Subject):void{command.execute();}}
''',
'interpreter': '''
interface Expression {evaluate(context:number):number;}
class Subject implements Expression {child:Expression;
 constructor(child:Expression){this.child=child;}
 evaluate(context:number):number{return this.child.evaluate(context);}
}
''',
'iterator': '''
export function* sequence(values:number[]):Generator<number>{
 yield* values;
}
''',
'mediator': '''
class First {act():void{}changed(hub:Hub):void{hub.coordinate();}}
class Second {act():void{}changed(hub:Hub):void{hub.coordinate();}}
class Hub {one:First;two:Second;
 constructor(one:First,two:Second){this.one=one;this.two=two;}
 coordinate():void{this.one.act();this.two.act();}
}
''',
'memento': '''
class Snapshot {value:number;constructor(value:number){this.value=value;}}
class Subject {value:number=0;
 save():Snapshot{return new Snapshot(this.value);}
 restore(snapshot:Snapshot):void{this.value=snapshot.value;}
}
''',
'observer': '''
class Subject {listeners:Array<(event:number)=>void>=[];
 subscribe(listener:(event:number)=>void):void{this.listeners.push(listener);}
 notify(event:number):void{for(const listener of this.listeners){listener(event);}}
}
''',
'state': '''
interface Contract {run():void;}
class Concrete implements Contract {run():void{}}
class Subject {state:Contract;
 constructor(state:Contract){this.state=state;}
 run():void{this.state.run();}
 change():void{this.state=new Concrete();}
}
''',
'strategy': '''
interface Contract {run():number;}
class First implements Contract {run():number{return 1;}}
class Second implements Contract {run():number{return 2;}}
class Subject {strategy:Contract;
 constructor(strategy:Contract){this.strategy=strategy;}
 run():number{return this.strategy.run();}
}
''',
 'template-method': '''
abstract class Base {run():void{this.step();}abstract step():void;}
class Subject extends Base {step():void{console.log("step");}}
''',
'visitor': '''
class Subject {accept(visitor:Visitor):void{visitor.visit(this);}}
class Visitor {visit(element:Subject):void{console.log(element);}}
''',
}

# Product families are separate contracts; two arbitrary methods returning
# unrelated data objects are insufficient evidence for Abstract Factory.
PYTHON['abstract-factory'] = PYTHON['abstract-factory'].replace(
    'class One: pass\nclass Two: pass',
    'class FamilyOne: pass\nclass FamilyTwo: pass\nclass One(FamilyOne): pass\nclass Two(FamilyTwo): pass')
JAVA['abstract-factory'] = JAVA['abstract-factory'].replace(
    'class One {} class Two {}',
    'interface FamilyOne {} interface FamilyTwo {} class One implements FamilyOne {} class Two implements FamilyTwo {}')
TYPESCRIPT['abstract-factory'] = TYPESCRIPT['abstract-factory'].replace(
    'class One {} class Two {}',
    'interface FamilyOne {} interface FamilyTwo {} class One implements FamilyOne {} class Two implements FamilyTwo {}')
