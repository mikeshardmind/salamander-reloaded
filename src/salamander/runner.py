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
import signal
import socket
import ssl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import aiohttp
import apsw
import apsw.bestpractice
import apsw.ext
import base2048
import discord
import scheduler
import truststore

from ._ev_policy import get_event_loop_policy
from ._type_stuff import HasExports
from .utils import platformdir_stuff, resolve_path_with_links

log = logging.getLogger(__name__)



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
    token = os.getenv("SALAMANDER_TOKEN") or _get_stored_token()
    if not token:
        msg = "NO TOKEN? (Use Environment `SALAMANDER_TOKEN` or launch with `--setup` to go through interactive setup)"
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


class KnownWarningFilter(logging.Filter):
    known_messages = (
        "Guilds intent seems to be disabled. This may cause state related issues.",
        "PyNaCl is not installed, voice will NOT be supported",
    )

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        return record.msg not in self.known_messages


@contextmanager
def with_logging() -> Generator[None]:
    q: queue.SimpleQueue[Any] = queue.SimpleQueue()
    q_handler = logging.handlers.QueueHandler(q)
    q_handler.addFilter(KnownWarningFilter())
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

    # Add apsw sqlite log forwarding
    apsw_log = logging.getLogger("apsw_forwarded")
    apsw.ext.log_sqlite(logger=apsw_log)

    try:
        q_listener.start()
        yield
    finally:
        q_listener.stop()


def run_bot() -> None:
    db_path = platformdir_stuff.user_data_path / "salamander.db"
    conn = apsw.Connection(str(db_path))

    policy_type = get_event_loop_policy()
    asyncio.set_event_loop_policy(policy_type())

    loop = asyncio.new_event_loop()
    loop.set_task_factory(asyncio.eager_task_factory)
    asyncio.set_event_loop(loop)

    # windows ssl root ca issues
    ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    connector = aiohttp.TCPConnector(
        happy_eyeballs_delay=None,
        family=socket.AddressFamily.AF_INET,
        ttl_dns_cache=60,
        loop=loop,
        ssl_context=ssl_ctx,
    )

    from . import dice, infotools, notes, reminders, settings_commands, tags

    inital_exts: list[HasExports] = [dice, infotools, notes, reminders, settings_commands, tags]

    from .bot import Salamander

    client = Salamander(
        intents=discord.Intents.none(), conn=conn, connector=connector, initial_exts=inital_exts,
    )
    sched = scheduler.DiscordBotScheduler(platformdir_stuff.user_data_path / "scheduled.db")

    async def entrypoint() -> None:

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
            _close_task = loop.create_task(client.close())  # noqa: RUF006, loop is closed in this scope
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

        if tasks:
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

    schema_location = (Path(__file__)).with_name("schema.sql")
    with schema_location.open(mode="r") as f:
        to_execute: list[str] = []
        for line in f.readlines():
            text = line.strip()
            # This isn't naive escaping, it's removing comments in a trusted file
            if not text.startswith("--"):
                to_execute.append(text)

    iterator = iter(to_execute)
    for line in iterator:
        s = [line]
        while n := next(iterator, None):
            s.append(n)
        statement = "\n".join(s)
        list(conn.execute(statement))


def main() -> None:
    os.umask(0o077)
    to_apply: tuple[Any, ...] = (
        apsw.bestpractice.connection_wal,
        apsw.bestpractice.connection_busy_timeout,
        apsw.bestpractice.connection_enable_foreign_keys,
        apsw.bestpractice.connection_dqs,
    )
    apsw.bestpractice.apply(to_apply)  # pyright: ignore[reportUnknownMemberType]
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