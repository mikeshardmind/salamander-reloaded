"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Final, Protocol, TypeVar, runtime_checkable

import apsw
import apsw.ext

from .utils import platformdir_stuff, resolve_path_with_links

_T_contra = TypeVar("_T_contra", contravariant=True)


class SupportsWrite(Protocol[_T_contra]):
    def write(self, s: _T_contra, /) -> object: ...


@runtime_checkable
class SupportsWriteAndisatty(Protocol[_T_contra]):
    def write(self, s: _T_contra, /) -> object: ...
    def isatty(self) -> bool: ...


type Stream[T] = SupportsWrite[T] | SupportsWriteAndisatty[T]


class KnownWarningFilter(logging.Filter):
    known_messages = (
        "Guilds intent seems to be disabled. This may cause state related issues.",
        "PyNaCl is not installed, voice will NOT be supported",
    )

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        return record.msg not in self.known_messages


dt_fmt = "%Y-%m-%d %H:%M:%S"
FMT = logging.Formatter("[%(asctime)s] [%(levelname)-8s}] %(name)s: %(message)s", dt_fmt)


_MSG_PREFIX = "\x1b[30;1m%(asctime)s\x1b[0m "
_MSG_POSTFIX = "%(levelname)-8s\x1b[0m \x1b[35m%(name)s\x1b[0m %(message)s"


class AnsiTermFormatter(logging.Formatter):
    LC = (
        (logging.DEBUG, "\x1b[40;1m"),
        (logging.INFO, "\x1b[34;1m"),
        (logging.WARNING, "\x1b[33;1m"),
        (logging.ERROR, "\x1b[31m"),
        (logging.CRITICAL, "\x1b[41m"),
    )

    FORMATS: Final = {
        level: logging.Formatter(_MSG_PREFIX + color + _MSG_POSTFIX, "%Y-%m-%d %H:%M:%S")
        for level, color in LC
    }

    def format(self, record: logging.LogRecord) -> str:
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f"\x1b[31m{text}\x1b[0m"
        output = formatter.format(record)
        record.exc_text = None
        return output


def use_color_formatting(stream: Stream[str]) -> bool:
    is_a_tty = isinstance(stream, SupportsWriteAndisatty) and stream.isatty()

    if os.environ.get("TERM_PROGRAM") == "vscode":
        return is_a_tty

    if sys.platform == "win32":
        if "WT_SESSION" not in os.environ:
            return False

    return is_a_tty


@contextmanager
def with_logging() -> Generator[None]:
    q: queue.SimpleQueue[Any] = queue.SimpleQueue()
    q_handler = logging.handlers.QueueHandler(q)
    q_handler.addFilter(KnownWarningFilter())
    stream_h = logging.StreamHandler()

    log_path = resolve_path_with_links(platformdir_stuff.user_log_path, folder=True)
    log_loc = log_path / "salamander.log"
    rotating_file_handler = logging.handlers.RotatingFileHandler(
        log_loc, maxBytes=2_000_000, backupCount=5
    )

    if use_color_formatting(sys.stderr):
        stream_h.setFormatter(AnsiTermFormatter())
    else:
        stream_h.setFormatter(FMT)

    rotating_file_handler.setFormatter(FMT)

    # add the queue listener for this
    q_listener = logging.handlers.QueueListener(q, stream_h, rotating_file_handler)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(q_handler)

    # Add apsw sqlite log forwarding
    apsw_log = logging.getLogger("apsw_forwarded")
    apsw.ext.log_sqlite(logger=apsw_log)

    try:
        q_listener.start()
        yield
    finally:
        q_listener.stop()
