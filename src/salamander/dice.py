"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from discord.app_commands import Group, Range

from ._type_stuff import BotExports
from .bot import Interaction
from .dicemath import DiceError, Expression

dice_group = Group(name="dice", description="Keep rolling")

type Expr = Range[str, 0, 500]


@dice_group.command(name="roll")
async def roll(itx: Interaction, expression: Expr, secret: bool = False) -> None:
    """Roll some dice"""
    send = itx.response.send_message
    try:
        ex = Expression.from_str(expression)
        msg = ex.verbose_roll2()
    except ZeroDivisionError:
        await send("Oops, too many dice. I dropped them", ephemeral=True)
    except DiceError as err:
        await send(f"{err}", ephemeral=True)
    else:
        msg = f"\N{GAME DIE}\n```\n{msg}\n```"
        await send(msg, ephemeral=secret)


@dice_group.command(name="info")
async def rverb(itx: Interaction, expression: Expr, secret: bool = False) -> None:
    """
    Get info about an expression
    """
    send = itx.response.send_message
    try:
        ex = Expression.from_str(expression)
        low, high, ev = ex.get_min(), ex.get_max(), ex.get_ev()
    except ZeroDivisionError:
        return await send("Oops, too many dice. I dropped them", ephemeral=True)
    except DiceError as err:
        return await send(f"{err}", ephemeral=True)

    return await send(
        f"Information about dice Expression: "
        f"{ex}:\nLow: {low}\nHigh: {high}\nEV: {ev:.7g}",
        ephemeral=secret,
    )


exports = BotExports([dice_group])
