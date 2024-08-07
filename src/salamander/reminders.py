"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from typing import Any

import apsw
import discord
from scheduler import DiscordBotScheduler, ScheduledDispatch

from ._type_stuff import BotExports, DynButton, Reminder
from .utils import LRU, b2048pack, b2048unpack

reminder_group = discord.app_commands.Group(name="remindme", description="remind yourself about something, later")


TRASH_EMOJI = "\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"


class ReminderView:
    @staticmethod
    def index_setup(items: list[ScheduledDispatch], index: int) -> tuple[discord.Embed, bool, bool, str]:
        ln = len(items)
        index %= ln

        item = items[index]
        reminder = item.unpack_extra(Reminder)
        assert reminder
        ts = item.get_arrow_time()
        embed = discord.Embed(description=reminder.content, timestamp=ts.datetime)
        return embed, index == 0, index == ln - 1, item.task_id

    @classmethod
    async def start(cls, itx: discord.Interaction[Any], user_id: int) -> None:
        await cls.edit_to_current_index(itx, user_id, 0, first=True)

    @classmethod
    async def edit_to_current_index(
        cls,
        itx: discord.Interaction[Any],
        user_id: int,
        index: int,
        first: bool = False,
    ) -> None:
        sched: DiscordBotScheduler = itx.client.sched
        _l = await sched.list_event_schedule_for_user("reminder", user_id)

        if not _l:
            if first:
                await itx.response.send_message("You have no reminders set", ephemeral=True)
            else:
                await itx.response.edit_message(content="You no longer have any reminders set", view=None, embed=None)
            return

        element, first_disabled, last_disabled, tid = cls.index_setup(_l, index)
        v = discord.ui.View(timeout=10)

        c_id = "b:rmndrlst:" + b2048pack(("first", user_id, 0, tid))
        v.add_item(DynButton(label="<<", style=discord.ButtonStyle.gray, custom_id=c_id, disabled=first_disabled))
        c_id = "b:rmndrlst:" + b2048pack(("previous", user_id, index - 1, tid))
        v.add_item(DynButton(label="<", style=discord.ButtonStyle.gray, custom_id=c_id))
        c_id = "b:rmndrlst:" + b2048pack(("delete", user_id, index, tid))
        v.add_item(DynButton(emoji=TRASH_EMOJI, style=discord.ButtonStyle.red, custom_id=c_id))
        c_id = "b:rmndrlst:" + b2048pack(("next", user_id, index + 1, tid))
        v.add_item(DynButton(label=">", style=discord.ButtonStyle.gray, custom_id=c_id))
        c_id = "b:rmndrlst:" + b2048pack(("last", user_id, len(_l) - 1, tid))
        v.add_item(DynButton(label=">>", style=discord.ButtonStyle.gray, custom_id=c_id, disabled=last_disabled))

        if first:
            await itx.response.send_message(embed=element, view=v, ephemeral=True)
        else:
            await itx.response.edit_message(embed=element, view=v)

    @classmethod
    async def raw_submit(cls, interaction: discord.Interaction[Any], conn: apsw.Connection, data: str) -> None:
        action, user_id, idx, tid = b2048unpack(data, tuple[str, int, int, str])
        if interaction.user.id != user_id:
            return
        if action == "delete":
            sched: DiscordBotScheduler = interaction.client.sched
            await sched.unschedule_uuid(tid)
        await cls.edit_to_current_index(interaction, user_id, idx)


_user_tz_lru: LRU[int, str] = LRU(128)


@reminder_group.command(name="in", description="remind in an amount of time")
async def remind_in(itx: discord.Interaction[Any]) -> None: ...


@reminder_group.command(name="at", description="remind at a specific time (uses your configured timezone)")
async def remind_at(itx: discord.Interaction[Any]) -> None: ...


@reminder_group.command(name="list", description="view and optionally remove your reminders.")
async def reminder_list(itx: discord.Interaction[Any]) -> None: ...


exports = BotExports([reminder_group], raw_button_submits={"rmndrlst": ReminderView})
