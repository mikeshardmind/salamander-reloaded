"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import apsw
import apsw.bestpractice
import discord
import msgspec
import scheduler
import xxhash

from . import base2048
from .dice import dice_group
from .infotools import raw_content, user_avatar
from .notes import add_note_ctx, get_note_ctx
from .tags import tag_group
from .utils import LRU, platformdir_stuff, resolve_path_with_links

log = logging.getLogger(__name__)


class Reminder(msgspec.Struct, gc=False, frozen=True, array_like=True):
    content: str
    recur: Literal["Daily", "Weekly"] | None = None


class VersionableTree(discord.app_commands.CommandTree["Salamander"]):
    async def interaction_check(self, interaction: discord.Interaction[Salamander]) -> bool:
        if interaction.client.is_blocked(interaction.user.id):
            await interaction.response.send_message("Nope.", ephemeral=True)
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


class Salamander(discord.AutoShardedClient):
    def __init__(
        self, *args: Any, intents: discord.Intents, sched: scheduler.DiscordBotScheduler, **kwargs: Any
    ) -> None:
        super().__init__(*args, intents=intents, **kwargs)
        self.tree = VersionableTree(
            self,
            fallback_to_global=False,
            allowed_contexts=discord.app_commands.AppCommandContext(dm_channel=True, guild=True, private_channel=True),
            allowed_installs=discord.app_commands.AppInstallationType(user=True, guild=False),
        )
        db_path = platformdir_stuff.user_data_path / "salamander.db"
        self.conn: apsw.Connection = apsw.Connection(str(db_path.resolve()))
        self.block_cache: LRU[int, bool] = LRU(512)
        self.sched: scheduler.DiscordBotScheduler = sched

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
        self.tree.add_command(raw_content)
        self.tree.add_command(user_avatar)
        self.tree.add_command(get_note_ctx)
        self.tree.add_command(add_note_ctx)
        self.tree.add_command(tag_group)
        self.tree.add_command(dice_group)
        path = platformdir_stuff.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash(self.tree)
        with path.open(mode="r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)

    async def get_channel_for_user(self, user_id: int) -> discord.DMChannel:
        """Might warrant a PR upstream for this given app commands"""
        await self.wait_until_ready()
        state = self._connection
        channel = state._get_private_channel_by_user(user_id)  # pyright: ignore[reportPrivateUsage]
        if channel is not None:
            return channel
        data = await state.http.start_private_message(user_id)
        return state.add_dm_channel(data)

    async def on_sinbad_scheduler_reminder(self, event: scheduler.ScheduledDispatch) -> None:
        user_id = event.associated_user
        reminder = event.unpack_extra(Reminder)
        if reminder and user_id:
            embed = discord.Embed(description=reminder.content, title="Your requested reminder")

            try:
                channel = await self.get_channel_for_user(user_id)
                await channel.send(embed=embed)
            except discord.HTTPException as exc:
                logging.warning("Could not handle reminder %r due to exception", event, exc_info=exc)

            if reminder.recur:
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


def _get_stored_token() -> str | None:
    token_file_path = platformdir_stuff.user_config_path / "salamander.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="r") as fp:
        data = fp.read()
        return base2048.decode(data).decode("utf-8") if data else None


def _store_token(token: str, /) -> None:
    token_file_path = platformdir_stuff.user_config_path / "salamander.token"
    token_file_path = resolve_path_with_links(token_file_path)
    with token_file_path.open(mode="w") as fp:
        fp.write(base2048.encode(token.encode()))


def _get_token() -> str:
    # TODO: alternative token stores: systemdcreds, etc
    token = os.getenv("ROLEBOT_TOKEN") or _get_stored_token()
    if not token:
        msg = "NO TOKEN? (Use Environment `ROLEBOT_TOKEN` or launch with `--setup` to go through interactive setup)"
        raise RuntimeError(msg) from None
    return token


def run_setup() -> None:
    prompt = (
        "Paste the discord token you'd like to use for this bot here (won't be visible) then press enter. "
        "This will be stored for later use >"
    )
    token = getpass.getpass(prompt)
    if not token:
        msg = "Not storing empty token"
        raise RuntimeError(msg)
    _store_token(token)


def run_bot() -> None:
    discord.utils.setup_logging()
    asyncio.run(entrypoint())


async def entrypoint() -> None:
    sched = scheduler.DiscordBotScheduler(platformdir_stuff.user_data_path / "scheduled.db")
    async with sched:
        client = Salamander(intents=discord.Intents.none(), sched=sched)
        async with client:
            await client.start(_get_token())


def ensure_schema() -> None:
    # The below is a hack of a solution, but it only runs against a trusted file
    # I don't want to have the schema repeated in multiple places

    db_path = platformdir_stuff.user_data_path / "salamander.db"
    conn = apsw.Connection(str(db_path))
    cursor = conn.cursor()

    schema_location = (Path(__file__)).with_name("schema.sql")
    with schema_location.open(mode="r") as f:
        to_execute: list[str] = []
        for line in f.readlines():
            text = line.strip()
            # This isn't naive escaping, it's removing comments in a trusted file
            if text and not text.startswith("--"):
                to_execute.append(text)

    # And this is just splitting statements at semicolons without removing the semicolons
    for match in re.finditer(r"[^;]+;", " ".join(to_execute)):
        cursor.execute(match.group(0))


def main() -> None:
    os.umask(0o077)
    apsw.bestpractice.apply(apsw.bestpractice.recommended)  # pyright: ignore[reportUnknownMemberType]
    parser = argparse.ArgumentParser(description="A minimal configuration discord bot for role menus")
    excl_setup = parser.add_mutually_exclusive_group()
    excl_setup.add_argument("--setup", action="store_true", default=False, help="Run interactive setup.", dest="isetup")
    excl_setup.add_argument(
        "--set-token-to",
        default=None,
        dest="token",
        help="Provide a token directly to be stored for use.",
    )
    args = parser.parse_args()

    if args.isetup:
        run_setup()
    elif args.token:
        _store_token(args.token)
    else:
        ensure_schema()
        run_bot()


if __name__ == "__main__":
    main()
