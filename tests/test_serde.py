from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

import pytest

from quantgen.serde import SchemaError, from_dict, to_dict


@dataclass(frozen=True)
class Circle:
    KIND: ClassVar[str] = "circle"
    radius: float


@dataclass(frozen=True)
class Square:
    KIND: ClassVar[str] = "square"
    side: float


@dataclass(frozen=True)
class Drawing:
    shapes: tuple[Circle | Square, ...]
    labels: Mapping[str, int]
    title: str = "untitled"


def test_round_trip_keeps_union_members_and_mappings():
    drawing = Drawing(shapes=(Circle(1.0), Square(2.0)), labels={"a": 1})

    restored = from_dict(Drawing, to_dict(drawing))

    assert restored.shapes == drawing.shapes
    assert dict(restored.labels) == {"a": 1}


def test_tagged_unions_write_their_kind():
    assert to_dict(Circle(1.0)) == {"kind": "circle", "radius": 1.0}


def test_unknown_keys_are_rejected():
    with pytest.raises(SchemaError, match="colour"):
        from_dict(Circle, {"kind": "circle", "radius": 1.0, "colour": "red"})


def test_missing_keys_are_rejected_unless_defaulted():
    assert from_dict(Drawing, {"shapes": [], "labels": {}}).title == "untitled"
    with pytest.raises(SchemaError):
        from_dict(Drawing, {"shapes": []})


def test_unknown_kind_is_rejected():
    with pytest.raises(SchemaError):
        from_dict(Drawing, {"shapes": [{"kind": "hexagon", "side": 1.0}], "labels": {}})


def test_wrong_scalar_types_are_rejected():
    with pytest.raises(SchemaError):
        from_dict(Circle, {"kind": "circle", "radius": "big"})


def test_loaded_mappings_are_read_only():
    restored = from_dict(Drawing, {"shapes": [], "labels": {"a": 1}})

    with pytest.raises(TypeError):
        restored.labels["b"] = 2


@dataclass(frozen=True)
class Knob:
    amount: float | tuple[float, float]


def test_plain_unions_take_the_first_type_that_fits():
    assert from_dict(Knob, {"amount": 2}).amount == 2.0
    assert from_dict(Knob, {"amount": [1, 3]}).amount == (1.0, 3.0)


def test_plain_unions_reject_values_that_fit_no_type():
    with pytest.raises(SchemaError, match="expected one of"):
        from_dict(Knob, {"amount": "lots"})
