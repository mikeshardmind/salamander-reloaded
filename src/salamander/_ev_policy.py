"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    def get_event_loop_policy() -> type[asyncio.AbstractEventLoopPolicy]:
        # moving a typing based *Accurate statement* here because pyright is dumb
        ...

else:

    def get_event_loop_policy() -> type[asyncio.AbstractEventLoopPolicy]:
        policy: type[asyncio.AbstractEventLoopPolicy] = asyncio.DefaultEventLoopPolicy

        if sys.platform in ("win32", "cygwin", "cli"):
            try:
                import winloop
            except ImportError:
                policy = asyncio.WindowsSelectorEventLoopPolicy
            else:
                policy = winloop.EventLoopPolicy

        else:
            try:
                import uvloop
            except ImportError:
                pass
            else:
                policy = uvloop.EventLoopPolicy

        return policy
