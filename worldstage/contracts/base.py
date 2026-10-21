"""Shared plumbing for every contract: canonical JSON, content hashes, dict round-trips, JSON Schema.

A contract is a frozen dataclass. Its JSON Schema is generated from the type hints, so the two cannot drift;
tests compare the generated schema with the committed file.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import types
import unicodedata
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints


def _normalise(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _normalise(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {unicodedata.normalize("NFC", str(k)): _normalise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalise(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    return obj


def canonical_json(obj: Any) -> str:
    """UTF-8, sorted keys, no insignificant whitespace, floats at 6 places, NFC strings."""
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def hash_without(obj: Any, *fields: str) -> str:
    """Hash of a contract excluding self-referential fields such as its own hash."""
    data = _normalise(obj)
    for f in fields:
        data.pop(f, None)
    return content_hash(data)


def to_dict(obj: Any) -> Any:
    return _normalise(obj)


def from_dict(cls: type, data: Any) -> Any:
    """Rebuild a (nested) frozen dataclass from plain JSON data."""
    return _build(cls, data)


def _build(tp: Any, value: Any) -> Any:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        options = [a for a in get_args(tp) if a is not type(None)]
        if value is None:
            return None
        return _build(options[0], value)
    if origin in (list, tuple):
        (inner, *_rest) = get_args(tp) or (Any,)
        items = [_build(inner, v) for v in value]
        return tuple(items) if origin is tuple else items
    if origin is dict:
        args = get_args(tp)
        inner = args[1] if len(args) == 2 else Any
        return {k: _build(inner, v) for k, v in value.items()}
    if origin is Literal or tp in (Any, str, int, float, bool, type(None)):
        return value
    if dataclasses.is_dataclass(tp):
        hints = get_type_hints(tp)
        kwargs = {f.name: _build(hints[f.name], value[f.name]) for f in dataclasses.fields(tp) if f.name in value}
        return tp(**kwargs)
    return value


def schema_for(cls: type, _defs: dict | None = None) -> dict:
    """JSON Schema (draft 2020-12) generated from a dataclass's type hints."""
    top = _defs is None
    defs: dict = {} if _defs is None else _defs
    _register(cls, defs)
    if not top:
        return {"$ref": f"#/$defs/{cls.__name__}"}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": f"#/$defs/{cls.__name__}", "$defs": dict(sorted(defs.items()))}


def _register(cls: type, defs: dict) -> None:
    if cls.__name__ in defs:
        return
    defs[cls.__name__] = {}  # placeholder stops recursion
    hints = get_type_hints(cls)
    props, required = {}, []
    for f in dataclasses.fields(cls):
        props[f.name] = _type_schema(hints[f.name], defs)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            required.append(f.name)
    defs[cls.__name__] = {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _type_schema(tp: Any, defs: dict) -> dict:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        return {"anyOf": [_type_schema(a, defs) for a in get_args(tp)]}
    if origin in (list, tuple):
        args = get_args(tp)
        return {"type": "array", "items": _type_schema(args[0], defs) if args else {}}
    if origin is dict:
        args = get_args(tp)
        return {"type": "object", "additionalProperties": _type_schema(args[1], defs) if len(args) == 2 else {}}
    if origin is Literal:
        return {"enum": list(get_args(tp))}
    if tp is str:
        return {"type": "string"}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is type(None):
        return {"type": "null"}
    if dataclasses.is_dataclass(tp):
        _register(tp, defs)
        return {"$ref": f"#/$defs/{tp.__name__}"}
    return {}
