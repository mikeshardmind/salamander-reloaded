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


def embed_from_user(member: discord.User | discord.Member) -> discord.Embed:
    em = discord.Embed()
    em.set_footer(text=f"Discord ID: {member.id}")
    avatar = member.display_avatar.with_static_format("png")
    em.set_author(name=str(member))
    em.set_image(url=avatar.url)
    return em


@discord.app_commands.context_menu(name="Avatar")
async def user_avatar(itx: discord.Interaction, user: discord.User | discord.Member) -> None:
    await itx.response.send_message(embed=embed_from_user(user), ephemeral=True)


@discord.app_commands.context_menu(name="Raw Content")
async def raw_content(itx: discord.Interaction, message: discord.Message) -> None:
    c = message.content
    if not c:
        await itx.response.send_message("No content", ephemeral=True)
        return

    if len(c) < 1000:
        escaped = discord.utils.escape_markdown(c)
        if len(escaped) < 1500:
            embed = discord.Embed(description=f"```\n{escaped}\n```")
            await itx.response.send_message(embed=embed, ephemeral=True)
            return

    b = io.BytesIO(c.encode())
    await itx.response.send_message(content="Attached long raw content", ephemeral=True, file=discord.File(b))


exports = BotExports([user_avatar, raw_content])
