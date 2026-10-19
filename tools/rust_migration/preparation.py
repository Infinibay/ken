"""Explicit native context prerequisites for validation, never original imports."""
from dataclasses import dataclass
import os
from pathlib import Path

CONTEXT_ENV=('KEN_CONTEXT_SNAPSHOT','KEN_ORT_LIBRARY','KEN_CONTEXT_PROBE')

@dataclass(frozen=True)
class PreparedNativeContext:
    snapshot:Path
    library:Path
    probe:Path

    def environment(self)->dict[str,str]:
        values=dict(zip(CONTEXT_ENV,(self.snapshot,self.library,self.probe),strict=True))
        if any(not p.is_absolute() for p in values.values()):
            raise ValueError('explicit absolute native context prerequisites required')
        return {key:str(value) for key,value in values.items()}


def context_environment(prepared:PreparedNativeContext|None=None)->dict[str,str]:
    if prepared is not None:return prepared.environment()
    # Forward only explicitly prepared inputs. Missing inputs are not invented;
    # mandatory Rust/process suites fail if the caller did not prepare them.
    values={key:os.environ[key] for key in CONTEXT_ENV if key in os.environ}
    if any(not Path(value).is_absolute() for value in values.values()):
        raise ValueError('absolute prepared context paths required')
    return values
