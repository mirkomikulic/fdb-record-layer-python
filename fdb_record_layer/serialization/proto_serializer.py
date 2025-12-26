"""Protobuf-based record serializer."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from google.protobuf import symbol_database

from fdb_record_layer.core.exceptions import SerializationException
from fdb_record_layer.serialization.serializer import RecordSerializer

if TYPE_CHECKING:
    from google.protobuf.descriptor import Descriptor
    from google.protobuf.message import Message

M = TypeVar("M", bound="Message")


class ProtobufSerializer(RecordSerializer):
    """Standard protobuf serializer.

    Uses protobuf's built-in serialization for converting messages
    to and from bytes.
    """

    def __init__(self) -> None:
        self._symbol_db = symbol_database.Default()
        self._class_cache: dict[str, type[Message]] = {}

    def serialize(self, record: Message) -> bytes:
        """Serialize a record using protobuf binary format.

        Args:
            record: The protobuf message.

        Returns:
            The serialized bytes.

        Raises:
            SerializationException: If serialization fails.
        """
        try:
            return record.SerializeToString()
        except Exception as e:
            raise SerializationException(f"Failed to serialize record: {e}") from e

    def deserialize(self, data: bytes, descriptor: Descriptor) -> Message:
        """Deserialize using a message descriptor.

        Creates a dynamic message instance from the descriptor.

        Args:
            data: The serialized bytes.
            descriptor: The message Descriptor.

        Returns:
            The deserialized message.

        Raises:
            SerializationException: If deserialization fails.
        """
        try:
            # Try to get from cache first
            full_name = descriptor.full_name
            if full_name in self._class_cache:
                message_class = self._class_cache[full_name]
            else:
                # Get message class from symbol database
                message_class = self._symbol_db.GetSymbol(full_name)
                self._class_cache[full_name] = message_class

            message = message_class()
            message.ParseFromString(data)
            return message
        except Exception as e:
            raise SerializationException(f"Failed to deserialize record: {e}") from e

    def deserialize_typed(self, data: bytes, message_class: type[M]) -> M:
        """Deserialize to a specific message type.

        Args:
            data: The serialized bytes.
            message_class: The message class.

        Returns:
            The deserialized message.

        Raises:
            SerializationException: If deserialization fails.
        """
        try:
            message = message_class()
            message.ParseFromString(data)
            return message
        except Exception as e:
            raise SerializationException(f"Failed to deserialize record: {e}") from e


class CompressedSerializer(RecordSerializer):
    """Serializer that compresses data using zlib."""

    def __init__(self, level: int = 6) -> None:
        """Initialize with compression level.

        Args:
            level: Compression level (0-9). Default is 6.
        """
        import zlib

        self._inner = ProtobufSerializer()
        self._level = level
        self._zlib = zlib

    def serialize(self, record: Message) -> bytes:
        """Serialize and compress."""
        data = self._inner.serialize(record)
        return self._zlib.compress(data, self._level)

    def deserialize(self, data: bytes, descriptor: Descriptor) -> Message:
        """Decompress and deserialize."""
        decompressed = self._zlib.decompress(data)
        return self._inner.deserialize(decompressed, descriptor)

    def deserialize_typed(self, data: bytes, message_class: type[M]) -> M:
        """Decompress and deserialize to type."""
        decompressed = self._zlib.decompress(data)
        return self._inner.deserialize_typed(decompressed, message_class)


# Default serializer instance
_default_serializer = ProtobufSerializer()


def get_default_serializer() -> ProtobufSerializer:
    """Get the default protobuf serializer."""
    return _default_serializer
