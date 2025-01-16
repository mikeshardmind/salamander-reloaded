"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from collections.abc import Generator, Iterable, Mapping, Sequence
from typing import Any

import apsw
from async_utils.gen_transform import ACTX, sync_to_async_gen

type SQLiteValue = int | float | bytes | str | None
type SQLiteValues = tuple[SQLiteValue, ...]
type Bindings = Sequence[SQLiteValue | apsw.zeroblob] | Mapping[str, SQLiteValue | apsw.zeroblob]


async def _a(ctx: ACTX[Any]) -> list[Any]:
    async with ctx as c:
        return [v async for v in c]
    return []


class ExecuteWrapper:
    def __init__(self, _c: ACTX[Any]):
        self._c = _c

    def __await__(self) -> Generator[Any, Any, list[Any]]:
        return _a(self._c).__await__()

    def __aenter__(self):
        return self._c.__aenter__()

    async def __aexit__(self, et: type[BaseException] | None, ev: BaseException | None, tb: object):
        return await self._c.__aexit__(et, ev, tb)

    async def fetchone(self) -> Any | None:
        async with self as g:
            async for val in g:
                return val
        return None


class ConnWrap:
    def __init__(self, path: str):
        self._path = path

    @property
    def _conn(self) -> apsw.Connection:
        return apsw.Connection(self._path)

    @staticmethod
    def _execute(
        conn: apsw.Connection,
        statements: str,
        bindings: Bindings | None = None,
    ) -> Generator[Any]:
        with conn:
            yield from conn.execute(statements, bindings)
        conn.close()

    @staticmethod
    def _executemany(
        conn: apsw.Connection,
        statements: str,
        bindings: Iterable[Bindings],
    ) -> Generator[Any]:
        with conn:
            yield from conn.executemany(statements, bindings)
        conn.close()

    def execute(self, statements: str, bindings: Bindings | None = None) -> ExecuteWrapper:
        return ExecuteWrapper(sync_to_async_gen(self._execute, self._conn, statements, bindings))

    def executemany(self, statements: str, bindings: Iterable[Bindings]) -> ExecuteWrapper:
        return ExecuteWrapper(
            sync_to_async_gen(self._executemany, self._conn, statements, bindings)
        )
