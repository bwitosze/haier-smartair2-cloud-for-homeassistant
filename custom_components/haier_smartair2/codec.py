"""Protocol codecs for Haier SmartAir2 devices.

Two device generations speak slightly different smartair2 dialects; both wrap the
same frame envelope but lay out the status/command block differently:

* V2 (e.g. salon, cloud): status ``6d01`` = 12 big-endian 16-bit words; command
  ``4d5f`` = full 24-byte block (read-modify-write).
* V3 (e.g. maks, local): status ``6d01`` = byte layout; command ``6001`` = first
  10 bytes of the status block (read-modify-write).

The codec is transport-agnostic — it only deals with smartair2 frames. Envelope
handling (cloud EPP base64 / local 80-byte wrapper) lives in the transport layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MID,
    MODE_AUTO,
    MODE_COOL,
    MODE_DRY,
    MODE_FAN,
    MODE_HEAT,
)


@dataclass
class HaierState:
    """Normalised device state decoded from a status frame."""

    power: bool | None = None
    mode: int | None = None  # MODE_* constant
    fan: int | None = None  # FAN_* constant
    quiet: bool | None = None  # 20200P super-silent (V2 only)
    turbo: bool | None = None  # 20200O powerful/boost (V2 only)
    target_temp: float | None = None
    current_temp: float | None = None
    raw_block: bytes = b""  # the status data block, for read-modify-write

    def merged(self, **changes: object) -> "HaierState":
        data = {**self.__dict__, **changes}
        return HaierState(**data)


def _checksum(body: bytes) -> int:
    return sum(body) & 0xFF


def build_frame(ftype: int, subcmd: bytes, data: bytes) -> bytes:
    """Assemble a smartair2 frame: FF FF | len | flags | res(5) | type | sub | data | chk."""
    length = 8 + len(subcmd) + len(data)
    body = bytes([length, 0, 0, 0, 0, 0, 0, ftype]) + subcmd + data
    return b"\xff\xff" + body + bytes([_checksum(body)])


def extract_block(frame: bytes) -> tuple[int, bytes]:
    """Return (frame_type, data-block) from a smartair2 frame, stripping sub+checksum(+crc)."""
    if len(frame) < 12 or frame[0] != 0xFF or frame[1] != 0xFF:
        raise ValueError("not a smartair2 frame")
    length = frame[2]
    flags = frame[3]
    ftype = frame[9]
    crc = 2 if flags & 0x40 else 0
    # data starts after subcmd (2 bytes at [10:12]); ends before checksum(+crc)
    end = 2 + length - crc
    return ftype, frame[12:end]


POLL_FRAME = build_frame(0x01, b"\x4d\x01", b"")  # query status -> 6d01


class Codec:
    """Base codec (subclassed per device generation)."""

    poll = POLL_FRAME
    # extra fan-selector entries beyond auto/low/medium/high (device-specific)
    extra_fan_modes: tuple[str, ...] = ()

    def decode(self, frame: bytes) -> HaierState:  # pragma: no cover - interface
        raise NotImplementedError

    def encode_set(self, state: HaierState, **changes) -> bytes:  # pragma: no cover
        raise NotImplementedError


_QUIET_BIT = 1 << 2  # 20200P (word 10 bit 2)
_TURBO_BIT = 1 << 1  # 20200O (word 10 bit 1)


class CodecV2(Codec):
    """Salon-class device (word layout, 4d5f command). Verified via cloud."""

    extra_fan_modes = ("quiet", "turbo")

    def decode(self, frame: bytes) -> HaierState:
        _ftype, data = extract_block(frame)
        w = [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data) - 1, 2)]
        if len(w) < 12:
            raise ValueError("short V2 status")
        return HaierState(
            current_temp=float(w[0]),
            mode=w[5],
            fan=w[6],
            quiet=bool(w[9] & _QUIET_BIT),
            turbo=bool(w[9] & _TURBO_BIT),
            power=bool(w[8] & 0x01),
            target_temp=float(w[11] + 16),
            raw_block=bytes(data),
        )

    def encode_set(self, state: HaierState, **changes) -> bytes:
        mode = changes.get("mode", state.mode) or 0
        fan = changes.get("fan", state.fan) or 0
        target = changes.get("target_temp", state.target_temp) or 16
        power = changes.get("power", state.power)
        # preserve swing / misc words from the last status block
        w8 = w10 = w11 = 0
        if len(state.raw_block) >= 24:
            src = state.raw_block
            w8 = int.from_bytes(src[14:16], "big")   # swing
            w10 = int.from_bytes(src[18:20], "big")  # fresh-air / turbo / quiet / display bits
            w11 = int.from_bytes(src[20:22], "big")
        # quiet / turbo live in word 10; flip only their bits, preserve the rest
        if "quiet" in changes and changes["quiet"] is not None:
            w10 = (w10 | _QUIET_BIT) if changes["quiet"] else (w10 & ~_QUIET_BIT)
        if "turbo" in changes and changes["turbo"] is not None:
            w10 = (w10 | _TURBO_BIT) if changes["turbo"] else (w10 & ~_TURBO_BIT)
        flags9 = 0x0001 if (power if power is not None else True) else 0x0000
        blk = bytearray(24)
        blk[10:12] = int(mode).to_bytes(2, "big")       # w6 mode
        blk[12:14] = int(fan).to_bytes(2, "big")        # w7 fan
        blk[14:16] = int(w8).to_bytes(2, "big")         # w8 swing (preserved)
        blk[16:18] = int(flags9).to_bytes(2, "big")     # w9 flags (power bit0)
        blk[18:20] = int(w10 & 0xFFFF).to_bytes(2, "big")  # w10 (quiet/turbo)
        blk[20:22] = int(w11).to_bytes(2, "big")
        blk[22:24] = int(round(target) - 16).to_bytes(2, "big")  # w12 setpoint
        return build_frame(0x01, b"\x4d\x5f", bytes(blk))


# V3 (maks) mode byte encoding is only partially calibrated: 0x25=COOL, 0x85=HEAT.
_V3_MODE_FROM_RAW = {0x25: MODE_COOL, 0x85: MODE_HEAT}
_V3_MODE_TO_RAW = {MODE_COOL: 0x25, MODE_HEAT: 0x85}


class CodecV3(Codec):
    """Maks-class device (byte layout, 6001 command). Verified via local TCP.

    Only setpoint / power / (cool,heat) mode are firmly calibrated. Fan and
    current temperature are best-effort and may be refined later.
    """

    def decode(self, frame: bytes) -> HaierState:
        _ftype, d = extract_block(frame)
        if len(d) < 10:
            raise ValueError("short V3 status")
        current = None
        if len(d) > 10 and d[10] > 10:
            current = float(d[10]) / 2.0  # dongle reports room temp in 0.5C steps (x2)
        return HaierState(
            target_temp=float(d[0] + 16),
            fan=d[1],
            mode=_V3_MODE_FROM_RAW.get(d[2], MODE_AUTO),
            power=bool(d[5] & 0x01),
            current_temp=current,
            raw_block=bytes(d),
        )

    def encode_set(self, state: HaierState, **changes) -> bytes:
        # read-modify-write on the first 10 bytes of the last status block
        block = bytearray(state.raw_block[:10].ljust(10, b"\x00"))
        if "target_temp" in changes and changes["target_temp"] is not None:
            block[0] = (int(round(changes["target_temp"])) - 16) & 0xFF
        if "fan" in changes and changes["fan"] is not None:
            block[1] = int(changes["fan"]) & 0xFF
        if "mode" in changes and changes["mode"] is not None:
            raw = _V3_MODE_TO_RAW.get(changes["mode"])
            if raw is not None:
                block[2] = raw
        if "power" in changes and changes["power"] is not None:
            if changes["power"]:
                block[5] |= 0x01
            else:
                block[5] &= ~0x01
        return build_frame(0x01, b"\x60\x01", bytes(block))


def codec_for_type(type_identifier: str | None) -> Codec:
    """Pick a codec by the device typeIdentifier (per Stadnicki's V2/V3 split)."""
    if type_identifier and len(type_identifier) > 32:
        return CodecV3()
    return CodecV2()
