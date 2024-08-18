"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from pathlib import Path
from typing import Generic, TypeVar

import msgspec
import platformdirs
from base2048 import decode, encode

platformdir_stuff = platformdirs.PlatformDirs("salamander", "mikeshardmind", roaming=False)

K = TypeVar("K")
V = TypeVar("V")
T = TypeVar("T")


def b2048pack(obj: object, /) -> str:
    return encode(msgspec.msgpack.encode(obj))


def b2048unpack(packed: str, typ: type[T], /) -> T:
    return msgspec.msgpack.decode(decode(packed), type=typ)


class LRU(Generic[K, V]):
    def __init__(self, maxsize: int, /):
        self.cache: dict[K, V] = {}
        self.maxsize = maxsize

    def get(self, key: K, default: T, /) -> V | T:
        if key not in self.cache:
            return default
        self.cache[key] = self.cache.pop(key)
        return self.cache[key]

    def __getitem__(self, key: K, /) -> V:
        self.cache[key] = self.cache.pop(key)
        return self.cache[key]

    def __setitem__(self, key: K, value: V, /) -> None:
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.pop(next(iter(self.cache)))

    def remove(self, key: K) -> None:
        self.cache.pop(key, None)


def resolve_path_with_links(path: Path, folder: bool = False) -> Path:
    """
    Python only resolves with strict=True if the path exists.
    """
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        path = resolve_path_with_links(path.parent, folder=True) / path.name
        if folder:
            path.mkdir(mode=0o700)  # python's default is world read/write/traversable... (0o777)
        else:
            path.touch(mode=0o600)  # python's default is world read/writable... (0o666)
        return path.resolve(strict=True)
