"""Three bounded syntax predicates, plus an independent Tree-sitter oracle."""

from itertools import chain

BRANCHES = {"if_statement", "if_expression", "elif_clause"}
RETURNS = {"return_statement", "return_expression"}
CALLS = {"call", "call_expression", "method_invocation", "invocation_expression"}
FUNCTIONS = {
    "function_item",
    "function_definition",
    "function_declaration",
    "method_definition",
    "method_declaration",
    "arrow_function",
    "lambda",
    "closure_expression",
    "function_expression",
}
LITERALS = {
    "integer",
    "integer_literal",
    "float",
    "float_literal",
    "string",
    "string_literal",
    "char_literal",
    "character_literal",
    "number",
}
COMPARISONS = {"comparison_operator", "binary_expression", "binary_operator"}
WRAPPERS = {"parenthesized_expression"}
COMMENTS = {"comment", "line_comment", "block_comment"}
QUERIES = {
    "if_literal": BRANCHES,
    "return_contains_call": RETURNS,
    "function_branch_return": FUNCTIONS,
}


def descendants(node, *, skip_functions=False):
    stack = list(reversed(node.children))
    while stack:
        child = stack.pop()
        if skip_functions and child.type in FUNCTIONS:
            continue
        yield child
        stack.extend(reversed(child.children))


def oracle_match(query, node):
    if node.has_error or node.is_missing:
        return False
    if query == "if_literal":
        condition = node.child_by_field_name("condition")
        while condition is not None and condition.type in WRAPPERS:
            children = [n for n in condition.named_children if n.type not in COMMENTS]
            condition = children[0] if len(children) == 1 else None
        if condition is None or condition.type not in COMPARISONS:
            return False
        children = [n for n in condition.children if n.type not in COMMENTS]
        return (
            len(children) == 3
            and children[0].type == "identifier"
            and children[1].type in {"==", "!="}
            and children[2].type in LITERALS
        )
    if query == "return_contains_call":
        return any(n.type in CALLS for n in descendants(node))
    kinds = {n.type for n in descendants(node, skip_functions=True)}
    return bool(kinds & BRANCHES) and bool(kinds & RETURNS)


def oracle(tree):
    found = {query: [] for query in QUERIES}
    for node in chain((tree.root_node,), descendants(tree.root_node)):
        for query, kinds in QUERIES.items():
            if node.type in kinds and oracle_match(query, node):
                found[query].append((node.start_byte, node.end_byte))
    return found


class Matcher:
    def __init__(self, words):
        ids = {word: i for i, word in enumerate(words)}
        codes = lambda names: {ids[n] for n in names if n in ids}
        self.branches, self.returns = codes(BRANCHES), codes(RETURNS)
        self.calls, self.functions = codes(CALLS), codes(FUNCTIONS)
        self.literals, self.comparisons = codes(LITERALS), codes(COMPARISONS)
        self.wrappers, self.comments = codes(WRAPPERS), codes(COMMENTS)
        self.operators = codes({"==", "!="})
        self.variable = ids.get("identifier", -1)
        self.condition = ids.get("condition", -1)
        self.roots = {query: codes(kinds) for query, kinds in QUERIES.items()}

    def children(self, columns, node):
        kind, _, _, end, *_ = columns
        child = node + 1
        while child < end[node]:
            if kind[child] not in self.comments:
                yield child
            child = int(end[child])

    def match(self, query, columns, node):
        kind, role, _, end, _, _, flags = columns
        if flags[node] & 6:
            return False
        if query == "if_literal":
            condition = next(
                (c for c in self.children(columns, node) if role[c] == self.condition),
                None,
            )
            while condition is not None and kind[condition] in self.wrappers:
                children = [
                    c for c in self.children(columns, condition) if flags[c] & 1
                ]
                condition = children[0] if len(children) == 1 else None
            if condition is None or kind[condition] not in self.comparisons:
                return False
            children = list(self.children(columns, condition))
            return (
                len(children) == 3
                and kind[children[0]] == self.variable
                and kind[children[1]] in self.operators
                and kind[children[2]] in self.literals
            )
        branch = returned = False
        child, stop = node + 1, int(end[node])
        while child < stop:
            current = kind[child]
            if query == "return_contains_call":
                if current in self.calls:
                    return True
            elif current in self.functions:
                child = int(end[child])
                continue
            else:
                branch |= current in self.branches
                returned |= current in self.returns
                if branch and returned:
                    return True
            child += 1
        return False
