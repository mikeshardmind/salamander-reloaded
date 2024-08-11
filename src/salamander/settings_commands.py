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
import pytz

from ._type_stuff import BotExports
from .utils import LRU

settings_group = discord.app_commands.Group(name="settings", description="configure settings here")


_user_tz_lru: LRU[int, str] = LRU(128)


def get_user_tz(conn: apsw.Connection, user_id: int) -> str:
    _tz = _user_tz_lru.get(user_id, None)
    if _tz is not None:
        return _tz

    cursor = conn.cursor()
    # the update here is required for this to return
    # even when it already exists, but this is "free" still.
    row = cursor.execute(
        """
        INSERT INTO discord_users (user_id)
        VALUES (?)
        ON CONFLICT (user_id)
        DO UPDATE SET user_tz=excluded.user_tz
        RETURNING user_tz
        """,
        (user_id,),
    ).fetchone()
    assert row is not None
    return row[0]


@settings_group.command(name="timezone", description="Set your timezone for time related functions")
async def tz_set(itx: discord.Interaction[Any], zone: discord.app_commands.Range[str, 1, 70]) -> None:
    if zone == "local":
        await itx.response.send_message("Invalid timezone: %s" % zone, ephemeral=True)
        return
    try:
        pytz.timezone(zone)
    except pytz.UnknownTimeZoneError:
        await itx.response.send_message("Invalid timezone: %s" % zone, ephemeral=True)
    else:
        conn: apsw.Connection = itx.client.conn
        cursor = conn.cursor()
        await itx.response.defer(ephemeral=True)
        cursor.execute(
            """
            INSERT INTO discord_users (user_id, user_tz) VALUES(?, ?)
            ON CONFLICT (user_id) DO UPDATE SET user_tz=excluded.user_tz
            """,
            (itx.user.id, zone),
        )
        _user_tz_lru[itx.user.id] = zone
        await itx.followup.send("Timezone set to %s" % zone, ephemeral=True)


_close_zone_cache: LRU[str, list[str]] = LRU(512)


# TODO: consider a trie
def closest_zones(current: str) -> list[str]:
    closest = _close_zone_cache.get(current, None)
    if closest is not None:
        return closest

    common_zones = pytz.common_timezones_set

    zone_matches = {z for z in common_zones if z.casefold().startswith(current.casefold())}
    if len(zone_matches) > 25:
        return [*sorted(zone_matches)][:25]
    return list(zone_matches)


@tz_set.autocomplete("zone")
async def zone_ac(itx: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
    return [discord.app_commands.Choice(name=x, value=x) for x in closest_zones(current)]


exports = BotExports(commands=[settings_group])
