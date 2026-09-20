"""File-container decoder vectors independent of any game binary."""

import pytest

from gk3hd.patch.binary.aes import decrypt_cbc


def test_nist_aes256_cbc_vector() -> None:
    # NIST SP 800-38A, F.2.5/F.2.6, all four blocks including CBC chaining.
    key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex(
        "f58c4c04d6e5f1ba779eabfb5f7bfbd6"
        "9cfc4e967edb808d679f777bc6702c7d"
        "39f23369a9d9bacfa530e26304231461"
        "b2eb05e2c39be9fcda6c19078c6a9d1b"
    )
    plaintext = bytes.fromhex(
        "6bc1bee22e409f96e93d7e117393172a"
        "ae2d8a571e03ac9c9eb76fac45af8e51"
        "30c81c46a35ce411e5fbc1191a0a52ef"
        "f69f2445df4f9b17ad2b417be66c3710"
    )
    assert decrypt_cbc(key, iv, ciphertext) == plaintext
    assert decrypt_cbc(key, iv, b"") == b""


@pytest.mark.parametrize("lengths", [(31, 16, 16), (32, 15, 16), (32, 16, 15)])
def test_incomplete_decoder_inputs_are_rejected(lengths: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError, match="complete blocks"):
        decrypt_cbc(*(bytes(length) for length in lengths))
