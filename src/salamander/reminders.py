"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from datetime import datetime, timedelta

import arrow
import discord
import pytz
from scheduler import DiscordBotScheduler, ScheduledDispatch

from ._type_stuff import BotExports, DynButton, Reminder
from .bot import Interaction
from .settings_commands import get_user_tz
from .utils import b2048pack, b2048unpack

reminder_group = discord.app_commands.Group(
    name="remindme", description="remind yourself about something, later"
)


TRASH_EMOJI = "\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"

MIN_YEAR = (arrow.Arrow.now(pytz.UTC) - timedelta(days=2)).datetime.year
MAX_YEAR = MIN_YEAR + 2

DATE_FMT = r"%Y-%m-%d %H:%M"


class ReminderView:
    @staticmethod
    def index_setup(
        items: list[ScheduledDispatch], index: int
    ) -> tuple[discord.Embed, bool, bool, bool, str]:
        ln = len(items)
        index %= ln

        item = items[index]
        reminder = item.unpack_extra(Reminder)
        assert reminder
        ts = item.get_arrow_time()
        embed = discord.Embed(description=reminder.content, timestamp=ts.datetime)

        first_disabled = index == 0
        last_disabled = index == ln - 1
        prev_next_disabled = ln == 1

        return embed, first_disabled, last_disabled, prev_next_disabled, item.task_id

    @classmethod
    async def start(cls, itx: Interaction, user_id: int) -> None:
        await cls.edit_to_current_index(itx, user_id, 0, first=True)

    @classmethod
    async def edit_to_current_index(
        cls,
        itx: Interaction,
        user_id: int,
        index: int,
        first: bool = False,
        use_followup: bool = False,
    ) -> None:
        sched: DiscordBotScheduler = itx.client.sched
        _l = await sched.list_event_schedule_for_user("reminder", user_id)

        send = itx.followup.send if use_followup else itx.response.send_message
        edit = itx.edit_original_response if use_followup else itx.response.edit_message

        if not _l:
            if first:
                await send("You have no reminders set", ephemeral=True)
            else:
                await edit(
                    content="You no longer have any reminders set", view=None, embed=None
                )
            return

        element, first_disabled, last_disabled, prev_next_disabled, tid = cls.index_setup(
            _l, index
        )
        v = discord.ui.View(timeout=4)

        c_id = "b:rmndrlst:" + b2048pack(("first", user_id, 0, tid))
        v.add_item(DynButton(label="<<", custom_id=c_id, disabled=first_disabled))
        c_id = "b:rmndrlst:" + b2048pack(("previous", user_id, index - 1, tid))
        v.add_item(DynButton(label="<", custom_id=c_id, disabled=prev_next_disabled))
        c_id = "b:rmndrlst:" + b2048pack(("delete", user_id, index, tid))
        v.add_item(DynButton(emoji=TRASH_EMOJI, style=discord.ButtonStyle.red, custom_id=c_id))
        c_id = "b:rmndrlst:" + b2048pack(("next", user_id, index + 1, tid))
        v.add_item(DynButton(label=">", custom_id=c_id, disabled=prev_next_disabled))
        c_id = "b:rmndrlst:" + b2048pack(("last", user_id, len(_l) - 1, tid))
        v.add_item(DynButton(label=">>", custom_id=c_id, disabled=last_disabled))

        if first:
            await send(embed=element, view=v, ephemeral=True)
        else:
            await edit(embed=element, view=v)

    @classmethod
    async def raw_submit(cls, interaction: Interaction, data: str) -> None:
        action, user_id, idx, tid = b2048unpack(data, tuple[str, int, int, str])
        if interaction.user.id != user_id:
            return
        await interaction.response.defer(ephemeral=True)
        if action == "delete":
            sched: DiscordBotScheduler = interaction.client.sched
            await sched.unschedule_uuid(tid)
        await cls.edit_to_current_index(interaction, user_id, idx, use_followup=True)


