"""Normalize only the hash-recognized Steam game, entirely from its own bytes."""

from __future__ import annotations

import hashlib
import struct

from gk3hd.patch.binary.aes import decrypt_cbc
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import PROTECTED_STEAM_SHA256, STEAM_NORMALIZED_BUILD, ProfileError

_HEADER_BYTES = 0xF0
_HEADER_MAGIC = 0xC0DEC0DF
_GAME_APP_ID = 497360
_TEXT_SHA256 = "7fc7cff8b489625db4b26ca5b7d4ce2664d8735bf87df5a153dda6b290ca635c"


def normalize_source(payload: bytes) -> bytes:
    """Decode the recognized Steam build; leave other source identities intact.

    The installer validates the original build before calling this function,
    and backs up that original, not this derived patching input. Unsupported
    Steam variants cannot enter the decoder by merely imitating a header.
    """
    if hashlib.sha256(payload).hexdigest() != PROTECTED_STEAM_SHA256:
        return payload
    image = PEFile(payload)
    code = image.get_section(".text")
    binding = image.get_section(".bind")
    if code is None or binding is None or image.sections[-1] is not binding:
        msg = "recognized Steam container has an unexpected section layout"
        raise ProfileError(msg)
    header_offset = image.va_to_offset(image.image_base + image.address_of_entry_point)
    encoded = struct.unpack_from("<60I", payload, header_offset - _HEADER_BYTES)
    # The container uses chained DWORD XOR; keys and stolen ciphertext come
    # from this local header, never bundled metadata or another game build.
    header = struct.pack(
        "<60I", encoded[0], *(encoded[index] ^ encoded[index - 1] for index in range(1, 60))
    )
    expected = (_HEADER_MAGIC, _GAME_APP_ID, code.virtual_address, code.size_of_raw_data)
    observed = (
        struct.unpack_from("<I", header, 0x04)[0],
        struct.unpack_from("<I", header, 0x38)[0],
        struct.unpack_from("<Q", header, 0x48)[0],
        struct.unpack_from("<Q", header, 0x50)[0],
    )
    if observed != expected:
        msg = "recognized Steam container has an unexpected code descriptor"
        raise ProfileError(msg)
    key = header[0x58:0x78]
    iv = decrypt_cbc(key, bytes(16), header[0x78:0x88])
    ciphertext = image.read_bytes(code.pointer_to_raw_data, code.size_of_raw_data)
    decoded = decrypt_cbc(key, iv, header[0x88:0x98] + ciphertext[:-16])
    if hashlib.sha256(decoded).hexdigest() != _TEXT_SHA256:
        msg = "decoded Steam game code failed its independent SHA-256 check"
        raise ProfileError(msg)
    output = bytearray(payload[: binding.pointer_to_raw_data])
    output[code.pointer_to_raw_data : code.pointer_to_raw_data + len(decoded)] = decoded
    # The wrapper does not change the original size-of-code/data fields.
    # Remove its final section and unused DOS payload; retain all game RVAs.
    output[binding.header_offset : binding.header_offset + 40] = bytes(40)
    output[0x40 : image.pe_offset] = bytes(image.pe_offset - 0x40)
    struct.pack_into("<H", output, image.coff_offset + 2, image.number_of_sections - 1)
    original_entry = struct.unpack_from("<Q", header, 0x20)[0]
    struct.pack_into("<I", output, image.optional_offset + 16, original_entry)
    struct.pack_into("<I", output, image.optional_offset + 56, binding.virtual_address)
    struct.pack_into("<I", output, image.optional_offset + 64, 0)  # PE checksum is optional.
    if hashlib.sha256(output).hexdigest() != STEAM_NORMALIZED_BUILD.original_sha256:
        msg = "normalized Steam executable failed its complete known-build SHA-256 check"
        raise ProfileError(msg)
    return bytes(output)
