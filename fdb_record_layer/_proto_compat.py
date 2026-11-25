"""Helpers that paper over protobuf API differences between versions.

``FieldDescriptor.label`` was removed in protobuf 7. Newer releases expose
``is_repeated`` / ``is_required`` instead, while older releases (< 5.x) only
have ``label``. These helpers work with both.
"""

from __future__ import annotations

from typing import Any, Literal

# Values of FieldDescriptorProto.Label (stable across all protobuf versions).
_LABEL_REQUIRED = 2
_LABEL_REPEATED = 3

Cardinality = Literal["optional", "required", "repeated"]


def is_repeated(field: Any) -> bool:
    """Return True if the protobuf field descriptor is a repeated field."""
    value = getattr(field, "is_repeated", None)
    if value is not None:
        return bool(value() if callable(value) else value)
    return getattr(field, "label", None) == _LABEL_REPEATED


def is_required(field: Any) -> bool:
    """Return True if the protobuf field descriptor is a proto2 required field."""
    value = getattr(field, "is_required", None)
    if value is not None:
        return bool(value() if callable(value) else value)
    return getattr(field, "label", None) == _LABEL_REQUIRED


def cardinality(field: Any) -> Cardinality:
    """Return the field's cardinality as 'optional', 'required' or 'repeated'."""
    if is_repeated(field):
        return "repeated"
    if is_required(field):
        return "required"
    return "optional"
