"""Replay new factory observations against authenticated, scope-specific oracles."""
from __future__ import annotations
import math
import re


def compare_factory(actual: dict, expected: dict, *, execution: dict, predecessors: dict) -> list[str]:
    """No outer passed flag substitutes for selection, native output or exec audit.

    The caller authenticates predecessor artifacts before passing their verified
    outcomes and derives expected data from those pinned original/direct records.
    This function deliberately does not award complete M2 acceptance.
    """
    errors = []
    def require(condition, message):
        if not condition: errors.append(message)
    try:
        require(actual['format'] == 'ken-model-factory-observation/1', 'wrong factory protocol')
        for key in ('selection', 'compatible_key', 'source_files', 'runtime'):
            require(actual[key] == expected[key], 'factory '+key+' differs from pinned original/native inputs')
        require(actual['initial_prepared'] is False, 'factory constructor loaded model')
        if expected['selection']['role'] == 'encoder':
            require(actual['after_empty_prepared'] is False, 'empty encoder call loaded model')
        require(actual['policy'] in ('offline', 'public'), 'explicit acquisition policy required')
        require(execution['exit_code'] == 0 and execution['outside_checkout'] is True,
                'successful outside-checkout native process required')
        require(execution['dependency_audit']['passed'] is True, 'native library audit missing')
        require(execution['sentinel_invocations'] == [] and execution['owned_after_exit'] == [],
                'native consumer ran a forbidden child or leaked an owned process')
        if execution['platform'] == 'linux':
            require(set(execution['audit_syscalls']) >= {'execve', 'execveat', 'connect'},
                    'both exec syscalls and network audit required')
            require(len(re.findall(r'\bexecve(?:at)?\(', execution['trace'])) == 1,
                    'exactly one initial native exec required')
            if actual['policy'] == 'offline':
                require(re.search(r'\bconnect\(', execution['trace']) is None,
                        'offline factory performed a network operation')
        for name in ('storage', 'core'):
            require(predecessors[name]['verified'] is True, 'unverified predecessor '+name)
        def equal(left, right, path):
            if type(right) is float:
                tolerance = 1e-5 if 'scores' in path else 1e-6
                return type(left) in (float, int) and math.isfinite(left) and math.isfinite(right) and abs(left-right) <= tolerance
            if type(right) is list:
                return type(left) is list and len(left) == len(right) and all(equal(a,b,path) for a,b in zip(left,right))
            if type(right) is dict:
                return type(left) is dict and left.keys() == right.keys() and all(equal(left[k],v,path+'.'+k) for k,v in right.items())
            return type(left) is type(right) and left == right
        require(equal(actual['rows'], expected['rows'], 'rows'), 'factory outputs/errors/ownership state differ')
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        errors.append('incomplete factory observation: '+str(error))
    return errors
