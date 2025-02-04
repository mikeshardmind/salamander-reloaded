"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import apsw
import discord
import pytz
from async_utils.corofunc_cache import lrucorocache
from async_utils.lru import LRU

from ._ac import cf_ac_cache_transform_no_user
from ._type_stuff import BotExports
from .bot import Interaction

settings_group = discord.app_commands.Group(
    name="settings",
    description="configure settings here",
)


_user_tz_lru: LRU[int, str] = LRU(128)


async def get_user_tz(conn: apsw.Connection, user_id: int) -> str:
    user_tz = _user_tz_lru.get(user_id, None)
    if user_tz is not None:
        return user_tz

    row = conn.execute(
        """
        INSERT INTO discord_users (user_id)
        VALUES (?)
        ON CONFLICT (user_id)
        DO UPDATE SET user_tz=user_tz
        RETURNING user_tz
        """,
        (user_id,),
    ).fetchone()
    assert row is not None, "Upsert + returning guaranteed to return a row"
    return row[0]


@settings_group.command(name="timezone", description="Set your timezone")
async def tz_set(itx: Interaction, zone: discord.app_commands.Range[str, 1, 70]) -> None:
    send = itx.response.send_message
    if zone == "local":
        await send("Invalid timezone: %s" % zone, ephemeral=True)
        return
    try:
        pytz.timezone(zone)
    except pytz.UnknownTimeZoneError:
        await send("Invalid timezone: %s" % zone, ephemeral=True)
    else:
        await itx.response.defer(ephemeral=True)
        with itx.client.conn:
            itx.client.conn.execute(
                """
                INSERT INTO discord_users (user_id, user_tz) VALUES(?, ?)
                ON CONFLICT (user_id) DO UPDATE SET user_tz=excluded.user_tz
                """,
                (itx.user.id, zone),
            ).get()
        _user_tz_lru[itx.user.id] = zone
        await itx.edit_original_response(content="Timezone set to %s" % zone)


@tz_set.autocomplete("zone")
@lrucorocache(ttl=None, maxsize=1024, cache_transform=cf_ac_cache_transform_no_user)
async def zone_ac(itx: Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
    common_zones = pytz.common_timezones_set
    c_insensitive = current.casefold()
    zone_matches = {z for z in common_zones if z.casefold().startswith(c_insensitive)}
    closest_zones = sorted(zone_matches)[:25]
    return [discord.app_commands.Choice(name=x, value=x) for x in closest_zones]


exports = BotExports(commands=[settings_group])
