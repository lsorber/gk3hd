"""AES-256-CBC decoding for the recognized local executable container.

This is a narrow file-format decoder, not a cryptographic security API: table
lookups are not constant-time, and there is no encryption or padding protocol.
The caller verifies the complete input and decoded output with SHA-256.
The algorithm follows FIPS 197; tests use the SP 800-38A known-answer vector.
No game keys or code are included here.
"""

from __future__ import annotations

import struct

_BLOCK_BYTES = 16
_KEY_BYTES = 32
_WORD_MASK = 0xFFFFFFFF
_ROUNDS = 14
_WORDS_PER_BLOCK = 4
type _State = tuple[int, int, int, int]


def _multiply(left: int, right: int) -> int:
    product = 0
    while right:
        if right & 1:
            product ^= left
        left = ((left << 1) ^ (0x11B if left & 0x80 else 0)) & 0xFF
        right >>= 1
    return product


def _substitution(value: int) -> int:
    # Multiplicative inverse in GF(2^8), followed by the AES affine map.
    inverse, power, exponent = 1, value, 254
    while exponent:
        if exponent & 1:
            inverse = _multiply(inverse, power)
        power = _multiply(power, power)
        exponent >>= 1
    result = inverse ^ 0x63
    for rotation in range(1, 5):
        result ^= ((inverse << rotation) | (inverse >> (8 - rotation))) & 0xFF
    return result


_SBOX = tuple(_substitution(value) for value in range(256))
_INVERSE = tuple(_SBOX.index(value) for value in range(256))
_TABLE0 = tuple(
    (_multiply(value, 14) << 24)
    | (_multiply(value, 9) << 16)
    | (_multiply(value, 13) << 8)
    | _multiply(value, 11)
    for value in _INVERSE
)
_TABLE1 = tuple(((word >> 8) | (word << 24)) & _WORD_MASK for word in _TABLE0)
_TABLE2 = tuple(((word >> 16) | (word << 16)) & _WORD_MASK for word in _TABLE0)
_TABLE3 = tuple(((word >> 24) | (word << 8)) & _WORD_MASK for word in _TABLE0)


def _sub_word(word: int) -> int:
    return sum(_SBOX[(word >> shift) & 0xFF] << shift for shift in (24, 16, 8, 0))


def _inverse_mix(word: int) -> int:
    return (
        _TABLE0[_SBOX[word >> 24]]
        ^ _TABLE1[_SBOX[(word >> 16) & 0xFF]]
        ^ _TABLE2[_SBOX[(word >> 8) & 0xFF]]
        ^ _TABLE3[_SBOX[word & 0xFF]]
    )


def _round_keys(key: bytes) -> tuple[_State, ...]:
    words = list(struct.unpack(">8I", key))
    round_constant = 1
    for index in range(8, 4 * (_ROUNDS + 1)):
        word = words[-1]
        if index % 8 == 0:
            word = _sub_word(((word << 8) | (word >> 24)) & _WORD_MASK)
            word ^= round_constant << 24
            round_constant = _multiply(round_constant, 2)
        elif index % 8 == _WORDS_PER_BLOCK:
            word = _sub_word(word)
        words.append(words[index - 8] ^ word)
    keys = []
    for offset in range(_ROUNDS * 4, -1, -4):
        group = words[offset : offset + 4]
        if offset not in (0, _ROUNDS * 4):
            group = [_inverse_mix(word) for word in group]
        keys.append((group[0], group[1], group[2], group[3]))
    return tuple(keys)


def _decrypt_block(state: _State, keys: tuple[_State, ...]) -> _State:
    a, b, c, d = (state[index] ^ keys[0][index] for index in range(4))
    for key in keys[1:-1]:
        a, b, c, d = (
            _TABLE0[a >> 24]
            ^ _TABLE1[(d >> 16) & 255]
            ^ _TABLE2[(c >> 8) & 255]
            ^ _TABLE3[b & 255]
            ^ key[0],
            _TABLE0[b >> 24]
            ^ _TABLE1[(a >> 16) & 255]
            ^ _TABLE2[(d >> 8) & 255]
            ^ _TABLE3[c & 255]
            ^ key[1],
            _TABLE0[c >> 24]
            ^ _TABLE1[(b >> 16) & 255]
            ^ _TABLE2[(a >> 8) & 255]
            ^ _TABLE3[d & 255]
            ^ key[2],
            _TABLE0[d >> 24]
            ^ _TABLE1[(c >> 16) & 255]
            ^ _TABLE2[(b >> 8) & 255]
            ^ _TABLE3[a & 255]
            ^ key[3],
        )
    state = (a, b, c, d)
    result = [
        (
            (_INVERSE[state[index] >> 24] << 24)
            | (_INVERSE[(state[(index - 1) % 4] >> 16) & 255] << 16)
            | (_INVERSE[(state[(index - 2) % 4] >> 8) & 255] << 8)
            | _INVERSE[state[(index - 3) % 4] & 255]
        )
        ^ keys[-1][index]
        for index in range(4)
    ]
    return result[0], result[1], result[2], result[3]


def decrypt_cbc(key: bytes, iv: bytes, payload: bytes) -> bytes:
    """Decode complete AES-256-CBC blocks without adding/removing padding."""
    if len(key) != _KEY_BYTES or len(iv) != _BLOCK_BYTES or len(payload) % _BLOCK_BYTES:
        msg = "AES-256-CBC requires a 32-byte key, 16-byte IV and complete blocks"
        raise ValueError(msg)
    keys = _round_keys(key)
    previous = struct.unpack(">4I", iv)
    output = bytearray(len(payload))
    for offset in range(0, len(payload), _BLOCK_BYTES):
        block = struct.unpack_from(">4I", payload, offset)
        decoded = _decrypt_block(block, keys)
        struct.pack_into(
            ">4I", output, offset, *(decoded[index] ^ previous[index] for index in range(4))
        )
        previous = block
    return bytes(output)