@reminder_group.command(name="in", description="remind in an amount of time")
async def remind_in(
    itx: Interaction,
    days: discord.app_commands.Range[int, 0, 365] = 0,
    hours: discord.app_commands.Range[int, 0, 72] = 0,
    minutes: discord.app_commands.Range[int, 0, 59] = 0,
    content: discord.app_commands.Range[str, 1, 1000] = "",
) -> None:
    sched: DiscordBotScheduler = itx.client.sched
    await itx.response.defer(ephemeral=True)
    # strategy here is based on a mix of factors
    raw_tz = get_user_tz(itx.client.conn, itx.user.id)
    user_tz = pytz.timezone(raw_tz)
    now = datetime.now(user_tz)
    when = now + timedelta(days=days, hours=hours, minutes=minutes)
    if days:
        # we assume normalizing hours to match the clock for DST transitions here.
        # TODO: document reminder behavior
        when = user_tz.normalize(when)

    ts = DiscordBotScheduler.time_str_from_params(
        when.year, when.month, when.day, when.hour, when.minute
    )
    # make a fake jump url here
    guild_id = itx.guild_id or "@me"
    channel_id = itx.channel_id
    message_id = discord.utils.time_snowflake(now)
    context = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    reminder = Reminder(content=content, context=context, recur=None)
    await sched.schedule_event(
        dispatch_name="reminder",
        dispatch_zone=raw_tz,
        user_id=itx.user.id,
        dispatch_extra=reminder,
        dispatch_time=ts,
    )

    formatted_ts = discord.utils.format_dt(when, style="f")
    await itx.followup.send(f"Reminder scheduled for {formatted_ts}", ephemeral=True)


@reminder_group.command(name="at", description="remind at a specific time")
async def remind_at(
    itx: Interaction,
    year: discord.app_commands.Range[int, MIN_YEAR, MAX_YEAR] = -1,
    month: discord.app_commands.Range[int, 1, 12] = -1,
    day: discord.app_commands.Range[int, 1, 31] = -1,
    hour: discord.app_commands.Range[int, 0, 23] = -1,
    minute: discord.app_commands.Range[int, 0, 59] = -1,
    content: discord.app_commands.Range[str, 1, 1000] = "",
) -> None:
    replacements = {
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
    }

    replacements = {k: v for k, v in replacements.items() if v >= 0}

    raw_tz = get_user_tz(itx.client.conn, itx.user.id)
    user_tz = pytz.timezone(raw_tz)
    now = arrow.now(user_tz)
    try:
        when = now.replace(**replacements)
    except ValueError:
        await itx.response.send_message("That isn't a valid calendar date", ephemeral=True)
        return
    if when < now:
        await itx.response.send_message("That date is in the past!", ephemeral=True)
        return

    # make a fake jump url here
    guild_id = itx.guild_id or "@me"
    channel_id = itx.channel_id
    message_id = discord.utils.time_snowflake(now.datetime)
    context = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    reminder = Reminder(content=content, context=context, recur=None)

    await itx.client.sched.schedule_event(
        dispatch_name="reminder",
        dispatch_zone=raw_tz,
        user_id=itx.user.id,
        dispatch_extra=reminder,
        dispatch_time=when.strftime(DATE_FMT),
    )

    formatted_ts = discord.utils.format_dt(when.datetime, style="f")
    message = f"Reminder scheduled for {formatted_ts}"
    if raw_tz == "UTC":
        footer = (
            "-# This was scheduled using UTC, "
            "consider setting your timezone with /settings timezone"
        )
        message = "\n".join((message, footer))
    await itx.response.send_message(message, ephemeral=True)


@reminder_group.command(name="list", description="view and optionally remove your reminders.")
async def reminder_list(itx: Interaction) -> None:
    await ReminderView.start(itx, itx.user.id)


exports = BotExports([reminder_group], raw_button_submits={"rmndrlst": ReminderView})
