"""Headband Bluetooth LE packets, byte for byte as in device-firmware/PROTOCOL.md (version 1).

All numbers little-endian. Common 6-byte header: type u8, flags u8, seq u32.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

PROTOCOL_MAJOR, PROTOCOL_MINOR = 1, 1
TYPE_EEG, TYPE_MOV, TYPE_STATUS, TYPE_CONTACT = 0x01, 0x02, 0x03, 0x04
FLAG_CATCHUP = 0x01
FLAG_CONTACT_CHECK = 0x02     # EEG measured during a contact check: not for the model
Z_UNKNOWN = 0xFFFF            # contact packet: no contact / not measurable
TICKS_PER_S = 32768                      # headband crystal clock (t_dev)

EEG_N, EEG_CH = 16, 4                    # samples per channel per packet, channels
MOV_N = 5                                # movement samples per packet (25 Hz)
INT24_MIN, INT24_MAX = -(1 << 23), (1 << 23) - 1

_HDR = struct.Struct("<BBI")
_EEG = struct.Struct("<BBIIIBB")         # header + sample_index, t_dev, n, lead_off
_MOV = struct.Struct("<BBIIB")           # header + t_dev, n
_STATUS = struct.Struct("<BBIIHBBBbIHI")
_INFO = struct.Struct("<BB3s8sHBfBHfB")
_CONTACT = struct.Struct("<BBII5H")   # header + t_dev, impedance kOhm per electrode

EEG_SIZE = _EEG.size + EEG_N * EEG_CH * 3     # 208
MOV_SIZE = _MOV.size + MOV_N * 6 * 2          # 71
STATUS_SIZE = _STATUS.size                    # 26
INFO_SIZE = _INFO.size                        # 28
CONTACT_SIZE = _CONTACT.size                  # 20

# status state bits
ST_CHARGING, ST_CHARGER, ST_STREAMING, ST_LOW_BATTERY = 1, 2, 4, 8
# status error bits
ERR_EEG_SATURATION, ERR_IMU_OVERFLOW, ERR_FLASH_FULL = 1, 2, 4
ERR_WATCHDOG, ERR_BROWNOUT, ERR_EEG_CHIP, ERR_IMU_CHIP = 8, 16, 32, 64
# lead-off bits (EEG and status packets)
LEAD_LTOP, LEAD_LBOT, LEAD_RTOP, LEAD_RBOT, LEAD_BIAS = 1, 2, 4, 8, 16


@dataclass
class EegPacket:
    seq: int
    sample_index: int
    t_dev: int
    codes: np.ndarray            # (n, 4) int32 ADC codes, time points x channels
    lead_off: int = 0
    flags: int = 0


@dataclass
class MovPacket:
    seq: int
    t_dev: int
    raw: np.ndarray              # (n, 6) int16: acc x, y, z, gyro x, y, z
    flags: int = 0


@dataclass
class StatusPacket:
    seq: int
    t_dev: int
    battery_mv: int
    battery_pct: int
    state: int = ST_STREAMING
    lead_off: int = 0
    temp_c: int = 30
    unconfirmed: int = 0
    errors: int = 0
    uptime_s: int = 0
    flags: int = 0


@dataclass
class ContactPacket:
    """Result of a contact check: skin contact impedance per electrode (L-top, L-bottom, R-top,
    R-bottom, bias) in kOhm; Z_UNKNOWN = no contact."""
    seq: int
    t_dev: int
    impedance_kohm: tuple[int, int, int, int, int]
    flags: int = 0


@dataclass
class DeviceInfo:
    fw: tuple[int, int, int] = (1, 0, 0)
    serial: bytes = b"EPH00001"
    eeg_rate: int = 256
    eeg_channels: int = 4
    eeg_lsb_nv: float = 9.0 / 12 / 2 ** 24 * 1e9      # ±4.5 V reference, gain 12 -> 44.7 nV
    mov_rate: int = 25
    acc_lsb_per_g: int = 4096                          # BMI270 ±8 g
    gyr_lsb_per_dps: float = 16.4                      # BMI270 ±2000 °/s
    layout: int = 1
    major: int = PROTOCOL_MAJOR
    minor: int = PROTOCOL_MINOR

    def encode(self) -> bytes:
        return _INFO.pack(self.major, self.minor, bytes(self.fw), self.serial[:8].ljust(8, b"\0"),
                          self.eeg_rate, self.eeg_channels, self.eeg_lsb_nv, self.mov_rate,
                          self.acc_lsb_per_g, self.gyr_lsb_per_dps, self.layout)

    @staticmethod
    def decode(b: bytes) -> "DeviceInfo":
        ma, mi, fw, ser, er, ec, lsb, mr, acc, gyr, lay = _INFO.unpack(b)
        if ma != PROTOCOL_MAJOR:
            raise ValueError(f"unsupported headband protocol {ma}.{mi}")      # rule P6
        return DeviceInfo(tuple(fw), ser, er, ec, lsb, mr, acc, gyr, lay, ma, mi)


def _int24_bytes(codes: np.ndarray) -> bytes:
    u = (np.clip(codes, INT24_MIN, INT24_MAX).astype(np.int64) & 0xFFFFFF).astype("<u4")
    return u.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()


def _int24_values(b: bytes) -> np.ndarray:
    a = np.frombuffer(b, np.uint8).reshape(-1, 3).astype(np.int32)
    v = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
    return np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.int32)


def encode(p) -> bytes:
    if isinstance(p, EegPacket):
        n = len(p.codes)
        return _EEG.pack(TYPE_EEG, p.flags, p.seq & 0xFFFFFFFF, p.sample_index & 0xFFFFFFFF,
                         p.t_dev & 0xFFFFFFFF, n, p.lead_off) + _int24_bytes(np.asarray(p.codes).reshape(-1))
    if isinstance(p, MovPacket):
        raw = np.clip(np.asarray(p.raw), -32768, 32767).astype("<i2")
        return _MOV.pack(TYPE_MOV, p.flags, p.seq & 0xFFFFFFFF, p.t_dev & 0xFFFFFFFF, len(raw)) + raw.tobytes()
    if isinstance(p, StatusPacket):
        return _STATUS.pack(TYPE_STATUS, p.flags, p.seq & 0xFFFFFFFF, p.t_dev & 0xFFFFFFFF, p.battery_mv,
                            p.battery_pct, p.state, p.lead_off, p.temp_c, p.unconfirmed, p.errors, p.uptime_s)
    if isinstance(p, ContactPacket):
        return _CONTACT.pack(TYPE_CONTACT, p.flags, p.seq & 0xFFFFFFFF, p.t_dev & 0xFFFFFFFF, *p.impedance_kohm)
    raise TypeError(type(p))


def decode(b: bytes):
    t = b[0]
    if t == TYPE_EEG:
        _, fl, seq, si, td, n, lo = _EEG.unpack_from(b)
        codes = _int24_values(b[_EEG.size:_EEG.size + n * EEG_CH * 3]).reshape(n, EEG_CH)
        return EegPacket(seq, si, td, codes, lo, fl)
    if t == TYPE_MOV:
        _, fl, seq, td, n = _MOV.unpack_from(b)
        raw = np.frombuffer(b, "<i2", count=n * 6, offset=_MOV.size).reshape(n, 6).astype(np.int16)
        return MovPacket(seq, td, raw, fl)
    if t == TYPE_STATUS:
        _, fl, seq, td, mv, pct, st, lo, tc, un, err, up = _STATUS.unpack(b[:STATUS_SIZE])
        return StatusPacket(seq, td, mv, pct, st, lo, tc, un, err, up, fl)
    if t == TYPE_CONTACT:
        _, fl, seq, td, *z = _CONTACT.unpack(b[:CONTACT_SIZE])
        return ContactPacket(seq, td, tuple(z), fl)
    raise ValueError(f"unknown packet type {t:#x}")
