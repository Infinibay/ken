"""Match the declaration phase of constructor initialization, before its BODY.

These are source inputs, not summaries of final field state; terminal BODY
restrictions must separately exclude overwrites and unsupported effects.
"""
from ken.structural_store import Node
from .values import Unknown


def _body_overwrites(semantic, owner, field) -> bool:
    """Does the executed constructor BODY write the field again?

    The declaration phase claims an input for the field; the body's own write is what
    makes that input non-terminal (``WRITES`` without ``execution`` is the declaration
    phase's own implicit write of a parameter property).
    """
    return any(f.object == field.local_id and f.attrs.get('execution')
               for f in semantic.facts('WRITES', owner.local_id))


def _copies_from_member(semantic, owner, initializer) -> bool:
    """Fill the field from a member of one of the owner's parameters?

    The copy constructor's spelling (``Config(const Config& other) : value(other.value)``)
    reads a member of the other instance. The analysis publishes that argument and the
    place it belongs to, which is how the declaration phase shows the parameter's state
    reaching the field.
    """
    parameters = {f.object for f in semantic.facts('HAS_PARAMETER',owner.local_id)}
    return any(any(f.object in parameters for f in semantic.facts('MEMBER_OF',argument.object))
               for argument in semantic.facts('INITIALIZER_ARGUMENT',initializer.object))


def matches(semantic, owner, statements, bindings):
    declared = semantic.index.ir.entities.get(owner.local_id) if hasattr(semantic,'index') else None
    if declared is not None and not declared.attrs.get('constructor'):
        return False
    initializers = semantic.facts('HAS_INITIALIZER',owner.local_id)
    if not any(_copies_from_member(semantic,owner,initializer) for initializer in initializers):
        for initializer in initializers:
            status = semantic.facts('CONSTRUCTOR_INITIALIZER_STATUS',initializer.object)
            if not status or any(f.object != 'supported' for f in status):
                return Unknown('constructor_initializer_unknown')
    for statement in statements:
        field = bindings.get(statement.expressions[0].value)
        value = bindings.get(statement.expressions[1].value)
        if not isinstance(field,Node) or not isinstance(value,Node):
            return Unknown('initializer_binding_unknown')
        params = [f.object for f in semantic.facts('HAS_PARAMETER',owner.local_id)]
        if value.local_id not in params:
            return False
        if any(f.object == field.local_id for f in semantic.facts('PARAMETER_INITIALIZES_FIELD',value.local_id)):
            # A parameter property initializes the field in the declaration phase, so no
            # ``CONSTRUCTOR_FIELD_INPUT`` is published for it -- but the parameter is the
            # field's input only while the BODY does not write the field again. Without
            # this check a parameter property the constructor overwrites still satisfies
            # the clause, which the linear field analysis does not claim.
            if _body_overwrites(semantic, owner, field):
                return False
            continue
        # Languages whose constructors are ordinary assignments (Python, JavaScript,
        # Java) publish the same claim as one fact on the field, with the parameter as
        # its input. There is no declaration-phase initializer to consult, so the
        # linear field input is the evidence the clause is asking for.
        if any(f.object == value.local_id for f in semantic.facts('CONSTRUCTOR_FIELD_INPUT',field.local_id)):
            continue
        # A declaration-phase initializer may fill the field with a *member* of another
        # instance, which is the copy constructor's own spelling
        # (``Config(const Config& other) : value(other.value)``). The initializer is the
        # field's own, so its argument is what fills that field; the member belongs to
        # the parameter, so the parameter's state is the input.
        if any(_copies_from_member(semantic,owner,initializer)
               and any(f.object == field.local_id for f in semantic.facts('INITIALIZES_FIELD',initializer.object))
               for initializer in initializers):
            if _body_overwrites(semantic, owner, field):
                return False
            continue
        accepted = False
        uncertain = False
        for initializer in semantic.facts('HAS_INITIALIZER',owner.local_id):
            status = semantic.facts('CONSTRUCTOR_INITIALIZER_STATUS',initializer.object)
            if not status or any(f.object != 'supported' for f in status):
                uncertain = True
                continue
            if (any(f.object == field.local_id for f in semantic.facts('INITIALIZES_FIELD',initializer.object)) and
                    any(f.object == value.local_id for f in semantic.facts('CONSTRUCTOR_INITIALIZER_INPUT',initializer.object))):
                # A declaration-phase initializer is the field's input only while the
                # body does not write the field again: the linear field analysis
                # withholds ``CONSTRUCTOR_FIELD_INPUT`` in exactly that case, and the
                # executed write the body publishes is how it is visible here.
                if _body_overwrites(semantic, owner, field):
                    return False
                accepted = True
        if not accepted:
            return Unknown('constructor_initializer_unknown') if uncertain else False
    return True
