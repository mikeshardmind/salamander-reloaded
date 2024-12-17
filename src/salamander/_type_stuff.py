"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any, Literal, NamedTuple, Protocol

import apsw
import msgspec
from discord import Interaction as DInter
from discord import app_commands, ui
from scheduler import DiscordBotScheduler


class SalamanderLike(Protocol):
    sched: DiscordBotScheduler
    conn: apsw.Connection


class Reminder(msgspec.Struct, gc=False, frozen=True, array_like=True):
    content: str
    context: str | None = None
    recur: Literal["Daily", "Weekly"] | None = None


class DynButton(ui.Button[ui.View]):
    async def callback(self, interaction: DInter) -> Any:
        pass


type Coro[T] = Coroutine[None, None, T]


class DeleteAllDataFunc(Protocol):
    def __call__(self, client: SalamanderLike, /) -> Coro[Any]: ...


class DeleteUserDataFunc(Protocol):
    def __call__(self, client: SalamanderLike, user_id: int, /) -> Coro[Any]: ...


class DeleteGuildDataFunc(Protocol):
    def __call__(self, client: SalamanderLike, guild_id: int, /) -> Coro[Any]: ...


class DeleteMemberDataFunc(Protocol):
    def __call__(self, client: SalamanderLike, guild_id: int, user_id: int, /) -> Coro[Any]: ...


class RawSubmittableCls(Protocol):
    @classmethod
    async def raw_submit(cls, interaction: DInter, data: str) -> Any: ...


class GetUserDataFunc(Protocol):
    def __call__(self, client: SalamanderLike, /) -> Coro[bytes]: ...


class RawSubmittableStatic(Protocol):
    @staticmethod
    async def raw_submit(interaction: DInter, data: str) -> Any: ...


type RawSubmittable = RawSubmittableCls | RawSubmittableStatic
type ACommand = app_commands.Command[Any, Any, Any]
type AppCommandTypes = app_commands.Group | ACommand | app_commands.ContextMenu


class BotExports(NamedTuple):
    commands: list[AppCommandTypes] | None = None
    raw_modal_submits: dict[str, type[RawSubmittable]] | None = None
    raw_button_submits: dict[str, type[RawSubmittable]] | None = None
    delete_all_data_func: DeleteAllDataFunc | None = None
    delete_user_data_func: DeleteUserDataFunc | None = None
    delete_guild_data_func: DeleteGuildDataFunc | None = None
    delete_member_data_func: DeleteMemberDataFunc | None = None
    get_user_data_func: GetUserDataFunc | None = None


class HasExports(Protocol):
    exports: BotExports
