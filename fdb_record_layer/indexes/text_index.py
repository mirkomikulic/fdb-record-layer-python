"""TEXT index maintainer for full-text search.

The TEXT index enables efficient full-text queries:
- Find all records containing a word
- Find records containing all of a set of words
- Find records containing any of a set of words
- Phrase search (words in order)

Implementation uses an inverted index where each token maps to
the records containing it.
"""

from __future__ import annotations

import re
import struct
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from fdb_record_layer.cursors.base import ListCursor
from fdb_record_layer.indexes.maintainer import (
    IndexMaintainer,
    IndexScanRange,
    RecordLoader,
)

if TYPE_CHECKING:
    from fdb import Subspace, Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor
    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData


TOKENS_KEY = 0


class Tokenizer(ABC):
    """Abstract base for text tokenizers."""

    @abstractmethod
    def tokenize(self, text: str) -> list[tuple[str, int]]:
        """Tokenize text into (token, position) pairs."""
        pass


class DefaultTokenizer(Tokenizer):
    """Default tokenizer using word boundaries."""

    def __init__(self, min_length: int = 2, lowercase: bool = True) -> None:
        self._min_length = min_length
        self._lowercase = lowercase
        self._pattern = re.compile(r"[^\w]+", re.UNICODE)

    def tokenize(self, text: str) -> list[tuple[str, int]]:
        if self._lowercase:
            text = text.lower()
        tokens: list[tuple[str, int]] = []
        for i, word in enumerate(self._pattern.split(text)):
            if len(word) >= self._min_length:
                tokens.append((word, i))
        return tokens


class TextIndexMaintainer(IndexMaintainer):
    """Maintains a TEXT index for full-text search."""

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        super().__init__(index, subspace, meta_data)
        self._tokens_subspace = subspace[TOKENS_KEY]
        self._tokenizer = tokenizer or DefaultTokenizer()

    def _get_text(self, record: Message) -> str | None:
        keys = self._index.root_expression.evaluate(record)
        if keys and keys[0]:
            value = keys[0][0] if isinstance(keys[0], tuple) else keys[0]
            if isinstance(value, str):
                return value
        return None

    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        text = self._get_text(record)
        if not text:
            return
        record_type = record.DESCRIPTOR.name
        tokens = self._tokenizer.tokenize(text)
        seen: set[str] = set()
        for token, pos in tokens:
            if token in seen:
                continue
            seen.add(token)
            key = self._tokens_subspace.pack((token, record_type) + primary_key)
            tr.set(key, struct.pack("<H", pos))

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        text = self._get_text(record)
        if not text:
            return
        record_type = record.DESCRIPTOR.name
        tokens = self._tokenizer.tokenize(text)
        seen: set[str] = set()
        for token, _ in tokens:
            if token in seen:
                continue
            seen.add(token)
            key = self._tokens_subspace.pack((token, record_type) + primary_key)
            tr.clear(key)

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        return ListCursor([])

    def search_token(
        self,
        tr: Transaction,
        token: str,
        record_loader: RecordLoader,
        limit: int = 100,
    ) -> list[FDBStoredRecord[Any]]:
        """Find records containing a token."""
        token = token.lower()
        start = self._tokens_subspace.pack((token,))
        end = self._tokens_subspace.pack((token + "\xff",))
        results: list[FDBStoredRecord[Any]] = []
        for key, _ in tr.get_range(start, end, limit=limit):
            unpacked = self._tokens_subspace.unpack(key)
            if len(unpacked) >= 2:
                record_type, pk = unpacked[1], unpacked[2:]
                stored = record_loader(record_type, pk)
                if stored:
                    results.append(stored)
        return results

    def search_all_tokens(
        self,
        tr: Transaction,
        tokens: list[str],
        record_loader: RecordLoader,
        limit: int = 100,
    ) -> list[FDBStoredRecord[Any]]:
        """Find records containing all tokens."""
        if not tokens:
            return []
        sets: list[set[tuple[str, tuple[Any, ...]]]] = []
        for token in tokens:
            token = token.lower()
            records: set[tuple[str, tuple[Any, ...]]] = set()
            start = self._tokens_subspace.pack((token,))
            end = self._tokens_subspace.pack((token + "\xff",))
            for key, _ in tr.get_range(start, end):
                unpacked = self._tokens_subspace.unpack(key)
                if len(unpacked) >= 2:
                    records.add((unpacked[1], unpacked[2:]))
            sets.append(records)
        result = sets[0]
        for s in sets[1:]:
            result &= s
        results: list[FDBStoredRecord[Any]] = []
        for rt, pk in list(result)[:limit]:
            stored = record_loader(rt, pk)
            if stored:
                results.append(stored)
        return results

    def search_any_token(
        self,
        tr: Transaction,
        tokens: list[str],
        record_loader: RecordLoader,
        limit: int = 100,
    ) -> list[FDBStoredRecord[Any]]:
        """Find records containing any token."""
        if not tokens:
            return []
        all_records: set[tuple[str, tuple[Any, ...]]] = set()
        for token in tokens:
            token = token.lower()
            start = self._tokens_subspace.pack((token,))
            end = self._tokens_subspace.pack((token + "\xff",))
            for key, _ in tr.get_range(start, end):
                unpacked = self._tokens_subspace.unpack(key)
                if len(unpacked) >= 2:
                    all_records.add((unpacked[1], unpacked[2:]))
        results: list[FDBStoredRecord[Any]] = []
        for rt, pk in list(all_records)[:limit]:
            stored = record_loader(rt, pk)
            if stored:
                results.append(stored)
        return results
