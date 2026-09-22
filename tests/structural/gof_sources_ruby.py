"""Ruby source fixtures for the GoF catalog; parsed, never executed.

Ruby publishes no nominal type annotations, so these examples exercise the
structural and call-name evidence a dynamic language provides: instance
variables hold collaborators, ``initialize`` is the constructor, ``each`` with a
block consumes a collection, and families are recognised by the operation name
invoked on a retained collaborator. Fixture names are arbitrary. These examples
demonstrate structural evidence, not functional libraries.
"""

ABSTRACT_FACTORY = '''
class WinButton
  def paint
    "win button"
  end
end

class MacButton
  def paint
    "mac button"
  end
end

class WinCheckbox
  def paint
    "win checkbox"
  end
end

class MacCheckbox
  def paint
    "mac checkbox"
  end
end

class WinFactory
  def create_button
    WinButton.new
  end

  def create_checkbox
    WinCheckbox.new
  end
end

class MacFactory
  def create_button
    MacButton.new
  end

  def create_checkbox
    MacCheckbox.new
  end
end
'''

ADAPTER = '''
class LegacyPrinter
  def initialize
    @lines = []
  end

  def print_old(text)
    @lines << text
  end
end

class PrinterAdapter
  def initialize(printer)
    @printer = printer
  end

  def print(text)
    @printer.print_old(text)
  end
end
'''

BRIDGE = '''
class DrawingApi
  def draw_circle(x, y, radius)
    raise NotImplementedError
  end
end

class SvgApi < DrawingApi
  def draw_circle(x, y, radius)
    @last = radius
  end
end

class Shape
  def initialize(api)
    @api = api
  end
end

class CircleShape < Shape
  def draw
    @api.draw_circle(1, 2, 3)
  end
end
'''

BUILDER = '''
class Product
  attr_accessor :size, :color

  def initialize
    @size = 0
    @color = "black"
  end
end

class ProductBuilder
  def initialize
    @product = Product.new
  end

  def size(value)
    @product.size = value
    self
  end

  def color(value)
    @product.color = value
    self
  end

  def finish
    @product
  end
end
'''

CHAIN_OF_RESPONSIBILITY = '''
class Handler
  def initialize(next_handler)
    @next_handler = next_handler
  end

  def handle(request)
    if request > 10
      return "large"
    end
    @next_handler.handle(request)
  end
end

class SmallHandler
  def handle(request)
    if request > 0
      return "small"
    end
    0
  end
end
'''

COMMAND = '''
class Light
  def turn_on
    @on = true
  end
end

class TurnOnCommand
  def initialize(light)
    @light = light
  end

  def execute
    @light.turn_on
  end
end

class RemoteControl
  def initialize(command)
    @command = command
  end

  def press
    @command.execute
  end
end
'''

COMPOSITE = '''
class Folder
  def initialize(name)
    @name = name
    @children = []
  end

  def add(child)
    @children << child
    self
  end

  def size
    total = 0
    @children.each { |child| total = total + child.size }
    total
  end
end
'''

DECORATOR = '''
class FileSource
  def read
    "data"
  end
end

class EncryptedSource
  def initialize(source)
    @source = source
  end

  def read
    encrypt(@source.read)
  end

  def encrypt(text)
    text.reverse
  end
end
'''

FACADE = '''
class Cpu
  def start
    @started = true
  end
end

class Memory
  def load
    @loaded = true
  end
end

class ComputerFacade
  def initialize
    @cpu = Cpu.new
    @memory = Memory.new
  end

  def start
    @cpu.start
    @memory.load
  end
end
'''

FACTORY_METHOD = '''
class Product
  def use
    "product"
  end
end

class SpecialProduct < Product
  def use
    "special"
  end
end

class Creator
  def create
    Product.new
  end

  def operate
    create.use
  end
end

class SpecialCreator < Creator
  def create
    SpecialProduct.new
  end
end
'''

FLYWEIGHT = '''
class TreeType
  def initialize(name)
    @name = name
  end

  def draw(x, y)
    @x = x
    @y = y
  end
end

class TreeFactory
  def initialize
    @types = {}
  end

  def type_for(name)
    return @types[name] if @types.key?(name)
    created = TreeType.new(name)
    @types[name] = created
    created
  end
end
'''

INTERPRETER = '''
class Number
  def initialize(value)
    @value = value
  end

  def evaluate
    @value
  end
end

class Add
  def initialize(left, right)
    @left = left
    @right = right
  end

  def evaluate
    @left.evaluate + @right.evaluate
  end
end
'''

