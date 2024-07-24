"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
from pathlib import Path
from typing import Any

import apsw
import discord
import msgspec
import xxhash

from . import base2048
from .dice import dice_group
from .notes import add_note_ctx, get_note_ctx
from .utils import platformdir_stuff, resolve_path_with_links


class VersionableTree(discord.app_commands.CommandTree):
    async def get_hash(self, tree: discord.app_commands.CommandTree) -> bytes:
        commands = sorted(self._get_all_commands(guild=None), key=lambda c: c.qualified_name)

        translator = self.translator
        if translator:
            payload = [await command.get_translated_payload(tree, translator) for command in commands]
        else:
            payload = [command.to_dict(tree) for command in commands]

        return xxhash.xxh64_digest(msgspec.msgpack.encode(payload), seed=0)


class Salamander(discord.AutoShardedClient):
    def __init__(self, *args: Any, intents: discord.Intents, **kwargs: Any) -> None:
        super().__init__(*args, intents=intents, **kwargs)
        self.tree = VersionableTree(
            self,
            fallback_to_global=False,
            allowed_contexts=discord.app_commands.AppCommandContext(dm_channel=True, guild=True, private_channel=True),
            allowed_installs=discord.app_commands.AppInstallationType(user=True, guild=False),
        )
        db_path = platformdir_stuff.user_data_path / "salamander.db"
        self.conn: apsw.Connection = apsw.Connection(str(db_path.resolve()))

    async def setup_hook(self) -> None:
        self.tree.add_command(dice_group)
        self.tree.add_command(add_note_ctx)
        self.tree.add_command(get_note_ctx)
        path = platformdir_stuff.user_cache_path / "tree.hash"
        path = resolve_path_with_links(path)
        tree_hash = await self.tree.get_hash(self.tree)
        with path.open(mode="r+b") as fp:
            data = fp.read()
            if data != tree_hash:
                await self.tree.sync()
                fp.seek(0)
                fp.write(tree_hash)


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
    token = _get_token()
    client = Salamander(intents=discord.Intents.none())
    client.run(token)


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
