class Node:
    def __init__(self, name):
        self.name = name
        self.children = []
    def add(self, child):
        self.children.append(child)
    def size(self):
        return 1 + sum(child.size() for child in self.children)
