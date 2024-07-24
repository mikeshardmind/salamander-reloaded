"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from itertools import chain
from typing import Any

import apsw
import discord
from discord import app_commands

tag_group = app_commands.Group(name="tag", description="Store and recall content")


class TagModal(discord.ui.Modal):
    tag: discord.ui.TextInput[TagModal] = discord.ui.TextInput(
        label="Tag",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=1000,
    )

    def __init__(
        self,
        *,
        title: str = "Add tag",
        timeout: float | None = 300,
        custom_id: str = "",
        tag_name: str,
        author_id: int,
    ) -> None:
        super().__init__(title=title, timeout=timeout)
        self.author_id = author_id
        self.tag_name: str = tag_name

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        conn: apsw.Connection = interaction.client.conn
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO discord_users (user_id, last_interaction)
                VALUES (:author_id, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET last_interaction=excluded.last_interaction;

                INSERT INTO user_tags (user_id, tag_name, content)
                VALUES (:author_id, :tag_name, :content)
                ON CONFLICT (user_id, tag_name)
                DO UPDATE SET content=excluded.content;
                """,
                {"author_id": self.author_id, "tag_name": self.tag_name, "content": self.tag.value},
            )
        await interaction.response.send_message("Tag saved", ephemeral=True)


@tag_group.command(name="create")
async def user_tag_create(itx: discord.Interaction, name: discord.app_commands.Range[str, 1, 20]) -> None:
    """Creates or replaces tag content"""
    await itx.response.send_modal(TagModal(tag_name=name, author_id=itx.user.id))


@tag_group.command(name="get")
async def user_tag_get(itx: discord.Interaction[Any], name: discord.app_commands.Range[str, 1, 20]) -> None:
    """Get some content"""
    cursor: apsw.Cursor = itx.client.conn.cursor()
    row = cursor.execute(
        """
        SELECT content FROM user_tags WHERE user_id = ? AND tag_name = ? LIMIT 1;
        """,
        (itx.user.id, name),
    ).fetchone()

    if row is None:
        await itx.response.send_message(content="No such tag.", ephemeral=True)
    else:
        (content,) = row
        await itx.response.send_message(content)


@user_tag_get.autocomplete("name")
async def tag_autocomplete(
    itx: discord.Interaction[Any],
    current: str,
) -> list[app_commands.Choice[str]]:
    cursor: apsw.Cursor = itx.client.conn.cursor()
    row = cursor.execute(
        """
        SELECT tag_name FROM user_tags WHERE user_id = ? AND tag_name LIKE ? || '%' LIMIT 25
        """,
        (itx.user.id, current),
    )
    return [app_commands.Choice(name=c, value=c) for c in chain.from_iterable(row)]
