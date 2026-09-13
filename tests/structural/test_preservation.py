import pytest

from ken.structural import lower_source, link_project, lower_instructions
from ken.structural.preservation import preserve_binding


def check(middle, mode='strict'):
    source = 'def f(x,other):\n z=x\n'+''.join(' '+line+'\n' for line in middle.splitlines())+' return z\n'
    fn = lower_instructions(link_project([lower_source(source,'python','example')])).functions[0]
    initial = next(i for i in fn.body.instructions if i.opcode == 'slot.store')
    return preserve_binding(fn, initial.operands[0].ref, after=initial.id,
                            through=fn.body.instructions[-1].id, mode=mode)


@pytest.mark.parametrize('middle', ['', 'pass', 'other=x'])
@pytest.mark.parametrize('mode', ['strict','explicit-writes'])
def test_unrelated_binding_work_can_intervene(middle, mode):
    assert check(middle,mode).status == 'preserved'


@pytest.mark.parametrize('middle', ['z=other', 'z=x', 'z=other\nz=x'])
@pytest.mark.parametrize('mode', ['strict','explicit-writes'])
def test_even_restoring_a_binding_does_not_mean_it_was_never_written(middle, mode):
    result = check(middle,mode)
    assert result.status == 'violated' and result.witnesses


@pytest.mark.parametrize('middle', ['log(x)', 'z.name=x'])
def test_binding_inventory_does_not_claim_to_resolve_hidden_effects(middle):
    assert check(middle,'explicit-writes').status == 'preserved'
    result = check(middle,'strict')
    assert result.status == 'unknown' and result.witnesses


@pytest.mark.parametrize('middle', ['if x:\n z=other', 'return x\nlog(x)'])
@pytest.mark.parametrize('mode', ['strict','explicit-writes'])
def test_unmodeled_control_is_not_preservation(middle, mode):
    assert check(middle,mode).status == 'unknown'


@pytest.mark.parametrize('mode', ['strict','explicit-writes'])
def test_unreachable_later_store_is_not_a_confirmed_violation(mode):
    assert check('return x\nz=other', mode).status == 'unknown'
