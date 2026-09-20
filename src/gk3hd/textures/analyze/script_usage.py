"""Recognize literal boundary-map bindings in compiled Sheep scripts.

This is not a script interpreter. Only the verified literal five-argument
SetBoundaryMap call sequence establishes usage; unrelated string constants,
variable arguments and arbitrary matching bytes do not.
"""

from __future__ import annotations

import struct

_WORD = struct.Struct("<I")
_SHORT = struct.Struct("<H")
_OPERAND_OPS = frozenset((*range(0x02, 0x09), *range(0x0D, 0x16), 0x2D, 0x2E))
_CALL_SEQUENCE = (0x15, 0x33, 0x14, 0x14, 0x14, 0x14, 0x13, 0x02)
_BOUNDARY_SIGNATURE = b"\x00\x05\x03\x02\x02\x02\x02"
_BOUNDARY_ARGUMENTS = 5
_HEADER_SIZE = 28
_LAST_OPCODE = 0x34
_UNSUPPORTED_EXPORT = 0x0C


def script_data_textures(payload: bytes, available: set[str]) -> set[str]:
    """Find existing BMPs passed literally to the native boundary-map setter."""
    if not payload.startswith(b"GK3Sheep") or b"setboundarymap" not in payload.lower():
        return set()
    try:
        return _literal_bindings(payload) & available
    except (KeyError, ValueError, struct.error) as exc:
        message = "invalid compiled Sheep boundary-map binding"
        raise ValueError(message) from exc


def _literal_bindings(payload: bytes) -> set[str]:
    sections = _sections(payload)
    imports = _records(sections[b"SysImports"])
    setters = {index for index, (_, record) in enumerate(imports) if _is_setter(record)}
    if not setters:
        return set()
    strings = dict(_records(sections[b"StringConsts"]))
    code = _records(sections[b"Code"])
    if len(code) != 1 or code[0][0] != 0:
        raise ValueError
    instructions = _instructions(code[0][1])
    result = set()
    for start in range(len(instructions) - len(_CALL_SEQUENCE) + 1):
        window = instructions[start : start + len(_CALL_SEQUENCE)]
        if tuple(op for op, _ in window) != _CALL_SEQUENCE:
            continue
        if window[-2][1] != _BOUNDARY_ARGUMENTS or window[-1][1] not in setters:
            continue
        raw = strings[window[0][1]]
        if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
            raise ValueError
        stem = raw[:-1].decode("latin-1").upper().removesuffix(".BMP")
        if stem and "/" not in stem and "\\" not in stem:
            result.add(f"{stem}.BMP")
    return result


def _sections(payload: bytes) -> dict[bytes, bytes]:
    """Resolve bounded section records using the file's offset table."""
    header = _WORD.unpack_from(payload, 12)[0]
    count = _WORD.unpack_from(payload, 24)[0]
    if header != _WORD.unpack_from(payload, 16)[0] or not 28 + count * 4 <= header <= len(payload):
        raise ValueError
    sections = {}
    for index in range(count):
        start = header + _WORD.unpack_from(payload, 28 + 4 * index)[0]
        size = _WORD.unpack_from(payload, start + 12)[0]
        length = _WORD.unpack_from(payload, start + 20)[0]
        end = start + size + length
        name = payload[start : start + 12].rstrip(b"\0")
        if size < _HEADER_SIZE or end > len(payload) or name in sections:
            raise ValueError
        sections[name] = payload[start:end]
    return sections


def _records(section: bytes) -> list[tuple[int, bytes]]:
    """Read section-relative records without scanning content for signatures."""
    header, duplicate, size, count = struct.unpack_from("<4I", section, 12)
    if header != duplicate or header != 28 + count * 4 or header + size != len(section):
        raise ValueError
    offsets = [_WORD.unpack_from(section, 28 + 4 * index)[0] for index in range(count)]
    if offsets != sorted(set(offsets)) or any(offset >= size for offset in offsets):
        raise ValueError
    ends = [*offsets[1:], size] if offsets else []
    return [
        (offset, section[header + offset : header + end])
        for offset, end in zip(offsets, ends, strict=True)
    ]


def _is_setter(record: bytes) -> bool:
    """Require the exact native name and string/four-float signature."""
    size = _SHORT.unpack_from(record)[0]
    return (
        record[2 : 2 + size].lower() == b"setboundarymap"
        and record[2 + size : 3 + size] == b"\0"
        and record[3 + size :] == _BOUNDARY_SIGNATURE
    )


def _instructions(code: bytes) -> list[tuple[int, int]]:
    """Decode instruction boundaries; immediates cannot masquerade as calls."""
    result = []
    offset = 0
    while offset < len(code):
        opcode = code[offset]
        offset += 1
        if opcode > _LAST_OPCODE or opcode == _UNSUPPORTED_EXPORT:
            raise ValueError
        operand = 0
        if opcode in _OPERAND_OPS:
            operand = _WORD.unpack_from(code, offset)[0]
            offset += 4
        result.append((opcode, operand))
    return result
