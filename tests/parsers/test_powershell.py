"""PowerShell parser: function definitions + Import-Module / dot-source."""

from __future__ import annotations


def test_function_definition(parse_powershell):
    src = "function Get-Thing {\n  param($x)\n  $x\n}\n"
    out = parse_powershell(src)
    by_name = {s.name: s for s in out.symbols}
    assert "Get-Thing" in by_name
    assert by_name["Get-Thing"].kind == "function"


def test_import_module_relative(parse_powershell):
    src = "Import-Module ./MyModule.psm1\n"
    out = parse_powershell(src)
    mods = {i.module for i in out.imports}
    assert "./MyModule.psm1" in mods
