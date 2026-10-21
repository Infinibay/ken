"""Explicit native context prerequisites for validation, never original imports."""
from dataclasses import dataclass
import os
from pathlib import Path

CONTEXT_ENV=('KEN_CONTEXT_SNAPSHOT','KEN_ORT_LIBRARY','KEN_CONTEXT_PROBE')
ETTIN_ENV=('KEN_ETTIN_SOURCE','KEN_ETTIN_PROBE')
TRANSLATION_ENV=('KEN_TRANSLATION_SOURCE','KEN_TRANSLATION_PROBE')
TRANSLATION_BUILD_ENV=('CMAKE','PKG_CONFIG_PATH','DEP_OPENBLAS_INCLUDE','DEP_OPENBLAS_LIBRARY')
FASTEMBED_ENV=('KEN_FASTEMBED_PROBE','KEN_FASTEMBED_SOURCES','KEN_FASTEMBED_REGISTRY')


@dataclass(frozen=True)
class PreparedNativeFastEmbed:
    probe:Path
    sources:Path
    registry:Path
    acquire:bool=False

    def environment(self)->dict[str,str]:
        values=(self.probe,self.sources,self.registry)
        if any(not isinstance(path,Path) or not path.is_absolute() for path in values):
            raise ValueError('explicit absolute native FastEmbed paths required')
        if type(self.acquire)is not bool:raise ValueError('explicit boolean FastEmbed acquisition policy required')
        return dict(zip(FASTEMBED_ENV,map(str,values),strict=True))|({'KEN_FASTEMBED_ACQUIRE':'1'}if self.acquire else {})

def fastembed_environment(prepared:PreparedNativeFastEmbed|None=None,*,environ:dict[str,str]|None=None)->dict[str,str]:
    if prepared is not None:
        if not isinstance(prepared,PreparedNativeFastEmbed):
            raise ValueError('typed PreparedNativeFastEmbed input required')
        return prepared.environment()
    source=os.environ if environ is None else environ
    values={key:source[key] for key in FASTEMBED_ENV if key in source}
    acquisition=source.get('KEN_FASTEMBED_ACQUIRE')
    if acquisition is not None and acquisition!='1':raise ValueError('explicit FastEmbed acquisition policy must be 1')
    if not values and acquisition is None:return {}
    if set(values)!=set(FASTEMBED_ENV):
        raise ValueError('complete explicit native FastEmbed paths required')
    return PreparedNativeFastEmbed(*(Path(values[key]) for key in FASTEMBED_ENV),acquire=acquisition=='1').environment()


@dataclass(frozen=True)
class PreparedNativeStorage:
    probe:Path

    def environment(self)->dict[str,str]:
        if not isinstance(self.probe,Path) or not self.probe.is_absolute():
            raise ValueError('explicit absolute native storage probe required')
        return {'KEN_STORAGE_PROBE':str(self.probe)}


def storage_environment(prepared:PreparedNativeStorage|None=None)->dict[str,str]:
    if prepared is not None:
        if not isinstance(prepared,PreparedNativeStorage):
            raise ValueError('typed PreparedNativeStorage input required')
        return prepared.environment()
    value=os.environ.get('KEN_STORAGE_PROBE')
    return {} if value is None else PreparedNativeStorage(Path(value)).environment()


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


TRANSFORMER_ENV=('KEN_TRANSFORMER_PROBE','KEN_TRANSFORMER_SOURCES','KEN_TRANSFORMER_REGISTRY',
                 'KEN_TRANSFORMER_MODULE','KEN_TRANSFORMER_CORE','KEN_TRANSFORMER_RUNTIMES')


@dataclass(frozen=True)
class PreparedNativeTransformer:
    """Explicit preparation for one public adapter and one optional native core."""
    probe:Path
    sources:Path
    registry:Path
    module:Path
    core:Path
    runtimes:Path
    acquire:bool=False

    def environment(self)->dict[str,str]:
        values=(self.probe,self.sources,self.registry,self.module,self.core,self.runtimes)
        if any(not isinstance(p,Path) or not p.is_absolute() for p in values):
            raise ValueError('complete absolute prepared transformer paths required')
        if type(self.acquire)is not bool:
            raise ValueError('explicit boolean transformer acquisition policy required')
        return dict(zip(TRANSFORMER_ENV,map(str,values),strict=True))|({'KEN_TRANSFORMER_ACQUIRE':'1'}if self.acquire else {})


TRANSFORMER_TEST_ENV=('KEN_TRANSFORMER_SOURCE_ROOT','KEN_TORCH_CORE','KEN_TORCH_MODULE','KEN_TORCH_PREPARATION')
MLX_TEST_ENV=('KEN_MLX_CORE','KEN_MLX_MODULE')


@dataclass(frozen=True)
class PreparedTransformerTests:
    """Small metadata sources and actual optional cores for workspace regressions."""
    metadata:Path
    torch_core:Path
    torch_module:Path
    torch_preparation:Path
    mlx_core:Path|None=None
    mlx_module:Path|None=None

    def environment(self)->dict[str,str]:
        paths=(self.metadata,self.torch_core,self.torch_module,self.torch_preparation)
        if any(not isinstance(p,Path) or not p.is_absolute() for p in paths):
            raise ValueError('complete absolute transformer test inputs required')
        if (self.mlx_core is None)!=(self.mlx_module is None):
            raise ValueError('complete explicit MLX test inputs required')
        result=dict(zip(TRANSFORMER_TEST_ENV,map(str,paths),strict=True))
        if self.mlx_core is not None:
            if any(not isinstance(p,Path) or not p.is_absolute() for p in (self.mlx_core,self.mlx_module)):
                raise ValueError('absolute MLX test inputs required')
            result.update(dict(zip(MLX_TEST_ENV,map(str,(self.mlx_core,self.mlx_module)),strict=True)))
        return result


def transformer_test_environment(prepared:PreparedTransformerTests|None=None,*,environ:dict|None=None)->dict[str,str]:
    if prepared is not None:
        if not isinstance(prepared,PreparedTransformerTests):raise ValueError('typed transformer test preparation required')
        return prepared.environment()
    source=os.environ if environ is None else environ
    values={key:source[key] for key in (*TRANSFORMER_TEST_ENV,*MLX_TEST_ENV) if key in source}
    if not values:return {}
    if any(key not in values for key in TRANSFORMER_TEST_ENV):
        raise ValueError('complete explicit transformer test inputs required')
    return PreparedTransformerTests(*(Path(values[k]) for k in TRANSFORMER_TEST_ENV),
        mlx_core=Path(values[MLX_TEST_ENV[0]]) if MLX_TEST_ENV[0] in values else None,
        mlx_module=Path(values[MLX_TEST_ENV[1]]) if MLX_TEST_ENV[1] in values else None).environment()
