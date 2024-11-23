"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from functools import lru_cache

import arrow
import discord
import pytz
from async_utils.task_cache import taskcache
from discord import app_commands
from discord.app_commands import Choice, Group
from scheduler import DiscordBotScheduler, ScheduledDispatch

from ._type_stuff import BotExports, DynButton, Reminder
from .bot import Interaction
from .settings_commands import get_user_tz
from .utils import b2048pack, b2048unpack

reminder_group = Group(
    name="remindme", description="remind yourself about something, later"
)


TRASH_EMOJI = "\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"

MIN_YEAR = (arrow.Arrow.now(pytz.UTC) - timedelta(days=2)).datetime.year
MAX_YEAR = MIN_YEAR + 3

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
        embed = discord.Embed(
            description=reminder.content, timestamp=ts.datetime
        )

        first_disabled = index == 0
        last_disabled = index == ln - 1
        prev_next_disabled = ln == 1

        return (
            embed,
            first_disabled,
            last_disabled,
            prev_next_disabled,
            item.task_id,
        )

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
        edit = (
            itx.edit_original_response
            if use_followup
            else itx.response.edit_message
        )

        if not _l:
            if first:
                await send("You have no reminders set", ephemeral=True)
            else:
                await edit(
                    content="You no longer have any reminders set",
                    view=None,
                    embed=None,
                )
            return

        element, first_disabled, last_disabled, prev_next_disabled, tid = (
            cls.index_setup(_l, index)
        )
        v = discord.ui.View(timeout=4)

        c_id = "b:rmndrlst:" + b2048pack(("first", user_id, 0, tid))
        v.add_item(
            DynButton(label="<<", custom_id=c_id, disabled=first_disabled)
        )
        c_id = "b:rmndrlst:" + b2048pack(("previous", user_id, index - 1, tid))
        v.add_item(
            DynButton(label="<", custom_id=c_id, disabled=prev_next_disabled)
        )
        c_id = "b:rmndrlst:" + b2048pack(("delete", user_id, index, tid))
        v.add_item(
            DynButton(
                emoji=TRASH_EMOJI, style=discord.ButtonStyle.red, custom_id=c_id
            )
        )
        c_id = "b:rmndrlst:" + b2048pack(("next", user_id, index + 1, tid))
        v.add_item(
            DynButton(label=">", custom_id=c_id, disabled=prev_next_disabled)
        )
        c_id = "b:rmndrlst:" + b2048pack(("last", user_id, len(_l) - 1, tid))
        v.add_item(
            DynButton(label=">>", custom_id=c_id, disabled=last_disabled)
        )

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
        await cls.edit_to_current_index(
            interaction, user_id, idx, use_followup=True
        )


