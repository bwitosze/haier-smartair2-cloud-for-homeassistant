"""Swing name tables, MAC list parsing and the health-off encode, without Home Assistant."""

import pytest

from conftest import codec, const
from test_codec_v3 import encoded_block


@pytest.mark.parametrize("name", sorted(codec.V3_VANE_V_NAME_TO_RAW))
def test_vertical_name_round_trips(name):
    assert codec.vane_v_name(codec.V3_VANE_V_NAME_TO_RAW[name]) == name


@pytest.mark.parametrize("name", sorted(codec.V3_VANE_H_NAME_TO_RAW))
def test_horizontal_name_round_trips(name):
    assert codec.vane_h_name(codec.V3_VANE_H_NAME_TO_RAW[name]) == name


def test_unmapped_vertical_raw_is_none():
    assert codec.vane_v_name(0x0A) is None


def test_mac_list_ignores_blanks_and_colons():
    assert const.parse_mac_list("2C:37:C5:10:CB:46, ,abc") == {"2C37C510CB46"}


def test_mac_list_none_is_empty():
    assert const.parse_mac_list(None) == set()


def test_mac_list_uppercases():
    assert const.parse_mac_list("2c37c510cb46") == {"2C37C510CB46"}


def test_encode_health_off_clears_bit_and_d9():
    # step 14 has health on and d9=0c; turning it off must clear both
    assert encoded_block(14, health=False).hex() == "080cc300020100070000"
