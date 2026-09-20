"""Small synthetic Steam caches: no user library metadata or credentials."""

import struct

from gk3hd.system.steam import VdfValue


def cache_bytes(records: dict[int, dict[str, VdfValue]], version: int = 41) -> bytes:
    keys: list[str] = []

    def key_bytes(key: str) -> bytes:
        if version < 41:
            return key.encode() + b"\0"
        if key not in keys:
            keys.append(key)
        return struct.pack("<I", keys.index(key))

    def object_bytes(values: dict[str, VdfValue]) -> bytes:
        parts = []
        for key, value in values.items():
            prefix = key_bytes(key)
            parts.append(
                b"\0" + prefix + object_bytes(value)
                if isinstance(value, dict)
                else b"\1" + prefix + value.encode() + b"\0"
            )
        return b"".join(parts) + b"\x08"

    entries = []
    for app_id, record in records.items():
        payload = bytes(40 if version == 39 else 60) + object_bytes(record)
        entries.append(struct.pack("<II", app_id, len(payload)) + payload)
    body = b"".join(entries) + bytes(4)
    header = struct.pack("<II", 0x07564400 | version, 1)
    if version < 41:
        return header + body
    table = struct.pack("<I", len(keys)) + b"".join(key.encode() + b"\0" for key in keys)
    return header + struct.pack("<Q", 16 + len(body)) + body + table