@reminder_group.command(name="in", description="remind in an amount of time")
async def remind_in(
    itx: Interaction,
    days: app_commands.Range[int, 0, 365] = 0,
    hours: app_commands.Range[int, 0, 72] = 0,
    minutes: app_commands.Range[int, 0, 59] = 0,
    content: app_commands.Range[str, 1, 1000] = "",
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
    context = (
        f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    )

    reminder = Reminder(content=content, context=context, recur=None)
    await sched.schedule_event(
        dispatch_name="reminder",
        dispatch_zone=raw_tz,
        user_id=itx.user.id,
        dispatch_extra=reminder,
        dispatch_time=ts,
    )

    formatted_ts = discord.utils.format_dt(when, style="f")
    await itx.followup.send(
        f"Reminder scheduled for {formatted_ts}", ephemeral=True
    )


def parse_hour(hour: str) -> int | None:
    hour = hour.replace(" ", "")

    inthour = -1

    if hour.endswith("m"):
        hour, suffix = hour[:-2], hour[-2:]
        if suffix.casefold() not in {"am", "pm"}:
            return None
        if len(hour) > 2:
            return None
        try:
            inthour = int(hour)
        except ValueError:
            return None
        if suffix == "am" and inthour == 12:
            inthour = 0
        elif suffix == "pm" and inthour != 12:
            inthour += 12
    else:
        try:
            inthour = int(hour)
        except ValueError:
            return None

    if 0 <= inthour <= 23:
        return inthour

    return None


@reminder_group.command(name="at")
async def remind_at(
    itx: Interaction,
    year: app_commands.Range[int, MIN_YEAR, MAX_YEAR] = -1,
    month: app_commands.Range[int, 1, 12] = -1,
    day: app_commands.Range[int, 1, 31] = -1,
    hour: app_commands.Range[str, 0, 5] = "",
    minute: app_commands.Range[int, 0, 59] = -1,
    content: app_commands.Range[str, 1, 1000] = "",
) -> None:
    """Remind at a specific time. Any unit of time not provided with use the current time.

    Parameters
    ----------
    year: int
        Defaults to the current year.
    month: int
        The month to remind at. 1 = January 2 = February ... 12 = December.
        Defaults to the current month
    day: int
        Defaults to the current day.
    hour: str
        Allows 24 hour time or 12 hour with "am" and "pm". 0 = 12am
        Defaults to the current hour.
    minute: int
        The minute to remind at. Defaults to the current minute.
    content: str
        Optional text to include alongside the reminder link.
    """

    inthour = parse_hour(hour)
    if inthour is None:
        await itx.response.send_message("Not a valid hour")
        return

    replacements = {
        "year": year,
        "month": month,
        "day": day,
        "hour": inthour,
        "minute": minute,
    }

    replacements = {k: v for k, v in replacements.items() if v >= 0}

    raw_tz = get_user_tz(itx.client.conn, itx.user.id)
    user_tz = pytz.timezone(raw_tz)
    now = arrow.now(user_tz)
    try:
        when = now.replace(**replacements)
    except ValueError:
        await itx.response.send_message(
            "That isn't a valid calendar date", ephemeral=True
        )
        return
    if when < now:
        await itx.response.send_message(
            "That date is in the past!", ephemeral=True
        )
        return

    # make a fake jump url here
    guild_id = itx.guild_id or "@me"
    channel_id = itx.channel_id
    message_id = discord.utils.time_snowflake(now.datetime)
    context = (
        f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    )

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


@reminder_group.command(
    name="list", description="view and optionally remove your reminders."
)
async def reminder_list(itx: Interaction) -> None:
    await ReminderView.start(itx, itx.user.id)


@lru_cache(64)
def en_hour_to_str(hour: int) -> str:
    if hour == 0:
        return "12am"
    if hour == 12:
        return "12pm"

    if hour > 12:
        return f"{hour - 12}pm"

    return f"{hour}am"


@taskcache(60)
async def _autocomplete_minute(current: str, tzstr: str) -> list[Choice[int]]:
    common_min = [0, 15, 20, 30, 40, 45]
    if not current:
        tz = pytz.timezone(tzstr)
        m = arrow.Arrow.now(tz).datetime.minute

        if m not in common_min:
            c = app_commands.Choice(name=str(m), value=m)
            return [
                c,
                *(
                    app_commands.Choice(name=str(m), value=m)
                    for m in common_min
                ),
            ]

    else:
        minutes_str = list(map(str, range(60)))
        if current in minutes_str:
            return [app_commands.Choice(name=current, value=int(current))]

    return [app_commands.Choice(name=str(m), value=m) for m in common_min]


@remind_at.autocomplete("minute")
async def autocomplete_minute(
    itx: Interaction, current: str
) -> list[Choice[int]]:
    tzstr = get_user_tz(itx.client.conn, itx.user.id)
    return await _autocomplete_minute(current, tzstr)


@taskcache(60)
async def _autocomplete_hour(current: str, tzstr: str) -> list[Choice[str]]:
    hours_int = range(24)
    hours = deque(en_hour_to_str(hour) for hour in range(24))
    if not current:
        tz = pytz.timezone(tzstr)
        now = arrow.Arrow.now(tz)
        hour = en_hour_to_str(now.datetime.hour)
        while hour != hours[0]:
            hours.rotate()

        return [app_commands.Choice(name=c, value=c) for c in hours]

    if current in hours:
        return [app_commands.Choice(name=current, value=current)]

    if current in hours_int:
        choices = (current, f"{current}am", f"{current}pm")
        return [app_commands.Choice(name=c, value=c) for c in choices]
    if parse_hour(current) is not None:
        return [app_commands.Choice(name=current, value=current)]

    return []


@remind_at.autocomplete("hour")
async def autocomplete_hour(
    itx: Interaction, current: str
) -> list[Choice[str]]:
    tzstr = get_user_tz(itx.client.conn, itx.user.id)
    return await _autocomplete_hour(current, tzstr)


@taskcache(300)
async def _autocomplete_day(
    current: str, tzstr: str, year: int | None, month: int | None
) -> list[Choice[int]]:
    # fmt: off
    days_str = (
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
        "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23",
        "24", "25", "26", "27", "28", "29", "30", "31"
    )
    # fmt: on
    if current in days_str:
        if not year or month:
            return [Choice(name=current, value=int(current))]

        now = arrow.Arrow.now(pytz.timezone(tzstr))
        kwargs = {k: v for k, v in (("year", year), ("month", month)) if v}
        when = now.replace(**kwargs) if kwargs else now

        if (when.datetime.year, when.datetime.month) > (
            now.datetime.year,
            now.datetime.month,
        ):
            start = when.replace(day=1)
            end = start.shift(months=1)
            span = arrow.Arrow.span_range(
                "day", start.datetime, end.datetime, exact=True
            )
            days = {str(s[0].datetime.day) for s in span}
        else:
            start = now
            end = start.shift(months=1).replace(day=1)
            span = arrow.Arrow.span_range(
                "day", start.datetime, end.datetime, exact=True
            )
            days = {str(s[0].datetime.day) for s in span}

        if current in days:
            return [Choice(name=current, value=int(current))]

    if not current:
        now = arrow.Arrow.now(pytz.timezone(tzstr))
        kwargs = {k: v for k, v in (("year", year), ("month", month)) if v}
        when = now.replace(**kwargs) if kwargs else now

        if (when.datetime.year, when.datetime.month) > (
            now.datetime.year,
            now.datetime.month,
        ):
            start = when.replace(day=1)
            end = start.shift(months=1)
        else:
            start = now
            end = start.shift(months=1).replace(day=1)

        span = arrow.Arrow.span_range(
            "day", start.datetime, end.datetime, exact=True
        )
        days = [*dict.fromkeys(s[0].datetime.day for s in span)][:10]
        return [Choice(name=str(day), value=day) for day in days]

    return []


@remind_at.autocomplete("day")
async def autocomplete_day(itx: Interaction, current: str) -> list[Choice[int]]:
    tzstr = get_user_tz(itx.client.conn, itx.user.id)
    year = itx.namespace.__dict__.get("year", None)
    month = itx.namespace.__dict__.get("month", None)
    return await _autocomplete_day(current, tzstr, year, month)


@remind_at.autocomplete("month")
async def autocomplete_month(
    itx: Interaction, current: str
) -> list[Choice[int]]:
    months = deque(range(1, 13))
    tzstr = get_user_tz(itx.client.conn, itx.user.id)
    now = arrow.Arrow.now(pytz.timezone(tzstr))
    starting_month = now.datetime.month
    try:
        year = itx.namespace["year"]
    except KeyError:
        pass
    else:
        if year > now.datetime.year:
            starting_month = 1

    if not current:
        months.rotate(1 - starting_month)
        return [Choice(name=f"{m}", value=m) for m in months]
    if current in map(str, months):
        return [Choice(name=current, value=int(current))]
    return []


@remind_at.autocomplete("year")
async def autocomplete_year(
    itx: Interaction, current: str
) -> list[Choice[int]]:
    if not current:
        return [
            Choice(name=str(y), value=y) for y in range(MIN_YEAR, MAX_YEAR + 1)
        ]
    if len(current) != 4:
        return []
    str_years = [str(y) for y in range(MIN_YEAR, MAX_YEAR + 1)]
    if current in str_years:
        return [Choice(name=current, value=int(current))]
    return []


exports = BotExports(
    [reminder_group], raw_button_submits={"rmndrlst": ReminderView}
)
