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
import logging.handlers
import os
import queue
import re
import signal
from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Self

import apsw
import apsw.bestpractice
import discord
import msgspec
import scheduler
import xxhash

from . import base2048, dice, infotools, notes, tags
from ._type_stuff import RawSubmittable
from .utils import LRU, platformdir_stuff, resolve_path_with_links

log = logging.getLogger(__name__)


class Reminder(msgspec.Struct, gc=False, frozen=True, array_like=True):
    content: str
    recur: Literal["Daily", "Weekly"] | None = None


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

_missing: Any = object()


class Salamander(discord.AutoShardedClient):
    def __init__(
        self,
        *args: Any,
        intents: discord.Intents,
        conn: apsw.Connection,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, intents=intents, **kwargs)
        self.raw_submits: dict[str, RawSubmittable] = {}
        self.tree = VersionableTree(
            self,
            fallback_to_global=False,
            allowed_contexts=discord.app_commands.AppCommandContext(dm_channel=True, guild=True, private_channel=True),
            allowed_installs=discord.app_commands.AppInstallationType(user=True, guild=False),
        )
        self.conn: apsw.Connection = conn
        self.block_cache: LRU[int, bool] = LRU(512)
        self.sched: scheduler.DiscordBotScheduler = _missing

    async def on_interaction(self, interaction: discord.Interaction[Self]) -> None:
        if interaction.type is discord.InteractionType.modal_submit:
            assert interaction.data is not None
            custom_id = interaction.data.get("custom_id", "")
            if match := modal_regex.match(custom_id):
                modal_name, data = match.groups()
                if rs := self.raw_submits.get(modal_name):
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

        for mod in (dice, infotools, notes, tags):
            exports = mod.exports
            if exports.commands:
                for command_obj in exports.commands:
                    self.tree.add_command(command_obj)
            if exports.raw_submits:
                self.raw_submits.update(exports.raw_submits)

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


@contextmanager
def with_logging() -> Generator[None]:
    q: queue.SimpleQueue[Any] = queue.SimpleQueue()
    q_handler = logging.handlers.QueueHandler(q)
    stream_h = logging.StreamHandler()

    log_path = resolve_path_with_links(platformdir_stuff.user_log_path, folder=True)
    log_loc = log_path / "salamander.log"
    rotating_file_handler = logging.handlers.RotatingFileHandler(log_loc, maxBytes=2_000_000, backupCount=5)

    # intentional, discord.py won't use the stream coloring if passed the queue handler
    discord.utils.setup_logging(handler=stream_h)
    discord.utils.setup_logging(handler=rotating_file_handler)

    root_logger = logging.getLogger()
    root_logger.removeHandler(stream_h)
    root_logger.removeHandler(rotating_file_handler)

    # add the queue listener for this
    q_listener = logging.handlers.QueueListener(q, stream_h, rotating_file_handler)
    root_logger.addHandler(q_handler)

    try:
        q_listener.start()
        yield
    finally:
        q_listener.stop()


def run_bot() -> None:
    db_path = platformdir_stuff.user_data_path / "salamander.db"
    conn = apsw.Connection(str(db_path))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = Salamander(intents=discord.Intents.none(), conn=conn)

    async def entrypoint() -> None:
        sched = scheduler.DiscordBotScheduler(platformdir_stuff.user_data_path / "scheduled.db")
        async with sched:
            try:
                async with client:
                    await client.start(_get_token(), scheduler=sched)
            finally:
                if not client.is_closed():
                    await client.close()

    try:
        loop.add_signal_handler(signal.SIGINT, lambda: loop.stop())
        loop.add_signal_handler(signal.SIGTERM, lambda: loop.stop())
    except NotImplementedError:
        pass
    loop.set_task_factory(asyncio.eager_task_factory)

    def stop_when_done(fut: asyncio.Future[None]):
        loop.stop()

    fut = asyncio.ensure_future(entrypoint(), loop=loop)
    try:
        fut.add_done_callback(stop_when_done)
        loop.run_forever()
    except KeyboardInterrupt:
        log.info("Shutting down via keyboard interrupt.")
    finally:
        fut.remove_done_callback(stop_when_done)
        if not client.is_closed():
            # give the client a brief opportunity to close
            _close_task = loop.create_task(client.close())  # noqa: RUF006
        loop.run_until_complete(asyncio.sleep(0.001))

        tasks: set[asyncio.Task[Any]] = {t for t in asyncio.all_tasks(loop) if not t.done()}

        async def limited_finalization():
            _done, pending = await asyncio.wait(tasks, timeout=0.1)
            if not pending:
                log.debug("Clean shutdown accomplished.")
                return

            for task in tasks:
                task.cancel()

            _done, pending = await asyncio.wait(tasks, timeout=0.1)

            for task in pending:
                name = task.get_name()
                coro = task.get_coro()
                log.warning("Task %s wrapping coro %r did not exit properly", name, coro)

        loop.run_until_complete(limited_finalization())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())

        for task in tasks:
            try:
                if (exc := task.exception()) is not None:
                    loop.call_exception_handler(
                        {
                            "message": "Unhandled exception in task during shutdown.",
                            "exception": exc,
                            "task": task,
                        }
                    )
            except (asyncio.InvalidStateError, asyncio.CancelledError):
                pass

        asyncio.set_event_loop(None)
        loop.close()

        if not fut.cancelled():
            try:
                fut.result()
            except KeyboardInterrupt:
                pass

    conn.pragma("analysis_limit", 400)
    conn.pragma("optimize")


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
    parser = argparse.ArgumentParser(description="Small suite of user installable tools")
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
        with with_logging():
            ensure_schema()
            run_bot()


if __name__ == "__main__":
    main()
