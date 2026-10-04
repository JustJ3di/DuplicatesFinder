from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Iterator, TypeVar


Key = TypeVar("Key")
Value = TypeVar("Value")


@dataclass
class _Node(Generic[Key, Value]):
    leaf: bool = True
    keys: list[Key] = field(default_factory=list)
    values: list[Value] = field(default_factory=list)
    children: list[_Node[Key, Value]] = field(default_factory=list)


class BTreeMap(Generic[Key, Value]):
    """In-memory ordered map backed by a B-tree."""

    def __init__(self, minimum_degree: int = 8) -> None:
        if minimum_degree < 2:
            raise ValueError("minimum_degree must be at least 2")
        self._degree = minimum_degree
        self._root: _Node[Key, Value] = _Node()
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def __iter__(self) -> Iterator[Key]:
        for key, _ in self.items():
            yield key

    def __contains__(self, key: object) -> bool:
        try:
            self._find(self._root, key)  # type: ignore[arg-type]
            return True
        except KeyError:
            return False

    def __getitem__(self, key: Key) -> Value:
        return self._find(self._root, key)

    def __setitem__(self, key: Key, value: Value) -> None:
        existed = key in self
        if len(self._root.keys) == 2 * self._degree - 1:
            new_root: _Node[Key, Value] = _Node(leaf=False, children=[self._root])
            self._split_child(new_root, 0)
            self._root = new_root
        self._insert_non_full(self._root, key, value)
        if not existed:
            self._size += 1

    def get(self, key: Key, default: Value | None = None) -> Value | None:
        try:
            return self[key]
        except KeyError:
            return default

    def items(self) -> Iterator[tuple[Key, Value]]:
        yield from self._iter_items(self._root)

    def values(self) -> Iterator[Value]:
        for _, value in self.items():
            yield value

    def _find(self, node: _Node[Key, Value], key: Key) -> Value:
        index = 0
        while index < len(node.keys) and key > node.keys[index]:
            index += 1
        if index < len(node.keys) and key == node.keys[index]:
            return node.values[index]
        if node.leaf:
            raise KeyError(key)
        return self._find(node.children[index], key)

    def _insert_non_full(self, node: _Node[Key, Value], key: Key, value: Value) -> None:
        index = len(node.keys) - 1
        if node.leaf:
            while index >= 0 and key < node.keys[index]:
                index -= 1
            if index >= 0 and key == node.keys[index]:
                node.values[index] = value
                return
            node.keys.insert(index + 1, key)
            node.values.insert(index + 1, value)
            return

        while index >= 0 and key < node.keys[index]:
            index -= 1
        index += 1
        if index > 0 and key == node.keys[index - 1]:
            node.values[index - 1] = value
            return
        if len(node.children[index].keys) == 2 * self._degree - 1:
            self._split_child(node, index)
            if key == node.keys[index]:
                node.values[index] = value
                return
            if key > node.keys[index]:
                index += 1
        self._insert_non_full(node.children[index], key, value)

    def _split_child(self, parent: _Node[Key, Value], index: int) -> None:
        child = parent.children[index]
        middle = self._degree - 1
        sibling: _Node[Key, Value] = _Node(leaf=child.leaf)
        promoted_key = child.keys[middle]
        promoted_value = child.values[middle]
        sibling.keys = child.keys[middle + 1 :]
        sibling.values = child.values[middle + 1 :]
        child.keys = child.keys[:middle]
        child.values = child.values[:middle]
        if not child.leaf:
            sibling.children = child.children[self._degree :]
            child.children = child.children[: self._degree]

        parent.keys.insert(index, promoted_key)
        parent.values.insert(index, promoted_value)
        parent.children.insert(index + 1, sibling)

    def _iter_items(self, node: _Node[Key, Value]) -> Iterator[tuple[Key, Value]]:
        for index, (key, value) in enumerate(zip(node.keys, node.values)):
            if not node.leaf:
                yield from self._iter_items(node.children[index])
            yield key, value
        if not node.leaf:
            yield from self._iter_items(node.children[-1])