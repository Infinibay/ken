"""CSS parser: rule selectors, @keyframes, custom properties, @import."""

from __future__ import annotations


def test_rules_and_doc_comment(parse_css):
    src = "/* Primary button */\n.btn, .btn-primary {\n  color: red;\n}\n#header { margin: 0; }\n"
    out = parse_css(src)
    by_name = {s.name: s for s in out.symbols}
    assert by_name[".btn, .btn-primary"].kind == "rule"
    assert by_name[".btn, .btn-primary"].docstring == "Primary button"
    assert "#header" in by_name


def test_imports_normalised_and_absolute_untouched(parse_css):
    src = (
        '@import "theme.css";\n'
        "@import url(vendor/reset.css);\n"
        '@import url("https://fonts.example.com/x.css");\n'
    )
    out = parse_css(src)
    mods = [i.module for i in out.imports]
    assert "./theme.css" in mods
    assert "./vendor/reset.css" in mods
    assert "https://fonts.example.com/x.css" in mods  # absolute left alone


def test_keyframes_and_custom_properties(parse_css):
    src = "@keyframes spin { from {} to {} }\n:root {\n  --main-color: #333;\n  --spacing: 8px;\n}\n"
    out = parse_css(src)
    kinds = {(s.kind, s.name) for s in out.symbols}
    assert ("keyframes", "spin") in kinds
    assert ("variable", "--main-color") in kinds
    assert ("variable", "--spacing") in kinds
