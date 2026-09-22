class Emitter:
    def __init__(self):
        self.listeners = []
    def on(self, fn):
        self.listeners.append(fn)
    def emit(self, value):
        for fn in self.listeners:
            fn(value)
