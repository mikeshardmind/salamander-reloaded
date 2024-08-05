"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from typing import Any

import discord
import pytz

from .utils import LRU

settings_group = discord.app_commands.Group(name="settings", description="configure settings here")


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
        conn = itx.client.conn
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO discord_users (user_id, user_tz) VALUES(?, ?)
            ON CONFLICT (user_id) DO UPDATE SET user_tz=excluded.user_tz
            """,
            (itx.user.id, zone),
        )
        await itx.response.send_message("Timezone set to %s" % zone, ephemeral=True)


_close_zone_cache: LRU[str, list[str]] = LRU(512)


# TODO: consider a trie
def closest_zones(current: str) -> list[str]:
    closest = _close_zone_cache.get(current, None)
    if closest is not None:
        return closest

    common_zones = pytz.common_timezones_set

    zone_matches = {z for z in common_zones if z.startswith(current)}
    if len(zone_matches) > 25:
        return [*sorted(zone_matches)][:25]
    return list(zone_matches)


@tz_set.autocomplete("zone")
async def zone_ac(itx: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
    return [discord.app_commands.Choice(name=x, value=x) for x in closest_zones(current)]
