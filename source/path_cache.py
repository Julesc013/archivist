"""Bounded, disposable directory-path caches; SQLite always owns the truth.

The byte budget accounts for retained scalar keys and values using getsizeof.
OrderedDict/container overhead is additional and constrained by the entry limit.
An oversized value is deliberately not cached; callers resolve misses from SQLite.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from typing import TypeVar, Generic

DEFAULT_MAX_ENTRIES = 8192
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
K = TypeVar("K", int, str)
V = TypeVar("V", int, str)


class PathCache(MutableMapping[K, V], Generic[K, V]):
    """LRU mapping for immutable int/string path keys and values.

    Reads update recency; iteration and membership tests do not. Insertion may
    evict entries or decline an oversized entry. This is not an authoritative map.
    """

    __slots__ = ("_data", "_max_entries", "_max_bytes", "_accounted_bytes")

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES, max_bytes: int = DEFAULT_MAX_BYTES):
        if (
            type(max_entries) is not int
            or type(max_bytes) is not int
            or max_entries < 0
            or max_bytes < 0
        ):
            raise ValueError("Cache limits must be finite nonnegative integer counts/bytes")
        self._data: OrderedDict[K, V] = OrderedDict()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._accounted_bytes = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def accounted_bytes(self) -> int:
        return self._accounted_bytes

    @property
    def object_bytes(self) -> int:
        """Diagnostic container/key/value size, not exclusive process allocation."""
        return sys.getsizeof(self) + sys.getsizeof(self._data) + self._accounted_bytes

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[K]:
        # Mapping copies may call __getitem__ while iterating, which updates LRU
        # order. Snapshot only these bounded keys so such reads remain safe.
        return iter(tuple(self._data))

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __getitem__(self, key: K) -> V:
        value = self._data[key]
        self._data.move_to_end(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        if type(key) not in (int, str) or type(value) not in (int, str):
            raise TypeError("Directory path cache keys and values must be int or str")
        if key in self._data:
            del self[key]
        cost = sys.getsizeof(key) + sys.getsizeof(value)
        if self._max_entries == 0 or cost > self._max_bytes:
            return
        while self._data and (
            len(self._data) >= self._max_entries or self._accounted_bytes + cost > self._max_bytes
        ):
            old_key, old_value = self._data.popitem(last=False)
            self._accounted_bytes -= sys.getsizeof(old_key) + sys.getsizeof(old_value)
        self._data[key] = value
        self._accounted_bytes += cost

    def __delitem__(self, key: K) -> None:
        value = self._data.pop(key)
        self._accounted_bytes -= sys.getsizeof(key) + sys.getsizeof(value)

    def items(self):
        return self._data.items()

    def values(self):
        return self._data.values()

    def clear(self) -> None:
        self._data.clear()
        self._accounted_bytes = 0
