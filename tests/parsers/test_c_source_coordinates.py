"""C ownership must use physical source coordinates, including syntax trivia."""
import pytest

from ken.parsers.c import parse_c_file


def ranges(source):
    return [(s.name, s.line_start, s.line_end)
            for s in parse_c_file(source.encode(), 'example.c').symbols]


def test_comments_cannot_shift_function_offsets_into_another_owner():
    source = ('/* ' + 'long copyright text '*20 + '*/\n'
              '// another comment with many characters\n'
              'static int first(void)\n{\n    return 1;\n}\n\n'
              'int second(void)\n{\n    return 2;\n}\n')
    assert ranges(source) == [('first', 3, 6), ('second', 8, 11)]


def test_braces_in_comments_strings_and_character_literals_do_not_end_the_body():
    source = '''int first(void) {
    const char *text = "}";
    char brace = '}';
    /* } } } */
    return text[0] == brace;
}
int second(void) { return 2; }
'''
    assert ranges(source) == [('first', 1, 6), ('second', 7, 7)]


def test_crlf_and_unicode_comments_preserve_physical_coordinates():
    source = '/* ñ 🌟 copyright */\r\n// more text\r\nint present(void) { return 1; }\r\n'
    assert ranges(source) == [('present', 3, 3)]


def test_conditional_definitions_keep_both_source_identities():
    source = '#if FEATURE\nint selected(void) { return 1; }\n#else\nint selected(void) { return 2; }\n#endif\n'
    assert ranges(source) == [('selected', 2, 2), ('selected', 4, 4)]


def test_scopes_retain_multiline_signature_documentation_and_real_statements():
    source = '''/** Return the incremented value. */
static int
helper(int value)
{
    return value + 1;
}
'''
    parsed = parse_c_file(source.encode(), 'example.c')
    assert ranges(source) == [('helper', 2, 6)]
    scope, = parsed.scopes
    assert scope.signature == 'static int\nhelper(int value)'
    assert scope.documentation == 'Return the incremented value.'
    assert scope.statements == [(5, 5)]
    assert scope.implementation_start_line == 5


def test_kernel_macro_definition_keeps_its_entire_body_and_existing_logical_name():
    source = 'SYSCALL_DEFINE2(example, int, fd, char *, name)\n{\n    return 0;\n}\n'
    parsed = parse_c_file(source.encode(), 'example.c')
    assert ranges(source) == [('__example', 1, 4)]
    scope, = parsed.scopes
    assert scope.implementation_start_line == 3
    assert scope.statements == [(3, 3)]


def test_commented_kernel_macro_is_not_a_definition():
    source = '/*\nSYSCALL_DEFINE0(fake) { return 0; }\n*/\nint real(void) { return 1; }\n'
    assert ranges(source) == [('real', 4, 4)]


def test_line_spliced_comment_does_not_introduce_a_fake_function():
    source = '\n'.join(['// continued comment '+chr(92),
                        'int fake(void) { return 0; }',
                        'int real(void) { return 1; }'])
    assert ranges(source) == [('real', 3, 3)]


@pytest.mark.parametrize(('header', 'logical_name'), [
    ('COMPAT_SYSCALL_DEFINE0(example)', '__example'),
    ('BPF_CALL_2(handle, int, fd, char *, data)', 'handle'),
    ('SYSCALL_DEFINE2(example, int, fd, int, flag)', '__example'),
])
def test_existing_definition_macro_names_survive_comments_before_the_body(header, logical_name):
    source = header + '\n/* a brace } in trivia */\n{\n    return 0;\n}\n'
    assert ranges(source) == [(logical_name, 1, 5)]


def test_function_returning_pointer_to_function_owns_its_real_body():
    source = 'int (*select_handler(void))(int)\n{\n    return 0;\n}\n'
    assert ranges(source) == [('select_handler', 1, 4)]


@pytest.mark.parametrize(('header', 'logical_name'), [
    ('SYSCALL_DEFINE0 /* comment */ (example)', '__example'),
    ('COMPAT_SYSCALL_DEFINE1(/* comment */ example, int, value)', '__example'),
])
def test_comments_between_macro_tokens_cannot_hide_a_definition(header, logical_name):
    assert ranges(header + ' { return 0; }') == [(logical_name, 1, 1)]


def test_elifdef_and_its_else_retain_each_physical_definition():
    source = ('#if A\nint a(void) { return 1; }\n#elifdef B\n'
              'int b(void) { return 2; }\n#else\nint c(void) { return 3; }\n#endif\n')
    assert ranges(source) == [('a', 2, 2), ('b', 4, 4), ('c', 6, 6)]


def test_gnu_nested_function_gets_its_own_scope_and_canonical_parent():
    source = 'int outer(void) {\n int inner(void) { return 1; }\n return inner();\n}\n'
    parsed = parse_c_file(source.encode(), 'example.c')
    assert [(s.qualname, s.line_start, s.line_end) for s in parsed.symbols] == [
        ('outer', 1, 4), ('outer.inner', 2, 2)]
    outer, inner = parsed.scopes
    assert outer.owner is None
    assert inner.owner == 'outer'
    assert inner.signature == 'int inner(void)'


def test_macro_argument_after_spliced_line_comment_uses_the_actual_identifier():
    source = '\n'.join(['SYSCALL_DEFINE0(// continued comment '+chr(92),
                        'fake_name', 'real_name)', '{', ' return 0;', '}'])
    assert ranges(source) == [('__real_name', 1, 6)]
