"""Go parser: func / method receiver / type / imports."""

from __future__ import annotations


def test_extracts_function(parse_go):
    src = '''package main

// Run starts everything.
func Run() error {
    return nil
}
'''
    out = parse_go(src)
    syms = [s for s in out.symbols if s.kind == "function"]
    assert len(syms) == 1
    assert syms[0].name == "Run"
    assert syms[0].docstring == "Run starts everything."


def test_extracts_method_with_receiver_in_qualname(parse_go):
    src = '''package main

type Server struct{}

// Start the server.
func (s *Server) Start() error { return nil }

func (s Server) Stop() {}
'''
    out = parse_go(src)
    by_qual = {s.qualname: s for s in out.symbols}
    # Pointer receiver `*Server` and value receiver `Server` both → "Server.X".
    assert "Server.Start" in by_qual
    assert "Server.Stop" in by_qual


def test_extracts_struct_and_imports(parse_go):
    src = '''package main

import (
    "fmt"
    "encoding/json"
)

type Pair struct {
    A int
    B int
}
'''
    out = parse_go(src)
    by_kind_name = {(s.kind, s.name) for s in out.symbols}
    assert ("struct", "Pair") in by_kind_name
    modules = {imp.module for imp in out.imports}
    assert "fmt" in modules
    assert "encoding/json" in modules
