"""Tests for protobuf-version compatibility helpers.

These use real protobuf descriptors (from descriptor_pb2) so they exercise
whatever protobuf version is installed. protobuf 7 removed
FieldDescriptor.label, which used to break repeated-field detection.
"""

from google.protobuf import descriptor_pb2

from fdb_record_layer import field, nest
from fdb_record_layer._proto_compat import cardinality, is_repeated, is_required

FILE_FIELDS = descriptor_pb2.FileDescriptorProto.DESCRIPTOR.fields_by_name
FIELD_FIELDS = descriptor_pb2.FieldDescriptorProto.DESCRIPTOR.fields_by_name


class _LegacyFieldDescriptor:
    """Mimics protobuf < 5, which only exposes ``label``."""

    def __init__(self, label: int):
        self.label = label


class TestProtoCompatHelpers:
    def test_repeated_field(self):
        assert is_repeated(FILE_FIELDS["dependency"])
        assert cardinality(FILE_FIELDS["dependency"]) == "repeated"

    def test_optional_field(self):
        assert not is_repeated(FILE_FIELDS["name"])
        assert not is_required(FILE_FIELDS["name"])
        assert cardinality(FILE_FIELDS["name"]) == "optional"

    def test_legacy_label_fallback(self):
        assert cardinality(_LegacyFieldDescriptor(1)) == "optional"
        assert cardinality(_LegacyFieldDescriptor(2)) == "required"
        assert cardinality(_LegacyFieldDescriptor(3)) == "repeated"


class TestRepeatedFieldExpressions:
    def test_field_is_repeated_on_real_message(self):
        msg = descriptor_pb2.FileDescriptorProto(name="x.proto", dependency=["a", "b"])
        assert field("dependency")._is_repeated(msg)
        assert not field("name")._is_repeated(msg)

    def test_nest_is_repeated_on_real_message(self):
        msg = descriptor_pb2.DescriptorProto(name="M")
        msg.field.add(name="a")
        assert nest("field", field("name"))._is_repeated(msg)
        assert not nest("options", field("map_entry"))._is_repeated(msg)
