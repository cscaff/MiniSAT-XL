#!/usr/bin/env python3
"""Convert flat binary to plain hex (one 32-bit little-endian word per line)."""
import sys
import struct

src = sys.argv[1]
dst = sys.argv[2]

with open(src, "rb") as f:
    data = f.read()

# Pad to 4-byte boundary
while len(data) % 4:
    data += b"\x00"

with open(dst, "w") as f:
    for i in range(0, len(data), 4):
        word = struct.unpack_from("<I", data, i)[0]
        f.write(f"{word:08x}\n")
