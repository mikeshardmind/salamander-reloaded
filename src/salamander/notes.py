"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import apsw
import discord
import msgspec
from discord import app_commands

from .base2048 import decode, encode


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
    ) -> None:

        data = msgspec.msgpack.encode((author_id, target_id))
        disc_safe = encode(data)
        custom_id = f"m:note:{disc_safe}"
        super().__init__(title=title, timeout=10, custom_id=custom_id)

    @staticmethod
    async def raw_submit(interaction: discord.Interaction[Any], conn: apsw.Connection, data: str) -> None:

        packed = decode(data)
        author_id, target_id = msgspec.msgpack.decode(packed)
        assert interaction.data

        raw_ = interaction.data.get("components", None)
        if not raw_:
            return
        comp = raw_[0]
        modal_components = comp.get("components")
        if not modal_components:
            return
        content = modal_components[0]["value"]

        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO discord_users (user_id, last_interaction) VALUES (:author_id, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET last_interaction=excluded.last_interaction;

                INSERT INTO user_notes (author_id, target_id, content) VALUES (:author_id, :target_id, :content);
                """,
                {
                    "author_id": author_id,
                    "target_id": target_id,
                    "content": content,
                },
            )
        await interaction.response.send_message("Note saved", ephemeral=True)


class NotesView(discord.ui.View):
    def __init__(self, user_id: int, target_id: int, *, timeout: float = 180, conn: apsw.Connection):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.target_id = target_id
        self.conn = conn
        self.index: int = 0
        self.message: discord.Message | None = None
        self.last_followup: discord.Webhook | None = None
        self.listmenu: list[tuple[str, str]] = [
            *conn.execute(
                """
                SELECT content, created_at FROM user_notes
                WHERE author_id = ? AND target_id = ?
                ORDER BY created_at ASC
                """,
                (self.user_id, self.target_id),
            )
        ]

    def setup_by_current_index(self) -> discord.Embed:
        ln = len(self.listmenu)
        index = self.index % ln
        self.previous.disabled = self.jump_first.disabled = bool(index == 0)
        self.nxt.disabled = self.jump_last.disabled = bool(index == ln - 1)
        content, ts = self.listmenu[index]
        dt = datetime.fromisoformat(ts)
        return discord.Embed(description=content, timestamp=dt)

    async def close(self) -> None:
        if self.last_followup and self.message:
            await self.last_followup.delete_message(self.message.id)

    async def on_timeout(self) -> None:
        await self.close()

    async def start(self, itx: discord.Interaction[Any]) -> None:
        # TODO: type this to allow using followup here as well
        if not self.listmenu:
            await itx.response.defer(ephemeral=True)
            await itx.followup.send("You have no saved notes for this user.")
            return
        element = self.setup_by_current_index()
        await itx.response.defer(ephemeral=True)
        self.last_followup = itx.followup
        self.message = await itx.followup.send(embed=element, view=self, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.defer(ephemeral=True)
        return False

    async def edit_to_current_index(self, interaction: discord.Interaction) -> None:
        element = self.setup_by_current_index()
        await interaction.response.edit_message(embed=element, view=self)
        self.last_followup = interaction.followup

    @discord.ui.button(label="<<", style=discord.ButtonStyle.gray)
    async def jump_first(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.index = 0
        await self.edit_to_current_index(interaction)

    @discord.ui.button(label="<", style=discord.ButtonStyle.gray)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.index -= 1
        await self.edit_to_current_index(interaction)

    @discord.ui.button(emoji="\N{WASTEBASKET}\N{VARIATION SELECTOR-16}", style=discord.ButtonStyle.red)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await interaction.response.defer(ephemeral=True)
        self.last_followup = interaction.followup
        with self.conn:
            cursor = self.conn.cursor()
            current_ts = self.listmenu[self.index][1]
            cursor.execute(
                """
                DELETE FROM user_notes
                WHERE author_id = ? AND target_id = ? AND created_at = ?
                """,
                (self.user_id, self.target_id, current_ts),
            )
        await self.close()

    @discord.ui.button(label=">", style=discord.ButtonStyle.gray)
    async def nxt(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.index += 1
        await self.edit_to_current_index(interaction)

    @discord.ui.button(label=">>", style=discord.ButtonStyle.gray)
    async def jump_last(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        self.index = -1
        await self.edit_to_current_index(interaction)


@app_commands.context_menu(name="Add note")
async def add_note_ctx(itx: discord.Interaction[Any], user: discord.Member | discord.User) -> None:
    modal = NoteModal(target_id=user.id, author_id=itx.user.id)
    await itx.response.send_modal(modal)


@app_commands.context_menu(name="Get notes")
async def get_note_ctx(itx: discord.Interaction[Any], user: discord.Member | discord.User) -> None:
    menu = NotesView(itx.user.id, user.id, conn=itx.client.conn)
    await menu.start(itx)
