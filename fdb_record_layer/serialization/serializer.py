"""Record serializer protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from google.protobuf.descriptor import Descriptor
    from google.protobuf.message import Message

M = TypeVar("M", bound="Message")


class RecordSerializer(ABC):
    """Abstract base for record serialization.

    A RecordSerializer handles converting between protobuf messages
    and bytes for storage in FoundationDB.

    Different implementations can provide:
    - Compression
    - Encryption
    - Custom encoding formats
    """

    @abstractmethod
    def serialize(self, record: Message) -> bytes:
        """Serialize a record to bytes.

        Args:
            record: The protobuf message to serialize.

        Returns:
            The serialized bytes.
        """
        pass

    @abstractmethod
    def deserialize(self, data: bytes, descriptor: Descriptor) -> Message:
        """Deserialize bytes to a record.

        Args:
            data: The serialized bytes.
            descriptor: The message Descriptor for the record type.

        Returns:
            The deserialized protobuf message.
        """
        pass

    @abstractmethod
    def deserialize_typed(self, data: bytes, message_class: type[M]) -> M:
        """Deserialize bytes to a specific message type.

        Args:
            data: The serialized bytes.
            message_class: The message class to deserialize to.

        Returns:
            The deserialized protobuf message of the specified type.
        """
        pass
