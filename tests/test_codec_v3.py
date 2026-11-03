"""CodecV3 against the frames in .ai/changes/haier-ac-swing/capture.md (06 push frames)."""

import pytest

from conftest import codec

CodecV3 = codec.CodecV3

PREFIX = "ffff2a400000000000066d01"

# step -> raw hex, from the capture.md "Steps" table
FRAMES = {
    1: "ffff2a400000000000066d010808c300020100070000270049000001000000000000000000000000000000002c9e5f",
    2: "ffff2a400000000000066d010808c30002010000000029004900000100000000000000000000000000000000277c9a",
    3: "ffff2a400000000000066d010808c3000201000300002a0049000001000000000000000000000000000000002b2216",
    4: "ffff2a400000000000066d010808c3000201000400002a0049000001000000000000000000000000000000002c4cbc",
    5: "ffff2a400000000000066d010808c3000201000500002a0049000001000000000000000000000000000000002db5e8",
    6: "ffff2a400000000000066d010808c3000201000600002a0049000001000000000000000000000000000000002efe17",
    7: "ffff2a400000000000066d010808c3000201000700002a0049000001000000000000000000000000000000002f0743",
    8: "ffff2a400000000000066d01080cc3000201000700002a00490000010000000000000000000000000000000033c502",
    9: "ffff2a400000000000066d010802c3000201000700002a0049000001000000000000000000000000000000002902e3",
    10: "ffff2a400000000000066d010804c3000201000700002a0049000001000000000000000000000000000000002b0183",
    11: "ffff2a400000000000066d010806c3000201000700002a0049000001000000000000000000000000000000002dc0a2",
    12: "ffff2a400000000000066d010808c3000201000700002a0049000001000000000000000000000000000000002f0743",
    13: "ffff2a400000000000066d01080cc3000201000700002a00490000010000000000000000000000000000000033c502",
    14: "ffff2a400000000000066d01080cc30002030007000c2a00490000010000000000000000000000000000000041d5a8",
    15: "ffff2a400000000000066d01080cc3000201000700002a00490000010000000000000000000000000000000033c502",
    16: "ffff2a400000000000066d010801c3000201000700002a004900000100000000000000000000000000000000280353",
    17: "ffff2a400000000000066d010803c3000201000700002a0049000001000000000000000000000000000000002ac272",
    18: "ffff2a400000000000066d01080cc3000201000700002a00490000010000000000000000000000000000000033c502",
    19: "ffff2a400000000000066d01080cc3000001000700002a004900000100000000000000000000000000000000318507",
    20: "ffff2a400000000000066d01080cc3000201000700002a00490000010000000000000000000000000000000033c502",
    22: "ffff2a400000000000066d01090a830002010000000023004900000100000000000000000000000000000000e46ee0",
    23: "ffff2a400000000000066d01090a830003010000000023004900000100000000000000000000000000000000e5eee3",
    24: "ffff2a400000000000066d01090a830002010000000022004900000100000000000000000000000000000000e3a230",
    25: "ffff2a400000000000066d01070c230002010007001028004900000100000000000000000000000000000000a0f4c2",
    26: "ffff2a400000000000066d01070c23000201000700002800490000010000000000000000000000000000000090f80f",
}

# step -> (vane_v, vane_h, display, heat10, health, self_clean)
EXPECTED = {
    1: (0x08, 0x07, True, False, False, False),
    2: (0x08, 0x00, True, False, False, False),
    3: (0x08, 0x03, True, False, False, False),
    4: (0x08, 0x04, True, False, False, False),
    5: (0x08, 0x05, True, False, False, False),
    6: (0x08, 0x06, True, False, False, False),
    7: (0x08, 0x07, True, False, False, False),
    8: (0x0C, 0x07, True, False, False, False),
    9: (0x02, 0x07, True, False, False, False),
    10: (0x04, 0x07, True, False, False, False),
    11: (0x06, 0x07, True, False, False, False),
    12: (0x08, 0x07, True, False, False, False),
    13: (0x0C, 0x07, True, False, False, False),
    14: (0x0C, 0x07, True, False, True, False),
    15: (0x0C, 0x07, True, False, False, False),
    16: (0x01, 0x07, True, False, False, False),
    17: (0x03, 0x07, True, False, False, False),
    18: (0x0C, 0x07, True, False, False, False),
    19: (0x0C, 0x07, False, False, False, False),
    20: (0x0C, 0x07, True, False, False, False),
    22: (0x0A, 0x00, True, False, False, False),
    23: (0x0A, 0x00, True, True, False, False),
    24: (0x0A, 0x00, True, False, False, False),
    25: (0x0C, 0x07, True, False, False, True),
    26: (0x0C, 0x07, True, False, False, False),
}

# CodecV3.encode_set(target_temp=24) at fork commit cf113bf on the step 1 state
CF113BF_TARGET_24 = "ffff140000000000000160010808c30002010007000053"


def decode(step):
    return CodecV3().decode(bytes.fromhex(FRAMES[step]))


def encoded_block(step, **changes):
    state = decode(step)
    frame = CodecV3().encode_set(state, **changes)
    assert frame[10:12] == b"\x60\x01"
    return codec.extract_block(frame)[1]


@pytest.mark.parametrize("step", sorted(FRAMES))
def test_decode_new_fields(step):
    s = decode(step)
    assert (s.vane_v, s.vane_h, s.display, s.heat10, s.health, s.self_clean) == EXPECTED[step]


@pytest.mark.parametrize(
    ("changes", "block"),
    [
        ({"vane_v": codec.V3_VANE_V_AUTO}, "080cc300020100070000"),
        ({"vane_h": codec.V3_VANE_H_CENTER}, "0808c300020100000000"),
        ({"display": False}, "0808c300000100070000"),
        ({"heat10": True}, "0808c300030100070000"),
        ({"health": True}, "0808c30002030007000c"),
        ({"self_clean": True}, "0808c300020100070010"),
    ],
    ids=["vane_v", "vane_h", "display", "heat10", "health", "self_clean"],
)
def test_encode_each_new_key_changes_only_its_bytes(changes, block):
    assert encoded_block(1, **changes).hex() == block


def test_encode_health_on_with_temperature_write_keeps_d9_0c():
    assert encoded_block(14, target_temp=22).hex() == "060cc30002030007000c"


def test_encode_stale_d9_10_without_self_clean_is_cleared():
    assert encoded_block(25, target_temp=24).hex() == "080c2300020100070000"


def test_encode_target_temp_24_matches_cf113bf_output():
    state = decode(1)
    assert CodecV3().encode_set(state, target_temp=24).hex() == CF113BF_TARGET_24