ITERATOR = '''
class NumberCollection
  def initialize(numbers)
    @numbers = numbers
  end

  def each
    @numbers.each { |number| yield number }
  end
end

class Cursor
  def initialize(numbers)
    @numbers = numbers
    @index = 0
  end

  def next_item
    value = @numbers[@index]
    @index = @index + 1
    value
  end

  def has_next
    @index < @numbers.length
  end
end
'''

MEDIATOR = '''
class ChatRoom
  def initialize
    @users = []
  end

  def register(user)
    @users << user
  end

  def broadcast(sender, message)
    @users.each { |user| user.receive(sender, message) }
  end
end

class User
  def initialize(name, room)
    @name = name
    @room = room
  end

  def say(message)
    @room.broadcast(@name, message)
  end

  def receive(sender, message)
    @inbox = message
  end
end
'''

MEMENTO = '''
class Editor
  def initialize
    @text = ""
  end

  def type(words)
    @text = @text + words
  end

  def save
    Snapshot.new(@text)
  end

  def restore(snapshot)
    @text = snapshot.text
  end
end

class Snapshot
  attr_reader :text

  def initialize(text)
    @text = text
  end
end
'''

OBSERVER = '''
class Subject
  def initialize
    @listeners = []
    @state = 0
  end

  def attach(listener)
    @listeners << listener
  end

  def change(state)
    @state = state
    @listeners.each { |listener| listener.update(@state) }
  end
end

class AuditListener
  def update(state)
    @seen = state
  end
end
'''

PROTOTYPE = '''
class Sheep
  def initialize(name)
    @name = name
  end

  def copy
    Sheep.new(@name)
  end
end

class Registry
  def initialize(prototype)
    @prototype = prototype
  end

  def spawn
    @prototype.copy
  end
end
'''

PROXY = '''
class RealService
  def request
    "served"
  end
end

class GuardedService
  def initialize(service)
    @service = service
    @calls = 0
  end

  def request
    @calls = @calls + 1
    return "denied" if @calls > 3
    @service.request
  end
end
'''

SINGLETON = '''
class Configuration
  def self.instance
    @instance ||= Configuration.new
  end

  def initialize
    @values = {}
  end

  def fetch(key)
    @values[key]
  end
end

class Logger
  @shared = Logger.new

  def self.shared
    @shared
  end

  def write(line)
    @last = line
  end
end
'''

STATE = '''
class DraftState
  def publish(document)
    document.state = PublishedState.new
  end
end

class PublishedState
  def publish(document)
    document.state = PublishedState.new
  end
end

class Document
  attr_accessor :state

  def initialize
    @state = DraftState.new
  end

  def publish
    @state.publish(self)
  end
end
'''

STRATEGY = '''
class Context
  def initialize(strategy)
    @strategy = strategy
  end

  def execute(a, b)
    @strategy.execute(a, b)
  end
end

class AddStrategy
  def execute(a, b)
    a + b
  end
end

class MultiplyStrategy
  def execute(a, b)
    a * b
  end
end
'''

TEMPLATE_METHOD = '''
class DataMiner
  def mine(path)
    data = extract(path)
    report = analyze(data)
    report
  end

  def extract(path)
    raise NotImplementedError
  end

  def analyze(data)
    data
  end
end

class CsvMiner < DataMiner
  def extract(path)
    path.split(",")
  end
end
'''

VISITOR = '''
class Dot
  def accept(visitor)
    visitor.visit_dot(self)
  end
end

class Circle
  def accept(visitor)
    visitor.visit_circle(self)
  end
end

class AreaVisitor
  def visit_dot(dot)
    @area = 0
  end

  def visit_circle(circle)
    @area = 1
  end
end
'''

RUBY = {
    'abstract-factory': ABSTRACT_FACTORY,
    'adapter': ADAPTER,
    'bridge': BRIDGE,
    'builder': BUILDER,
    'chain-of-responsibility': CHAIN_OF_RESPONSIBILITY,
    'command': COMMAND,
    'composite': COMPOSITE,
    'decorator': DECORATOR,
    'facade': FACADE,
    'factory-method': FACTORY_METHOD,
    'flyweight': FLYWEIGHT,
    'interpreter': INTERPRETER,
    'iterator': ITERATOR,
    'mediator': MEDIATOR,
    'memento': MEMENTO,
    'observer': OBSERVER,
    'prototype': PROTOTYPE,
    'proxy': PROXY,
    'singleton': SINGLETON,
    'state': STATE,
    'strategy': STRATEGY,
    'template-method': TEMPLATE_METHOD,
    'visitor': VISITOR,
}
