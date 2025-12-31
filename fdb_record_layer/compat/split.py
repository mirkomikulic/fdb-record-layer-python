"""Record splitting for large records.

The Java Record Layer splits records larger than 100KB across multiple
key-value pairs. This module provides compatible splitting/unsplitting.

See: com.apple.foundationdb.record.provider.foundationdb.SplitHelper
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb import Transaction
    from fdb.subspace_impl import Subspace

# Maximum size before splitting (same as Java)
SPLIT_RECORD_SIZE = 100_000  # 100KB

# Key suffix constants (same as Java)
UNSPLIT_RECORD = 0  # Suffix for unsplit records
START_SPLIT_RECORD = 1  # First chunk index for split records
RECORD_VERSION = -1  # Suffix for record version


class SplitHelper:
    """Helper for splitting and unsplitting large records.

    Records larger than SPLIT_RECORD_SIZE are split across multiple
    key-value pairs, with each chunk stored under an incrementing suffix.
    """

    @staticmethod
    def needs_split(data: bytes) -> bool:
        """Check if data needs to be split."""
        return len(data) > SPLIT_RECORD_SIZE

    @staticmethod
    def save_possibly_split(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
        data: bytes,
        omit_unsplit_suffix: bool = False,
    ) -> int:
        """Save a record, splitting if necessary.

        Args:
            tr: FDB transaction
            subspace: Records subspace
            primary_key: Record's primary key tuple
            data: Serialized record bytes
            omit_unsplit_suffix: If True, don't add suffix for small records
                                 (older format versions)

        Returns:
            Number of key-value pairs written
        """
        if len(data) <= SPLIT_RECORD_SIZE:
            # Single key-value pair
            if omit_unsplit_suffix:
                key = subspace.pack(primary_key)
            else:
                key = subspace.pack(primary_key + (UNSPLIT_RECORD,))
            tr.set(key, data)
            return 1

        # Split into chunks
        record_subspace = subspace.subspace(primary_key)
        chunk_index = START_SPLIT_RECORD
        offset = 0

        while offset < len(data):
            chunk = data[offset : offset + SPLIT_RECORD_SIZE]
            key = record_subspace.pack((chunk_index,))
            tr.set(key, chunk)
            chunk_index += 1
            offset += SPLIT_RECORD_SIZE

        return chunk_index - START_SPLIT_RECORD

    @staticmethod
    def delete_possibly_split(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Delete a record that may be split.

        Clears the entire primary key range to handle both split and unsplit.
        """
        record_subspace = subspace.subspace(primary_key)
        start, end = record_subspace.range()
        tr.clear_range(start, end)

    @staticmethod
    async def load_possibly_split(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
    ) -> bytes | None:
        """Load a record that may be split.

        Args:
            tr: FDB transaction
            subspace: Records subspace
            primary_key: Record's primary key tuple

        Returns:
            Reassembled record bytes, or None if not found
        """
        import asyncio

        # Try unsplit first (most common case)
        unsplit_key = subspace.pack(primary_key + (UNSPLIT_RECORD,))

        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(None, lambda: tr[unsplit_key])

        if value.present():
            return bytes(value)

        # Try without suffix (older format)
        bare_key = subspace.pack(primary_key)
        value = await loop.run_in_executor(None, lambda: tr[bare_key])

        if value.present():
            return bytes(value)

        # Try to load split record
        record_subspace = subspace.subspace(primary_key)
        start, end = record_subspace.range()

        # Get all chunks
        chunks: list[tuple[int, bytes]] = []

        def read_range():
            return list(tr.get_range(start, end))

        kvs = await loop.run_in_executor(None, read_range)

        if not kvs:
            return None

        for kv in kvs:
            # Unpack the suffix
            suffix_tuple = record_subspace.unpack(kv.key)
            if suffix_tuple and len(suffix_tuple) == 1:
                suffix = suffix_tuple[0]
                if isinstance(suffix, int) and suffix >= START_SPLIT_RECORD:
                    chunks.append((suffix, bytes(kv.value)))

        if not chunks:
            return None

        # Reassemble in order
        chunks.sort(key=lambda x: x[0])
        return b"".join(chunk for _, chunk in chunks)

    @staticmethod
    def save_version(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
        version: bytes,
    ) -> None:
        """Save a record version.

        Args:
            tr: FDB transaction
            subspace: Records subspace
            primary_key: Record's primary key tuple
            version: Packed version bytes (10 bytes for versionstamp)
        """
        key = subspace.pack(primary_key + (RECORD_VERSION,))
        tr.set(key, version)

    @staticmethod
    async def load_version(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
    ) -> bytes | None:
        """Load a record version.

        Args:
            tr: FDB transaction
            subspace: Records subspace
            primary_key: Record's primary key tuple

        Returns:
            Version bytes, or None if not found
        """
        import asyncio

        key = subspace.pack(primary_key + (RECORD_VERSION,))

        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(None, lambda: tr[key])

        if value.present():
            return bytes(value)
        return None

    @staticmethod
    def delete_version(
        tr: Transaction,
        subspace: Subspace,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Delete a record version."""
        key = subspace.pack(primary_key + (RECORD_VERSION,))
        tr.clear(key)
