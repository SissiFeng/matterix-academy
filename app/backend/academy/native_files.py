"""Small local IPC primitives; no simulator or AWS imports."""

import json
import mmap
import os
import struct
import time
from pathlib import Path

WIDTH, HEIGHT = 960, 540
HEADER = struct.Struct("<QIIQd")
PIXELS = WIDTH * HEIGHT * 3


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def alive_lease(folder):
    try:
        return read_json(Path(folder) / "lease.json")["lease_expires"] > time.time() + 2
    except (OSError, ValueError, KeyError):
        return False


class FrameBuffer:
    """Single writer, read-only seqlock snapshots in host shared memory."""

    def __init__(self, path, create=False):
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY
        fd = os.open(path, flags, 0o600)
        try:
            if create:
                os.ftruncate(fd, HEADER.size + PIXELS)
            self.memory = mmap.mmap(
                fd, HEADER.size + PIXELS, access=mmap.ACCESS_WRITE if create else mmap.ACCESS_READ
            )
        finally:
            os.close(fd)
        self.sequence = 0

    def write(self, rgb, tick):
        if len(rgb) != PIXELS:
            raise ValueError("Viewport must produce 960 by 540 RGB frames")
        self.sequence += 2
        stamp = time.time()
        self.memory[: HEADER.size] = HEADER.pack(self.sequence - 1, WIDTH, HEIGHT, tick, stamp)
        self.memory[HEADER.size :] = rgb
        self.memory[: HEADER.size] = HEADER.pack(self.sequence, WIDTH, HEIGHT, tick, stamp)

    def read(self):
        for _ in range(3):
            header = self.memory[: HEADER.size]
            seq, width, height, tick, stamp = HEADER.unpack(header)
            if seq == 0 or seq % 2 or (width, height) != (WIDTH, HEIGHT):
                continue
            rgb = self.memory[HEADER.size :]
            if header == self.memory[: HEADER.size]:
                return rgb, tick, stamp
        return None

    def close(self):
        self.memory.close()
