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
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Self, override

import discord
import msgspec
import scheduler
import xxhash
from async_utils.lru import LRU
from async_utils.priority_sem import PrioritySemaphore, priority_context
from async_utils.task_cache import taskcache
from async_utils.waterfall import Waterfall
from discord import InteractionType, app_commands

from ._type_stuff import HasExports, RawSubmittable, Reminder
from .db import ConnWrap
from .utils import platformdir_stuff, resolve_path_with_links

log = logging.getLogger(__name__)


type Interaction = discord.Interaction[Salamander]


class VersionableTree(app_commands.CommandTree["Salamander"]):
    @classmethod
    def from_salamander(cls: type[Self], client: Salamander) -> Self:
        installs = app_commands.AppInstallationType(user=True, guild=False)

        cx = app_commands.AppCommandContext
        contexts = cx(dm_channel=True, guild=True, private_channel=True)
        return cls(
            client,
            fallback_to_global=False,
            allowed_contexts=contexts,
            allowed_installs=installs,
        )

    @override
    async def interaction_check(self, interaction: Interaction) -> bool:
        if await interaction.client.is_blocked(interaction.user.id):
            resp = interaction.response
            if interaction.type is InteractionType.application_command:
                await resp.send_message("blocked, go away", ephemeral=True)
            else:
                await resp.defer(ephemeral=True)
            return False
        return True

    async def get_hash(self) -> bytes:
        coms = sorted(self._get_all_commands(guild=None), key=lambda c: c.qualified_name)

        translator = self.translator
        if translator:
            payload = [await c.get_translated_payload(self, translator) for c in coms]
        else:
            payload = [c.to_dict(self) for c in coms]

        return xxhash.xxh64_digest(msgspec.msgpack.encode(payload), seed=0)


modal_regex = re.compile(r"^m:(.{1,10}):(.*)$", flags=re.DOTALL)
button_regex = re.compile(r"^b:(.{1,10}):(.*)$", flags=re.DOTALL)

_missing: Any = object()


class PreemptiveBlocked(Exception):
    pass


class Salamander(discord.AutoShardedClient):
    def __init__(
        self,
        *args: Any,
        intents: discord.Intents | None = None,
        conn: ConnWrap,
        initial_exts: list[HasExports],
        **kwargs: Any,
    ):
        intents = intents or discord.Intents.none()
        super().__init__(*args, intents=intents, **kwargs)
        self.raw_modal_submits: dict[str, RawSubmittable] = {}
        self.raw_button_submits: dict[str, RawSubmittable] = {}
        self.tree = VersionableTree.from_salamander(self)
        self.conn: ConnWrap = conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self.sched: scheduler.DiscordBotScheduler = _missing
        self.initial_exts: list[HasExports] = initial_exts
        self._is_closing: bool = False
        self._last_interact_waterfall = Waterfall(10, 100, self.update_last_seen)
        self._dm_sem = PrioritySemaphore(5)

    @taskcache(3600)
    async def cachefetch_priority_ids(self) -> set[int]:
        """Ensure DMs with these users are prioritized"""
        app_info = await self.application_info()
        owner = app_info.owner.id
        team = app_info.team
        if not team:
            return {owner}

        return {owner, *(t.id for t in team.members)}

    async def _send_embeds_dm(
        self,
        user_id: int,
        embeds: list[discord.Embed],
    ) -> discord.Message:
        priority = 1 if user_id in (await self.cachefetch_priority_ids()) else 5

        with priority_context(priority):
            async with self._dm_sem:
                if await self.is_blocked(user_id):
                    raise PreemptiveBlocked from None
                try:
                    dm = await self.create_dm(discord.Object(user_id, type=discord.User))
                    return await dm.send(embeds=embeds)

                # todo: implement a threshold system for other http exceptions
                except discord.NotFound:
                    # prevent deleted users from continuing to have stuff sent
                    await self.set_blocked(user_id, True)
                    raise

    async def update_last_seen(self, user_ids: Sequence[int], /) -> None:
        await self.conn.executemany(
            """
            INSERT INTO discord_users (user_id, last_interaction)
            VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET last_interaction=excluded.last_interaction;
            """,
            ((user_id,) for user_id in user_ids),
        )

    async def on_interaction(self, interaction: discord.Interaction[Self]) -> None:
        if not await self.is_blocked(interaction.user.id):
            self._last_interact_waterfall.put(interaction.user.id)
        for typ, regex, mapping in (
            (InteractionType.modal_submit, modal_regex, self.raw_modal_submits),
            (InteractionType.component, button_regex, self.raw_button_submits),
        ):
            if interaction.type is typ and interaction.data is not None:
                custom_id = interaction.data.get("custom_id", "")
                if match := regex.match(custom_id):
                    modal_name, data = match.groups()
                    if rs := mapping.get(modal_name):
                        await rs.raw_submit(interaction, data)

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        self.block_cache[user_id] = blocked
        await self.conn.execute(
            """
            INSERT INTO discord_users (user_id, is_blocked)
            VALUES (?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET is_blocked=excluded.is_blocked
            """,
            (user_id, blocked),
        )

    async def is_blocked(self, user_id: int) -> bool:
        blocked = self.block_cache.get(user_id, None)
        if blocked is not None:
            return blocked

        row = await self.conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM discord_users
                WHERE user_id=? AND is_blocked LIMIT 1
            );
            """,
            (user_id,),
        ).fetchone()
        assert row is not None, "SELECT EXISTS top level query"
        b: bool = row[0]
        self.block_cache[user_id] = b
        return b

    async def setup_hook(self) -> None:
        self.sched.start_dispatch_to_bot(self, redispatch_fetched_first=True)

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
        tree_hash = await self.tree.get_hash()
        log.info("Command tree hash digest: %s", tree_hash.hex())
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
        self._last_interact_waterfall.start()
        if scheduler is _missing:
            msg = "Must provide a valid scheudler instance"
            raise RuntimeError(msg)
        self.sched = scheduler
        return await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        self._is_closing = True
        await self.sched.stop_gracefully()
        await super().close()
        await self._last_interact_waterfall.stop()

    async def on_sinbad_scheduler_reminder(self, event: scheduler.ScheduledDispatch) -> None:
        if self._is_closing:
            return

        user_id = event.associated_user
        reminder = event.unpack_extra(Reminder)

        if not (reminder and user_id):
            await self.sched.task_done(event)
            return

        if reminder and user_id:
            embed = discord.Embed(description=reminder.content, title="Your requested reminder")
            jmp_label = "Jump to around where you created this reminder"
            embed.add_field(name=jmp_label, value=reminder.context)

            unrecoverable_fail = False

            try:
                # todo: batching of reminders by user
                await self._send_embeds_dm(user_id, embeds=[embed])
            except (discord.NotFound, discord.Forbidden, PreemptiveBlocked):
                unrecoverable_fail = True
            except discord.HTTPException as exc:
                logging.exception(
                    "Could not handle reminder %r due to exception",
                    event,
                    exc_info=exc,
                )

            await self.sched.task_done(event)

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
