"""Strict conversion between frozen dataclasses and JSON-compatible dicts.

Unknown keys, missing keys and wrong types are errors, so a stale or hand-edited params file fails loudly at load time.
A field typed as a union of dataclasses is resolved by the `kind` key, matched against each class's KIND. A union of
plain types (such as `float | tuple[float, float]`) takes the first type the value converts to.
"""

import dataclasses
import types
import typing
from collections.abc import Mapping
from typing import Any


class SchemaError(ValueError):
    pass


def to_dict(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out = {"kind": value.KIND} if hasattr(value, "KIND") else {}
        out.update({field.name: to_dict(getattr(value, field.name)) for field in dataclasses.fields(value)})
        return out
    if isinstance(value, Mapping):
        return {key: to_dict(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_dict(item) for item in value]
    return value


def from_dict[T](cls: type[T], data: Any, path: str = "$") -> T:
    return _convert(cls, data, path)


def _convert(tp: Any, data: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        return _convert_union(typing.get_args(tp), data, path)
    if dataclasses.is_dataclass(tp):
        return _convert_dataclass(tp, data, path)
    if origin is tuple:
        return _convert_tuple(typing.get_args(tp), data, path)
    if origin in (dict, Mapping) or tp in (dict, Mapping):
        if not isinstance(data, dict):
            raise SchemaError(f"{path}: expected an object")
        value_type = typing.get_args(tp)[1]
        return types.MappingProxyType({key: _convert(value_type, item, f"{path}.{key}") for key, item in data.items()})
    return _convert_scalar(tp, data, path)


def _convert_union(options: tuple[Any, ...], data: Any, path: str) -> Any:
    if data is None and type(None) in options:
        return None
    candidates = [option for option in options if option is not type(None)]
    if len(candidates) == 1:
        return _convert(candidates[0], data, path)
    tagged = [option for option in candidates if dataclasses.is_dataclass(option)]
    if tagged:
        if not isinstance(data, dict) or "kind" not in data:
            raise SchemaError(f"{path}: expected an object with a 'kind'")
        for option in tagged:
            if getattr(option, "KIND", None) == data["kind"]:
                return _convert_dataclass(option, data, path)
        raise SchemaError(f"{path}: unknown kind {data['kind']!r}")
    for option in candidates:
        try:
            return _convert(option, data, path)
        except SchemaError:
            continue
    raise SchemaError(f"{path}: expected one of {', '.join(_type_name(option) for option in candidates)}")


def _type_name(tp: Any) -> str:
    return getattr(tp, "__name__", None) or str(tp)


def _convert_dataclass(cls: Any, data: Any, path: str) -> Any:
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: expected an object for {cls.__name__}")
    hints = typing.get_type_hints(cls)
    fields = {field.name: field for field in dataclasses.fields(cls)}
    unknown = set(data) - set(fields) - {"kind"}
    if unknown:
        raise SchemaError(f"{path}: unknown keys {sorted(unknown)} for {cls.__name__}")
    values = {}
    for name, field in fields.items():
        if name in data:
            values[name] = _convert(hints[name], data[name], f"{path}.{name}")
        elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            raise SchemaError(f"{path}: missing key {name!r} for {cls.__name__}")
    return cls(**values)


def _convert_tuple(args: tuple[Any, ...], data: Any, path: str) -> tuple[Any, ...]:
    if not isinstance(data, list | tuple):
        raise SchemaError(f"{path}: expected a list")
    if len(args) == 2 and args[1] is Ellipsis:
        return tuple(_convert(args[0], item, f"{path}[{i}]") for i, item in enumerate(data))
    if len(args) != len(data):
        raise SchemaError(f"{path}: expected {len(args)} items, got {len(data)}")
    return tuple(_convert(arg, item, f"{path}[{i}]") for i, (arg, item) in enumerate(zip(args, data, strict=True)))


def _convert_scalar(tp: Any, data: Any, path: str) -> Any:
    if tp is float:
        if isinstance(data, bool) or not isinstance(data, int | float):
            raise SchemaError(f"{path}: expected a number")
        return float(data)
    if tp is int:
        if isinstance(data, bool) or not isinstance(data, int):
            raise SchemaError(f"{path}: expected an integer")
        return data
    if tp in (str, bool):
        if not isinstance(data, tp):
            raise SchemaError(f"{path}: expected {tp.__name__}")
        return data
    raise SchemaError(f"{path}: unsupported type {tp!r}")
