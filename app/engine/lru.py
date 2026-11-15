"""A small thread-safe least-recently-used cache for map tiles and arrays."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

V = TypeVar("V")


class LruCache(Generic[V]):
    """Keeps the `size` most recently used values. A cached None is a value, not a miss."""

    def __init__(self, size: int):
        self._size = size
        self._items: OrderedDict[Hashable, V] = OrderedDict()
        self._lock = threading.Lock()
        self._loading: dict[Hashable, threading.Lock] = {}

    def get(self, key: Hashable) -> tuple[bool, V | None]:
        with self._lock:
            if key not in self._items:
                return False, None
            self._items.move_to_end(key)
            return True, self._items[key]

    def put(self, key: Hashable, value: V) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def get_or_load(self, key: Hashable, load: Callable[[], V]) -> V:
        """The cached value, or load() it once however many threads ask at the same time.

        A failed load isn't cached: its exception reaches the caller, and the next call tries again.
        """
        found, value = self.get(key)
        if found:
            return value  # type: ignore[return-value]
        with self._lock:
            key_lock = self._loading.setdefault(key, threading.Lock())
        with key_lock:
            found, value = self.get(key)
            if found:
                return value  # type: ignore[return-value]
            try:
                value = load()
                self.put(key, value)
                return value
            finally:
                with self._lock:
                    self._loading.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
