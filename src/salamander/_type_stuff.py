"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, NamedTuple, Protocol

import apsw
import discord


class DeleteAllDataFunc(Protocol):
    def __call__(self, conn: apsw.Connection, /) -> Coroutine[Any, Any, Any]: ...


class DeleteUserDataFunc(Protocol):
    def __call__(self, conn: apsw.Connection, user_id: int, /) -> Coroutine[Any, Any, Any]: ...


class DeleteGuildDataFunc(Protocol):
    def __call__(self, conn: apsw.Connection, guild_id: int, /) -> Coroutine[Any, Any, Any]: ...


class DeleteMemberDataFunc(Protocol):
    def __call__(self, conn: apsw.Connection, guild_id: int, user_id: int, /) -> Coroutine[Any, Any, Any]: ...


class RawSubmittable(Protocol):
    @staticmethod
    async def raw_submit(interaction: discord.Interaction[Any], conn: apsw.Connection, data: str) -> None: ...


class BotExports(NamedTuple):
    commands: (
        list[
            discord.app_commands.Group | discord.app_commands.Command[Any, Any, Any] | discord.app_commands.ContextMenu
        ]
        | None
    ) = None
    raw_submits: dict[str, type[RawSubmittable]] | None = None
    delete_all_data_func: DeleteAllDataFunc | None = None
    delete_user_data_func: DeleteUserDataFunc | None = None
    delete_guild_data_func: DeleteGuildDataFunc | None = None
    delete_member_data_func: DeleteMemberDataFunc | None = None
