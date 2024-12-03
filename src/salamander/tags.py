"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from itertools import chain

import discord
from apsw import Connection
from async_utils.lru import LRU
from base2048 import decode
from discord.app_commands import Choice, Group, Range
from msgspec import msgpack

from ._type_stuff import BotExports
from .bot import Interaction
from .utils import b2048pack

tag_group = Group(name="tag", description="Store and recall content")


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
    ):
        disc_safe = b2048pack((author_id, tag_name))
        custom_id = f"m:tag:{disc_safe}"
        super().__init__(title=title, timeout=10, custom_id=custom_id)

    @staticmethod
    async def raw_submit(interaction: Interaction, data: str) -> None:
        cursor = interaction.client.conn.cursor()
        packed = decode(data)
        author_id, tag_name = msgpack.decode(packed, type=tuple[int, str])

        assert interaction.data, "Checked by caller"

        raw_ = interaction.data.get("components", None)
        if not raw_:
            return
        comp = raw_[0]
        modal_components = comp.get("components")
        if not modal_components:
            return
        content = modal_components[0]["value"]

        await interaction.response.defer(ephemeral=True)
        cursor.execute(
            """
            INSERT INTO user_tags (user_id, tag_name, content)
            VALUES (:author_id, :tag_name, :content)
            ON CONFLICT (user_id, tag_name)
            DO UPDATE SET content=excluded.content;
            """,
            {"author_id": author_id, "tag_name": tag_name, "content": content},
        )
        await interaction.followup.send(content="Tag saved", ephemeral=True)


@tag_group.command(name="create")
async def user_tag_create(itx: Interaction, name: Range[str, 1, 20]) -> None:
    """Creates or replaces tag content"""
    modal = TagModal(tag_name=name, author_id=itx.user.id)
    await itx.response.send_modal(modal)


@tag_group.command(name="get")
async def user_tag_get(itx: Interaction, name: Range[str, 1, 20]) -> None:
    """Get some content"""
    cursor = itx.client.conn.cursor()
    row = cursor.execute(
        """
        SELECT content FROM user_tags
        WHERE user_id = ? AND tag_name = ? LIMIT 1;
        """,
        (itx.user.id, name),
    ).fetchone()

    if row is None:
        await itx.response.send_message(content="No such tag.", ephemeral=True)
    else:
        (content,) = row
        await itx.response.send_message(content)


@tag_group.command(name="delete")
async def user_tag_del(itx: Interaction, name: Range[str, 1, 20]) -> None:
    """Delete a tag."""
    await itx.response.defer(ephemeral=True)
    conn: Connection = itx.client.conn
    cursor = conn.cursor()
    row = cursor.execute(
        """
        DELETE FROM user_tags
        WHERE user_id = ? AND tag_name = ?
        RETURNING tag_name
        """,
        (itx.user.id, name),
    ).fetchall()
    msg = "Tag Deleted" if row else "No such tag"
    await itx.followup.send(msg, ephemeral=True)


_cache: LRU[tuple[int, str], list[Choice[str]]] = LRU(1024)


@user_tag_del.autocomplete("name")
@user_tag_get.autocomplete("name")
async def tag_ac(itx: Interaction, current: str) -> list[Choice[str]]:
    # TODO: smarter trie based cache? is it worth it?
    key = (itx.user.id, current)
    val = _cache.get(key, None)

    if val is not None:
        return val

    cursor = itx.client.conn.cursor()
    it = chain.from_iterable(
        cursor.execute(
            """
        SELECT tag_name
        FROM user_tags
        WHERE user_id = ? AND tag_name LIKE ? || '%' LIMIT 25
        """,
            key,
        )
    )
    _cache[key] = r = [Choice(name=c, value=c) for c in it]
    return r


exports = BotExports([tag_group], {"tag": TagModal})
