"""Closed, versioned JSON codec for immutable compilation artifacts."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import json
import math
import types
from typing import Any, get_args, get_origin, get_type_hints

from .compiler import Program, Scan, Action
from .compilation import Prepared
from .syntax.ast import Expr, Parameter, Span, TypeName, Clause, SourceExpr, Declaration
from .logic import Predicate
from .body import BodyPattern

CODEC='kql2-prepared-json/1'
_CLASSES: dict[str,type[Any]]={cls.__name__:cls for cls in (Prepared,Program,Scan,Action,Expr,Parameter,Span,TypeName,Predicate,Clause,SourceExpr,BodyPattern,Declaration)}
_HINTS={name:get_type_hints(cls) for name,cls in _CLASSES.items()}


def encode(prepared: Prepared) -> bytes:
    def item(value: object) -> object:
        if is_dataclass(value) and not isinstance(value,type):
            if type(value).__name__ not in _CLASSES:
                raise ValueError('unregistered artifact type')
            return {'tag':type(value).__name__,'fields':{f.name:item(getattr(value,f.name)) for f in fields(value)}}
        if isinstance(value,tuple):
            return {'tuple':[item(v) for v in value]}
        if value is None or type(value) in (str,int,bool,float):
            return value
        raise ValueError('unsupported artifact value')
    return json.dumps(item(prepared),ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def decode(payload: bytes, *, max_bytes: int) -> Prepared:
    if len(payload)>max_bytes:
        raise ValueError('artifact exceeds decode budget')
    def valid(value: object, expected: Any) -> bool:
        origin=get_origin(expected)
        if origin is types.UnionType:
            return any(valid(value,t) for t in get_args(expected))
        if origin is tuple:
            if not isinstance(value,tuple):
                return False
            args=get_args(expected)
            if len(args)==2 and args[1] is Ellipsis:
                return all(valid(v,args[0]) for v in value)
            return len(args)==len(value) and all(valid(v,t) for v,t in zip(value,args))
        return type(value) is expected
    def item(value: object, depth: int = 0) -> object:
        if depth>128:
            raise ValueError('artifact nesting limit')
        if isinstance(value,dict):
            if set(value)=={'tuple'} and isinstance(value['tuple'],list):
                return tuple(item(v,depth+1) for v in value['tuple'])
            if set(value)!={'tag','fields'} or not isinstance(value['tag'],str) or value['tag'] not in _CLASSES:
                raise ValueError('invalid artifact tag')
            name=value['tag']; data=value['fields']; hints=_HINTS[name]
            if not isinstance(data,dict) or set(data)!=set(hints):
                raise ValueError('artifact schema mismatch')
            args={key:item(val,depth+1) for key,val in data.items()}
            if not all(valid(args[key],hints[key]) for key in args):
                raise ValueError('artifact field type mismatch')
            return _CLASSES[name](**args)
        if value is None or type(value) in (str,int,bool,float):
            if isinstance(value,float) and not math.isfinite(value):
                raise ValueError('nonfinite artifact value')
            return value
        raise ValueError('unsupported JSON artifact')
    try:
        value=item(json.loads(payload))
    except (RecursionError,UnicodeError,TypeError) as exc:
        raise ValueError('invalid compiled artifact') from exc
    if not isinstance(value,Prepared):
        raise ValueError('expected prepared program')
    return value
