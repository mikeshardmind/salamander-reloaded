"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import discord
from discord import app_commands

from ._type_stuff import BotExports
from .bot import Salamander
from .dicemath import DiceError, Expression

dice_group = app_commands.Group(name="dice", description="Keep rolling")


@dice_group.command(name="roll")
async def roll(
    itx: discord.Interaction[Salamander],
    expression: app_commands.Range[str, 0, 500],
    secret: bool = False,
) -> None:
    """Roll some dice"""

    try:
        ex = Expression.from_str(expression)
        msg = ex.verbose_roll2()
    except ZeroDivisionError:
        await itx.response.send_message("Oops, too many dice. I dropped them", ephemeral=True)
    except DiceError as err:
        await itx.response.send_message(f"{err}", ephemeral=True)
    else:
        msg = f"\N{GAME DIE}\n```\n{msg}\n```"
        await itx.response.send_message(msg, ephemeral=secret)


@dice_group.command(name="info")
async def rverb(
    itx: discord.Interaction[Salamander],
    expression: app_commands.Range[str, 0, 500],
    secret: bool = False,
) -> None:
    """
    Get info about an expression
    """

    try:
        ex = Expression.from_str(expression)
        low, high, ev = ex.get_min(), ex.get_max(), ex.get_ev()
    except ZeroDivisionError:
        return await itx.response.send_message("Oops, too many dice. I dropped them", ephemeral=True)
    except DiceError as err:
        return await itx.response.send_message(f"{err}", ephemeral=True)

    return await itx.response.send_message(
        f"Information about dice Expression: {ex}:\nLow: {low}\nHigh: {high}\nEV: {ev:.7g}",
        ephemeral=secret,
    )


exports = BotExports([dice_group])
