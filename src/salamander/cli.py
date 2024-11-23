"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os

from .runner import run_bot
from .utils import store_token

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


def main() -> None:
    os.umask(0o077)

    parser = argparse.ArgumentParser(
        description="Small suite of user installable tools"
    )
    excl_setup = parser.add_mutually_exclusive_group()
    excl_setup.add_argument(
        "--setup",
        action="store_true",
        default=False,
        help="Run interactive setup.",
        dest="isetup",
    )
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
        store_token(args.token)
    else:
        run_bot()


if __name__ == "__main__":
    main()
