"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.

Copyright (C) 2023 Michael Hall <https://github.com/mikeshardmind>
"""

# This creates src/salamander/b2048.zlib
# as the object is used, it shouldnt be possible for this to be malicious
# but it's here for reproducability anyway.
# This file should *never* need regeneration, it's lookup tables for a stable
# encoding

import struct
import zlib
from pathlib import Path

from .dec_table import dec
from .enc_table import enc


def write_data() -> None:
    packed = struct.pack("!4340H2048H", *dec, *map(ord, enc))
    compressed = zlib.compress(packed, level=9, wbits=-15)
    with Path(__file__).with_name("b2048.zlib").open(mode="wb") as fp:
        fp.write(compressed)
