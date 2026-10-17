from tests.retrieval.test_symbol_ranking import make_catalog
from ken.retrieval.source_operations import OperationWitnesses
from ken.retrieval.symbol_requirements import requested_operations, prefer_operations


def test_cause_requires_direct_non_null_chaining_and_keeps_error_family(tmp_path):
    catalog = make_catalog(tmp_path, {'sample.py': '''def chained(error):
    raise AttributeError("location") from error
def suppressed():
    raise AttributeError("location") from None
def wrapper(error):
    def nested():
        raise AttributeError("location") from error
    return nested
'''})
    witnesses = OperationWitnesses(catalog)
    keys = {k.qualname: k for k in catalog.owners}
    assert 'cause:AttributeError' in witnesses.for_owner(keys['chained'])
    assert 'cause:AttributeError' not in witnesses.for_owner(keys['suppressed'])
    assert 'cause:AttributeError' not in witnesses.for_owner(keys['wrapper'])


def test_snapshot_write_binds_the_same_mapping_key_and_previous_value(tmp_path):
    template = '''def update(mapping, key, value, undo):
    old = mapping.get(key, None)
    mapping[key] = value
    undo.append((mapping, key, old))
'''
    catalog = make_catalog(tmp_path, {'sample.py': template + template.replace('update(', 'delete(').replace('mapping[key] = value', 'del mapping[key]') + template.replace('update(', 'other_key(').replace('undo.append((mapping, key, old))', 'undo.append((mapping, "different", old))')})
    witnesses = OperationWitnesses(catalog)
    keys = {k.qualname: k for k in catalog.owners}
    assert 'snapshot_keyed_write' in witnesses.for_owner(keys['update'])
    assert 'snapshot_keyed_write' not in witnesses.for_owner(keys['delete'])
    assert 'snapshot_keyed_write' not in witnesses.for_owner(keys['other_key'])


def test_returned_flag_update_is_same_value_not_just_an_or_token(tmp_path):
    catalog = make_catalog(tmp_path, {'Sample.java': '''class Sample {
    boolean flag, other;
    boolean refresh() {
        return flag || (flag = attempt());
    }
    boolean wrongTarget() {
        return flag || (other = attempt());
    }
    boolean blocking() {
        flag = attempt();
        return true;
    }
}
'''})
    keys = {k.qualname: k for k in catalog.owners}
    witnesses = OperationWitnesses(catalog)
    assert 'returned_flag_refresh' in witnesses.for_owner(keys['Sample.refresh'])
    assert 'returned_flag_refresh' not in witnesses.for_owner(keys['Sample.wrongTarget'])
    assert 'returned_flag_refresh' not in witnesses.for_owner(keys['Sample.blocking'])


def test_query_requirements_are_explicit_and_skip_negated_prose():
    assert requested_operations('Which lookup retains the original exception as its cause after an attribute error?') == {'cause:AttributeError'}
    assert requested_operations('Where is an existing flag returned or updated from an attempt?') == {'returned_flag_refresh'}
    assert requested_operations('Which update remembers an absent mapping key before assigning a temporary value and adding the old state to an undo log?') == {'snapshot_keyed_write'}
    assert requested_operations('Which helper suppresses the exception cause?') == set()
    assert requested_operations('Which mapping helper deletes a key without assigning a replacement?') == set()


def test_preference_is_stable_and_never_drops_unknown_candidates():
    required = {'cause:AttributeError'}
    assert prefer_operations(required, [set(), required, set()], [0, 1, 2]) == [1, 0, 2]
    assert prefer_operations(required, [set(), set()], [1, 0]) == [1, 0]
    assert prefer_operations(set(), [required, set()], [1, 0]) == [1, 0]


def test_java_witnesses_use_the_catalog_snapshot_after_disk_changes(tmp_path):
    source = "class Sample {\n    boolean flag;\n    boolean refresh() {\n        return flag || (flag = attempt());\n    }\n}\n"
    catalog = make_catalog(tmp_path, {'Sample.java': source})
    key = next(k for k in catalog.owners if k.qualname == 'Sample.refresh')
    (tmp_path / 'Sample.java').write_text(source.replace('return flag || (flag = attempt());', 'return false;'))
    assert 'returned_flag_refresh' in OperationWitnesses(catalog).for_owner(key)


def test_a_nested_java_lambda_return_does_not_belong_to_the_enclosing_method(tmp_path):
    source = "class Sample {\n    boolean flag;\n    Object factory() {\n        return () -> {\n            return flag || (flag = attempt());\n        };\n    }\n}\n"
    catalog = make_catalog(tmp_path, {'Sample.java': source})
    key = next(k for k in catalog.owners if k.qualname == 'Sample.factory')
    assert 'returned_flag_refresh' not in OperationWitnesses(catalog).for_owner(key)


def test_negated_refresh_is_not_a_request_for_a_flag_update():
    assert requested_operations("Which function returns a flag or default without updating it?") == set()


def test_invocation_uses_owned_body_not_stored_callbacks_defaults_or_nested_bodies(tmp_path):
    catalog = make_catalog(tmp_path, {'callbacks.py': '''def store(callback=build_callback()):
    return callback

def nested(callback):
    def deferred():
        callback()
    return deferred

def run(callback):
    return callback()
''', 'Callbacks.java': '''class Callbacks {
    Runnable callback;
    Callbacks(Runnable callback) { this.callback = callback; }
    void run() { callback.run(); }
    Runnable deferred() {
        return () -> callback.run();
    }
}
''', 'callbacks.js': '''function store(callback) { return callback; }
function run(callback) { return callback(); }
function deferred(callback) {
    return () => callback();
}
'''})
    observations = OperationWitnesses(catalog)
    actual = {(key.path, key.qualname): 'invocation' in observations.for_owner(key)
              for key in catalog.owners if key.kind in {'function', 'method', 'constructor'}}
    assert actual[('callbacks.py', 'store')] is False
    assert actual[('callbacks.py', 'nested')] is False
    assert actual[('callbacks.py', 'run')] is True
    assert actual[('Callbacks.java', 'Callbacks.Callbacks')] is False
    assert actual[('Callbacks.java', 'Callbacks.run')] is True
    assert actual[('Callbacks.java', 'Callbacks.deferred')] is False
    assert actual[('callbacks.js', 'store')] is False
    assert actual[('callbacks.js', 'run')] is True
    assert actual[('callbacks.js', 'deferred')] is False


def test_invocation_requirement_is_an_active_positive_action_with_an_object():
    assert requested_operations('Find a handler that invokes the selected callback.') == {'invocation'}
    assert requested_operations('Where does an event invoke a listener after validation?') == {'invocation'}
    assert requested_operations('Find dispatch by invoking a handler.') == {'invocation'}
    assert requested_operations('Find callback registration without invoking a handler.') == set()
    assert requested_operations('Find a helper that never invokes the callback.') == set()
    assert requested_operations('Find a helper that avoids invoking a callback.') == set()
    assert requested_operations('Find a callback that can be invoked later.') == set()
    assert requested_operations('Show the `invoke` function definition.') == set()
