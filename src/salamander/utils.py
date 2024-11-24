"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

import msgspec
import platformdirs
from base2048 import decode, encode

platformdir_stuff = platformdirs.PlatformDirs(
    "salamander", "mikeshardmind", roaming=False
)

T = TypeVar("T")

__all__ = ["b2048pack", "b2048unpack", "resolve_path_with_links"]


def _get_stored_token() -> str | None:
    token_file_path = platformdir_stuff.user_config_path / "salamander.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="r") as fp:
        data = fp.read()
        return decode(data).decode("utf-8") if data else None


def store_token(token: str, /):
    token_file_path = platformdir_stuff.user_config_path / "salamander.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="w") as fp:
        fp.write(encode(token.encode()))


def get_token() -> str:
    # TODO: alternative token stores: systemdcreds, etc
    token = os.getenv("SALAMANDER_TOKEN") or _get_stored_token()
    if not token:
        msg = (
            "NO TOKEN? (Use Environment `SALAMANDER_TOKEN`"
            "or launch with `--setup` to go through interactive setup)"
        )
        raise RuntimeError(msg) from None
    return token


def b2048pack(obj: object, /) -> str:
    return encode(msgspec.msgpack.encode(obj))


def b2048unpack(packed: str, typ: type[T], /) -> T:
    return msgspec.msgpack.decode(decode(packed), type=typ)


def resolve_path_with_links(path: Path, folder: bool = False) -> Path:
    """
    Python only resolves with strict=True if the path exists.
    """
    try:
        return path.resolve(strict=True)
    except FileNotFoundError:
        path = resolve_path_with_links(path.parent, folder=True) / path.name
        if folder:
            # python's default is world read/write/traversable... (0o777)
            path.mkdir(mode=0o700)
        else:
            # python's default is world read/writable... (0o666)
            path.touch(mode=0o600)
        return path.resolve(strict=True)
