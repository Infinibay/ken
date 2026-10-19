"""Explicit native context prerequisites for validation, never original imports."""
from dataclasses import dataclass
import os
from pathlib import Path

CONTEXT_ENV=('KEN_CONTEXT_SNAPSHOT','KEN_ORT_LIBRARY','KEN_CONTEXT_PROBE')
ETTIN_ENV=('KEN_ETTIN_SOURCE','KEN_ETTIN_PROBE')
TRANSLATION_ENV=('KEN_TRANSLATION_SOURCE','KEN_TRANSLATION_PROBE')
TRANSLATION_BUILD_ENV=('CMAKE','PKG_CONFIG_PATH','DEP_OPENBLAS_INCLUDE','DEP_OPENBLAS_LIBRARY')


def policy_environment(probe:Path|None=None)->dict[str,str]:
    value=str(probe) if probe is not None else os.environ.get('KEN_POLICY_PROBE')
    if value is None:return {}
    if not Path(value).is_absolute():
        raise ValueError('explicit absolute native policy probe required')
    return {'KEN_POLICY_PROBE':value}

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


@dataclass(frozen=True)
class PreparedNativeEttin:
    source:Path
    probe:Path

    def environment(self)->dict[str,str]:
        values=dict(zip(ETTIN_ENV,(self.source,self.probe),strict=True))
        if any(not path.is_absolute() for path in values.values()):
            raise ValueError('explicit absolute native Ettin prerequisites required')
        return {key:str(value) for key,value in values.items()}


def ettin_environment(prepared:PreparedNativeEttin|None=None)->dict[str,str]:
    if prepared is not None:return prepared.environment()
    values={key:os.environ[key] for key in ETTIN_ENV if key in os.environ}
    if any(not Path(value).is_absolute() for value in values.values()):
        raise ValueError('absolute prepared Ettin paths required')
    return values


@dataclass(frozen=True)
class PreparedTranslationBuild:
    cmake:Path
    openblas_prefix:Path|None=None

    def environment(self)->dict[str,str]:
        paths={'CMAKE':self.cmake}
        if self.openblas_prefix is not None:
            paths.update(PKG_CONFIG_PATH=self.openblas_prefix/'lib/pkgconfig',
                DEP_OPENBLAS_INCLUDE=self.openblas_prefix/'include',DEP_OPENBLAS_LIBRARY=self.openblas_prefix/'lib')
        if any(not path.is_absolute() for path in paths.values()):
            raise ValueError('absolute explicit native translation build paths required')
        return {key:str(path) for key,path in paths.items()}


@dataclass(frozen=True)
class PreparedNativeTranslation:
    source:Path
    probe:Path
    build:PreparedTranslationBuild|None=None

    def environment(self)->dict[str,str]:
        paths=dict(zip(TRANSLATION_ENV,(self.source,self.probe),strict=True))
        if any(not path.is_absolute() for path in paths.values()):
            raise ValueError('absolute explicit native translation prerequisites required')
        return {key:str(path) for key,path in paths.items()} | (self.build.environment() if self.build is not None else {})


def translation_environment(prepared:PreparedNativeTranslation|None=None)->dict[str,str]:
    keys=TRANSLATION_ENV if prepared is not None and prepared.build is not None else TRANSLATION_ENV+TRANSLATION_BUILD_ENV
    values={key:os.environ[key] for key in keys if key in os.environ}
    if prepared is not None:values.update(prepared.environment())
    if any(not Path(value).is_absolute() for value in values.values()):
        raise ValueError('absolute prepared translation/build paths required')
    return values
