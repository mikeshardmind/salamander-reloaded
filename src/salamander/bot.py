"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from datetime import timedelta
from typing import Any, Self

import apsw
import discord
import msgspec
import scheduler
import xxhash

from ._type_stuff import HasExports, RawSubmittable, Reminder
from .utils import LRU, platformdir_stuff, resolve_path_with_links

log = logging.getLogger(__name__)


class VersionableTree(discord.app_commands.CommandTree["Salamander"]):
    async def interaction_check(self, interaction: discord.Interaction[Salamander]) -> bool:
        if interaction.client.is_blocked(interaction.user.id):
            if interaction.type is discord.InteractionType.application_command:
                # We're not allowed to defer without thinking and ghost them, thanks discord! /s
                await interaction.response.send_message("blocked, go away", ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True)
            return False
        return True

    async def get_hash(self, tree: discord.app_commands.CommandTree) -> bytes:
        commands = sorted(self._get_all_commands(guild=None), key=lambda c: c.qualified_name)

        translator = self.translator
        if translator:
            payload = [await command.get_translated_payload(tree, translator) for command in commands]
        else:
            payload = [command.to_dict(tree) for command in commands]

        return xxhash.xxh64_digest(msgspec.msgpack.encode(payload), seed=0)


modal_regex = re.compile(r"^m:(.{1,10}):(.*)$", flags=re.DOTALL)
button_regex = re.compile(r"^b:(.{1,10}):(.*)$", flags=re.DOTALL)

_missing: Any = object()


class Salamander(discord.AutoShardedClient):
    def __init__(
        self,
        *args: Any,
        intents: discord.Intents,
        conn: apsw.Connection,
        initial_exts: list[HasExports],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, intents=intents, **kwargs)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.raw_button_submits: dict[str, RawSubmittable] = {}
        self.tree = VersionableTree(
            self,
            fallback_to_global=False,
            allowed_contexts=discord.app_commands.AppCommandContext(dm_channel=True, guild=True, private_channel=True),
            allowed_installs=discord.app_commands.AppInstallationType(user=True, guild=False),
        )
        self.conn: apsw.Connection = conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self.sched: scheduler.DiscordBotScheduler = _missing
        self.initial_exts: list[HasExports] = initial_exts

    async def on_interaction(self, interaction: discord.Interaction[Self]) -> None:
        for typ, regex, mapping in (
            (discord.InteractionType.modal_submit, modal_regex, self.raw_modal_submits),
            (discord.InteractionType.component, button_regex, self.raw_button_submits),
        ):
            if interaction.type is typ:
                assert interaction.data is not None
                custom_id = interaction.data.get("custom_id", "")
                if match := regex.match(custom_id):
                    modal_name, data = match.groups()
                    if rs := mapping.get(modal_name):
                        await rs.raw_submit(interaction, self.conn, data)

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        self.block_cache[user_id] = blocked
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO discord_users (user_id, is_blocked)
                VALUES (?, ?)
                ON CONFLICT (user_id)
                DO UPDATE SET is_blocked=excluded.is_blocked
                """,
                (user_id, blocked),
            )

    def is_blocked(self, user_id: int) -> bool:
        blocked = self.block_cache.get(user_id, None)
        if blocked is not None:
            return blocked

        cursor = self.conn.cursor()

        row = cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM discord_users WHERE user_id=? AND is_blocked LIMIT 1
            );
            """,
            (user_id,),
        ).fetchone()
        assert row is not None, "SELECT EXISTS top level query is always going to have a result..."
        b: bool = row[0]
        self.block_cache[user_id] = b
        return b

    async def setup_hook(self) -> None:
        from datetime import timedelta

        t = discord.utils.utcnow() + timedelta(minutes=1)
        fmt = t.strftime(r"%Y-%m-%d %H:%M")
        await self.sched.schedule_event(dispatch_name="test", dispatch_time=fmt, dispatch_zone="UTC")
        self.sched.start_dispatch_to_bot(self)

        for mod in self.initial_exts:
            exports = mod.exports
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)
            if exports.raw_modal_submits:
                self.raw_modal_submits.update(exports.raw_modal_submits)
            if exports.raw_button_submits:
                self.raw_button_submits.update(exports.raw_button_submits)

        path = platformdir_stuff.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash(self.tree)
        with path.open(mode="r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)

    async def start(
        self,
        token: str,
        *,
        reconnect: bool = True,
        scheduler: scheduler.DiscordBotScheduler = _missing,
    ) -> None:
        if scheduler is _missing:
            msg = "Must provide a valid scheudler instance"
            raise RuntimeError(msg)
        self.sched = scheduler
        return await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        await self.sched.stop_gracefully()
        return await super().close()

    async def on_sinbad_scheduler_reminder(self, event: scheduler.ScheduledDispatch) -> None:
        user_id = event.associated_user
        reminder = event.unpack_extra(Reminder)
        if reminder and user_id:
            embed = discord.Embed(description=reminder.content, title="Your requested reminder")
            embed.add_field(name="Jump to around where you created this reminder", value=reminder.context)

            unrecoverable_fail = False
            try:
                channel = await self.create_dm(discord.Object(user_id, type=discord.User))
                await channel.send(embed=embed)
            except (discord.NotFound, discord.Forbidden):
                # assume user doesn't exist or removed the app
                unrecoverable_fail = True
            except discord.HTTPException as exc:
                logging.exception("Could not handle reminder %r due to exception", event, exc_info=exc)

            if reminder.recur and not unrecoverable_fail:
                delta = {
                    "Weekly": timedelta(weeks=1),
                    "Daily": timedelta(days=1),
                }[reminder.recur]

                time = event.get_arrow_time() + delta

                await self.sched.schedule_event(
                    dispatch_name=event.dispatch_name,
                    dispatch_time=time.strftime(r"%Y-%m-%d %H:%M"),
                    dispatch_zone=event.dispatch_zone,
                    guild_id=event.associated_guild,
                    user_id=user_id,
                    dispatch_extra=reminder,
                )
