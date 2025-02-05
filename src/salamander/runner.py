"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import asyncio
import gc
import getpass
import logging
import os
import signal
import socket
import ssl
import threading
from pathlib import Path
from typing import Any

import aiohttp
import apsw
import apsw.bestpractice
import scheduler
import truststore
from async_utils.sig_service import SignalService, SpecialExit

from ._type_stuff import HasExports
from .logs import with_logging
from .utils import get_token, platformdir_stuff, store_token

log = logging.getLogger(__name__)


def run_setup() -> None:
    prompt = (
        "Paste the discord token you'd like to use for this bot here"
        "(won't be visible) then press enter. "
        "This will be stored for later use >"
    )
    token = getpass.getpass(prompt)
    if not token:
        msg = "Not storing empty token"
        raise RuntimeError(msg)
    store_token(token)


def _run_bot(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[signal.Signals]) -> None:
    db_path = str(platformdir_stuff.user_data_path / "salamander.db")

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

    inital_exts: list[HasExports] = [
        dice,
        infotools,
        notes,
        reminders,
        settings_commands,
        tags,
    ]

    from .bot import Salamander

    read_conn = apsw.Connection(db_path, flags=apsw.SQLITE_OPEN_READONLY)
    rw_conn = apsw.Connection(db_path)
    client = Salamander(
        conn=rw_conn, read_conn=read_conn, connector=connector, initial_exts=inital_exts
    )

    sched = scheduler.DiscordBotScheduler(
        platformdir_stuff.user_data_path / "scheduled.db", use_threads=True
    )

    async def bot_entrypoint():
        async with sched:
            try:
                async with client:
                    await client.start(get_token(), scheduler=sched)
            finally:
                if not client.is_closed():
                    await client.close()

    async def sig_handler():
        sig = await queue.get()
        if sig != SpecialExit.EXIT:
            log.info("Shutting down, recieved signal: %r", sig)
        loop.call_soon(loop.stop)

    async def entrypoint():
        t1 = asyncio.create_task(bot_entrypoint())
        t2 = asyncio.create_task(sig_handler())
        await asyncio.gather(t1, t2)

    def stop_when_done(fut: asyncio.Future[None]):
        loop.stop()

    fut = asyncio.ensure_future(entrypoint(), loop=loop)
    try:
        fut.add_done_callback(stop_when_done)
        loop.run_forever()
    finally:
        fut.remove_done_callback(stop_when_done)
        if not client.is_closed():
            # give the client a brief opportunity to close
            _close_task = loop.create_task(client.close())
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
                    loop.call_exception_handler({
                        "message": "Unhandled exception in task during shutdown.",
                        "exception": exc,
                        "task": task,
                    })
            except (asyncio.InvalidStateError, asyncio.CancelledError):
                pass

        asyncio.set_event_loop(None)
        loop.close()

        if not fut.cancelled():
            fut.result()

        read_conn.close()
        rw_conn.pragma("analysis_limit", 400)
        rw_conn.pragma("optimize")
        rw_conn.close()


def _wrapped_run_bot(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[signal.Signals],
    socket: socket.socket,
):
    try:
        _run_bot(loop, queue)
    finally:
        socket.send(SpecialExit.EXIT.to_bytes())


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


def run_bot() -> None:
    """Run the bot then exit the interpreter.
    This function intentionally takes full control of the main thread
    and purposes it for signal handling, constructing everything else
    required in other threads with and without event loop use in those threads.
    """
    gc.set_threshold(0)

    def conn_hook(connection: apsw.Connection):
        for hook in (
            apsw.bestpractice.connection_wal,
            apsw.bestpractice.connection_busy_timeout,
            apsw.bestpractice.connection_enable_foreign_keys,
            apsw.bestpractice.connection_dqs,
            apsw.bestpractice.connection_recursive_triggers,
            apsw.bestpractice.connection_optimize,
        ):
            hook(connection)

    apsw.connection_hooks.append(conn_hook)

    with with_logging():
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue[signal.Signals | SpecialExit] = asyncio.Queue()

        def _stop_loop_on_signal(s: signal.Signals | SpecialExit):
            loop.call_soon_threadsafe(queue.put_nowait, s)

        signal_service = SignalService()
        sock = signal_service.get_send_socket()

        bot_thread = threading.Thread(target=_wrapped_run_bot, args=(loop, queue, sock))

        signal_service.add_startup(ensure_schema)
        signal_service.add_startup(bot_thread.start)
        signal_service.add_signal_cb(_stop_loop_on_signal)
        signal_service.add_join(bot_thread.join)

        signal_service.run()

    # If any library is creating threads implicitly that continue running in the
    # background, we don't want to wait on them, and ideally will drop libraries
    # that are found to do this. Same with atexit handlers.
    # The only output to flushable streams is via logging which also flushes
    # before this point.
    # if this breaks anything, report what was broken as a problem, not this.
    os._exit(0)  # pyright: ignore[reportPrivateUsage]
