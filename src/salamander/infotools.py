"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import io

import discord

from ._type_stuff import BotExports
from .bot import Interaction


def embed_from_user(member: discord.User | discord.Member) -> discord.Embed:
    em = discord.Embed()
    em.set_footer(text=f"Discord ID: {member.id}")
    avatar = member.display_avatar.with_static_format("png")
    em.set_author(name=str(member))
    em.set_image(url=avatar.url)
    return em


@discord.app_commands.context_menu(name="Avatar")
async def user_avatar(itx: Interaction, user: discord.User | discord.Member) -> None:
    await itx.response.send_message(embed=embed_from_user(user), ephemeral=True)


@discord.app_commands.context_menu(name="Raw Content")
async def raw_content(itx: Interaction, message: discord.Message) -> None:
    send = itx.response.send_message
    c = message.content
    if not c:
        await send("No content", ephemeral=True)
        return

    if len(c) < 1000:
        escaped = discord.utils.escape_markdown(c)
        if len(escaped) < 1500:
            embed = discord.Embed(description=f"```\n{escaped}\n```")
            await send(embed=embed, ephemeral=True)
            return

    f = discord.File(io.BytesIO(c.encode()))
    await send(content="Attached long raw content", ephemeral=True, file=f)


exports = BotExports([user_avatar, raw_content])
