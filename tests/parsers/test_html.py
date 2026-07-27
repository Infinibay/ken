"""HTML parser: anchors, components, named controls, title, script/link imports."""

from __future__ import annotations


def test_anchors_components_and_doc_comment(parse_html):
    src = (
        "<!-- main navigation -->\n"
        '<div id="sidebar" class="nav nav-left">\n'
        "  <my-widget></my-widget>\n"
        "</div>\n"
    )
    out = parse_html(src)
    by_name = {s.name: s for s in out.symbols}
    assert by_name["#sidebar"].kind == "anchor"
    assert by_name["#sidebar"].docstring == "main navigation"
    assert by_name["my-widget"].kind == "component"
    # A class is declared in CSS and only used here; emitting one symbol per use
    # would bury every real name.
    assert not any(s.name in ("nav", "nav-left", ".nav") for s in out.symbols)


def test_title_and_named_controls(parse_html):
    src = (
        "<html><head><title>Admin  panel</title></head>\n"
        '<body><form name="login"><input name="password" type="password">\n'
        '<span name="decorative"></span></form></body></html>\n'
    )
    out = parse_html(src)
    kinds = {(s.kind, s.name) for s in out.symbols}
    assert ("title", "Admin panel") in kinds  # whitespace collapsed
    assert ("control", "login") in kinds
    assert ("control", "password") in kinds
    # `name` on an arbitrary element is an author annotation, not API surface.
    assert ("control", "decorative") not in kinds


def test_script_and_link_imports_normalised(parse_html):
    src = (
        '<link rel="stylesheet" href="theme.css">\n'
        '<link rel="icon" href="/static/favicon.ico">\n'
        '<script src="app.js"></script>\n'
        '<script src="https://cdn.example.com/lib.js"></script>\n'
        "<script>const inline = 1;</script>\n"
    )
    mods = [i.module for i in parse_html(src).imports]
    assert "./theme.css" in mods
    assert "./app.js" in mods
    assert "/static/favicon.ico" in mods           # root-absolute left alone
    assert "https://cdn.example.com/lib.js" in mods  # external left alone
    assert len(mods) == 4                          # the inline script is not one


def test_unquoted_and_self_closing_attributes(parse_html):
    src = '<img id=hero src="a.png"/>\n<input name=email>\n'
    out = parse_html(src)
    names = {s.name for s in out.symbols}
    assert "#hero" in names
    assert "email" in names


def test_malformed_markup_does_not_raise(parse_html):
    """ken indexes whatever is on disk, including half-written templates."""
    out = parse_html("<div id='a'><span></div></p><<<")
    assert any(s.name == "#a" for s in out.symbols)
