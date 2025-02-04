"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

import apsw
import discord
import msgspec
from async_utils.lru import LRU
from base2048 import decode
from discord import app_commands

from ._type_stuff import BotExports, DynButton
from .bot import Interaction
from .utils import b2048pack

_user_notes_lru: LRU[tuple[int, int], tuple[str, str]] = LRU(128)

TRASH_EMOJI = "\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"


class NoteModal(discord.ui.Modal):
    note: discord.ui.TextInput[NoteModal] = discord.ui.TextInput(
        label="Note",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=1000,
    )

    def __init__(
        self,
        *,
        title: str = "Add note",
        timeout: float | None = None,
        custom_id: str = "",
        target_id: int,
        author_id: int,
    ):
        disc_safe = b2048pack((author_id, target_id))
        custom_id = f"m:note:{disc_safe}"
        super().__init__(title=title, timeout=10, custom_id=custom_id)

    @staticmethod
    async def raw_submit(interaction: Interaction, data: str) -> None:
        packed = decode(data)
        author_id, target_id = msgspec.msgpack.decode(packed, type=tuple[int, int])
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

        conn = interaction.client.conn

        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO user_notes (author_id, target_id, content)
                    VALUES (:author_id, :target_id, :content);
                    """,
                    {
                        "author_id": author_id,
                        "target_id": target_id,
                        "content": content,
                    },
                ).get()
        except apsw.ConstraintError:
            too_many = True
        else:
            too_many = False

        if not too_many:
            await interaction.edit_original_response(content="Note saved")
            _user_notes_lru.remove((author_id, target_id))
        else:
            msg = "You have 25 notes for this user already, enough!"
            await interaction.edit_original_response(content=msg)


async def get_user_notes(conn: apsw.Connection, author_id: int, user_id: int) -> tuple[str, ...]:
    if nl := _user_notes_lru.get((author_id, user_id), None):
        return nl

    notes = conn.execute(
        """
        SELECT content, created_at FROM user_notes
        WHERE author_id = ? AND target_id = ?
        ORDER BY created_at ASC
        """,
        (author_id, user_id),
    )

    _user_notes_lru[author_id, user_id] = r = tuple(notes)

    return r


class NotesView:
    @staticmethod
    def index_setup(
        items: tuple[str, ...], index: int
    ) -> tuple[discord.Embed, bool, bool, bool, str]:
        ln = len(items)
        index %= ln
        content, ts = items[index]
        dt = datetime.fromisoformat(ts).replace(tzinfo=UTC)
        first_disabled = index == 0
        last_disabled = index == ln - 1
        prev_next_disabled = ln == 1
        return (
            discord.Embed(description=content, timestamp=dt),
            first_disabled,
            last_disabled,
            prev_next_disabled,
            ts,
        )

    @classmethod
    async def start(
        cls,
        itx: Interaction,
        conn: apsw.Connection,
        user_id: int,
        target_id: int,
    ) -> None:
        await cls.edit_to_current_index(itx, conn, user_id, target_id, 0, first=True)

    @classmethod
    async def edit_to_current_index(
        cls,
        itx: Interaction,
        conn: apsw.Connection,
        user_id: int,
        target_id: int,
        index: int,
        *,
        first: bool = False,
        defer_used: bool = False,
    ) -> None:
        fetched = await get_user_notes(itx.client.read_conn, user_id, target_id)

        edit = itx.edit_original_response if defer_used else itx.response.edit_message
        send = edit if defer_used else partial(itx.response.send_message, ephemeral=True)

        if not fetched:
            if first:
                await send(content="You have no saved notes for this user.")
            else:
                await edit(
                    content="You no longer have any saved noted for this user.",
                    view=None,
                    embed=None,
                )
            return

        element, f_disabled, l_disabled, single, ts = cls.index_setup(fetched, index)

        v = discord.ui.View(timeout=4)

        c_id = "b:note:" + b2048pack(("first", user_id, target_id, 0, ts))
        v.add_item(DynButton(label="<<", custom_id=c_id, disabled=f_disabled))
        c_id = "b:note:" + b2048pack((
            "previous",
            user_id,
            target_id,
            index - 1,
            ts,
        ))
        v.add_item(DynButton(label="<", custom_id=c_id, disabled=single))
        c_id = "b:note:" + b2048pack(("delete", user_id, target_id, index, ts))
        v.add_item(DynButton(emoji=TRASH_EMOJI, style=discord.ButtonStyle.red, custom_id=c_id))
        c_id = "b:note:" + b2048pack((
            "next",
            user_id,
            target_id,
            index + 1,
            ts,
        ))
        v.add_item(DynButton(label=">", custom_id=c_id, disabled=single))
        c_id = "b:note:" + b2048pack((
            "last",
            user_id,
            target_id,
            len(fetched) - 1,
            ts,
        ))
        v.add_item(DynButton(label=">>", custom_id=c_id, disabled=l_disabled))

        method = send if first else edit
        await method(embed=element, view=v)

    @classmethod
    async def raw_submit(cls, interaction: Interaction, data: str) -> None:
        conn = interaction.client.conn
        action, user_id, target_id, idx, ts = msgspec.msgpack.decode(
            decode(data), type=tuple[str, int, int, int, str]
        )
        if interaction.user.id != user_id:
            return

        await interaction.response.defer(ephemeral=True)
        if action == "delete":
            _user_notes_lru.remove((user_id, target_id))
            with conn:
                conn.execute(
                    """
                    DELETE FROM user_notes
                    WHERE author_id = ? AND target_id = ? AND created_at = ?
                    """,
                    (user_id, target_id, ts),
                ).get()

        await cls.edit_to_current_index(interaction, conn, user_id, target_id, idx, defer_used=True)


@app_commands.context_menu(name="Add note")
async def add_note_ctx(itx: Interaction, user: discord.Member | discord.User) -> None:
    modal = NoteModal(target_id=user.id, author_id=itx.user.id)
    await itx.response.send_modal(modal)


@app_commands.context_menu(name="Get notes")
async def get_note_ctx(itx: Interaction, user: discord.Member | discord.User) -> None:
    menu = NotesView()
    await menu.start(itx, itx.client.conn, itx.user.id, user.id)


exports = BotExports(
    commands=[add_note_ctx, get_note_ctx],
    raw_modal_submits={"note": NoteModal},
    raw_button_submits={"note": NotesView},
)
