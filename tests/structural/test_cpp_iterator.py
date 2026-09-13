"""External C++ cursor protocol and source-order-independent field references."""
import pytest
from .test_gof_executable import evaluate

SOURCE = '''class Cursor {
public:
 void next() { position++; }
 bool isDone() const { return position >= 10; }
 int currentItem() const { return position; }
private:
 int position;
 int other;
};'''


@pytest.mark.parametrize('update', ['position++', '++position', 'position--', '--position'])
@pytest.mark.parametrize('fields_first', [False, True])
def test_cpp_cursor_updates_shared_position(update, fields_first):
    source = SOURCE.replace('position++', update)
    if fields_first:
        source = source.replace(' int position;', '').replace('class Cursor {', 'class Cursor { int position;')
    assert evaluate(source, 'cpp', 'iterator')


@pytest.mark.parametrize('before,after', [
 ('position++;', '(void)position;'),
 ('position++;', 'other++;'),
 ('return position >= 10', 'return other >= 10'),
 ('return position;', 'return other;'),
 ('void next() { position++; }', 'void next() { int position = 0; position++; }'),
])
def test_cpp_cursor_rejects_unrelated_or_unmodified_state(before, after):
    assert not evaluate(SOURCE.replace(before, after), 'cpp', 'iterator')
