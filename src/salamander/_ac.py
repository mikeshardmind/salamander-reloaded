"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2020 Michael Hall <https://github.com/mikeshardmind>
"""

from __future__ import annotations

from .bot import Interaction


def ac_cache_transform(
    args: tuple[Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[int, str], dict[str, object]]:
    itx, current = args
    return (itx.user.id, current), kwds


def casefolded_ac_cache_transform(
    args: tuple[Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[int, str], dict[str, object]]:
    itx, current = args
    return (itx.user.id, current.casefold()), kwds


def cf_ac_cache_transform_no_user(
    args: tuple[Interaction, str], kwds: dict[str, object]
) -> tuple[tuple[str], dict[str, object]]:
    _itx, current = args
    return (current.casefold(),), kwds
